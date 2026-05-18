# Phase: Code Review Report

**Reviewed:** 2026-05-17T12:00:00Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

This review covers all 28 source files in `src/relay/` (v0.4.1, Python 3.12+). The codebase is generally well-structured with consistent patterns (frozen dataclasses, Result type, layer isolation) and good security practices (HMAC via `compare_digest`, pipeline_id validation, secret length enforcement). However, several significant issues were found:

**CRITICAL (2):** The budget enforcement mechanism checks the *input* slice size against the token budget and per-agent limits, but `token_budget_used` only tracks *output* sizes. This means the budget check and the accounting measure different things -- the enforcement is checking the wrong metric. Steps can be allowed to run based on a small input projection while the actual output (which is what gets tracked) blows the budget.

**WARNING (4):** Rollback creates orphaned snapshot files; `_do_rollback` has fragile type dispatch; `apply_join_strategy` API is unsafe for FIRST_WINS; `AutoGenAdapter` accepts plain `object` with no structural validation.

---

## Critical Issues

### CR-01: Budget enforcement checks input slice cost against token budget, but accounting tracks only output size

**File:** `src/relay/core_pipeline.py:250-285`
**File:** `src/relay/budget/enforcer.py:23-47`
**File:** `src/relay/envelope.py:230-231` (create_next_envelope adds output tokens)

**Issue:** The budget enforcement in `_check_budget` and `HardCapEnforcer.check` uses the *input* slice (what the agent reads) as the projected cost. But `token_budget_used` in every envelope only accumulates the *output* sizes (via `estimate_tokens(agent_output)` in `create_next_envelope`). These are fundamentally different quantities that can diverge arbitrarily.

**Trace:**

1. `_check_budget(manifest, current_envelope)` at line 250 -- `current_envelope` is not None, so it enters the `if current_envelope is not None` branch at line 251.
2. Calls `_slice_payload(manifest, current_envelope)` at line 252 -- which serializes the current envelope's payload (the input that the agent will read), not the output the agent will produce.
3. `budget_used + projected > budget_total` at line 273 -- compares accumulated output against current input.
4. `create_next_envelope` at envelope.py:230-231 -- increments `token_budget_used` by `estimate_tokens(agent_output)` (the *output*).

**Concrete scenario:**

- token_budget_total = 1000, token_budget_used = 950 (near limit)
- Agent reads a small input slice of 30 tokens => budget check: 950 + 30 = 980 <= 1000 => **passes**
- Agent produces a large output of 200 tokens => token_budget_used = 950 + 200 = 1150 > 1000
- The budget is silently exceeded because the check measured input while tracking measures output.

Conversely, a large input could block an agent that would produce a tiny output, causing false positive denials.

**Severity:** BLOCKER -- budget enforcement is not just "advisory under concurrent load" as documented; it is structurally incorrect because it measures the wrong quantity. This undermines the hard-cap guarantee from the design document (Section 6: "The cap is a hard wall").

**Fix:** The budget projection should estimate the output size, not the input. One approach: use `estimate_tokens` on a projected output stub derived from `manifest.writes`, similar to the initial-step path:

```python
# In _check_budget, when current_envelope is not None:
# Estimate potential output based on manifest.writes (what the agent
# is expected to produce), not on the input context it reads.
projected = serialize_slice(
    dict[str, object]({s: "<stub>" for s in manifest.writes})
)
```

---

### CR-02: Per-agent max_tokens limit compared against input slice instead of output

**File:** `src/relay/core_pipeline.py:276-285`

**Issue:** The per-agent `manifest.max_tokens` check at line 277 uses the same `projected` variable from `_slice_payload`, which is the *input* context size. But `max_tokens` on an `AgentManifest` (slicer/manifest.py:28) is documented as "Maximum tokens allowed for this agent's context" -- conventionally an output or total limit. Comparing an input projection against this limit is semantically wrong.

```python
# Line 276-285 -- manifest.max_tokens evaluated against INPUT size
if manifest.max_tokens is not None:
    projected_cost = self._enforcer.counter.count(projected)  # projected = INPUT size
    if projected_cost > manifest.max_tokens:
        return Failure(...)  # Blocks based on input size, not output
```

An agent that reads 500 tokens of context but produces 50 tokens of output would be blocked if `max_tokens=100`. An agent that reads 10 tokens but produces 5000 tokens would pass the check but blow the limit.

**Severity:** BLOCKER -- the per-agent limit is enforced against the wrong metric, making it either over-restrictive or ineffective.

**Fix:** Replace `projected` (input size) with an estimate of the output size based on manifest.writes:

```python
if manifest.max_tokens is not None:
    output_stub = serialize_slice(
        dict[str, object]({s: "<output>" for s in manifest.writes})
    )
    projected_cost = self._enforcer.counter.count(output_stub)
    if projected_cost > manifest.max_tokens:
        return Failure(...)
```

---

## Warnings

### WR-01: _finalize_step creates orphaned snapshot files on rollback

**File:** `src/relay/core_pipeline.py:308-318`

**Issue:** When the validator triggers rollback in `_finalize_step`, the code saves `current_envelope` as a new snapshot at line 309:

```python
save_result = self._snapshot_store.save_snapshot(current_envelope)
```

This creates a new snapshot file with a fresh UUID. Then at line 312:

```python
self._state.register_snapshot(current_envelope.step, save_result.value)
```

This overwrites the in-memory snapshot ID for `current_envelope.step` with the new (duplicate) file. The previous snapshot file for this step (created when the step was originally committed) becomes orphaned -- it exists on disk but is no longer referenced by the index. Repeated rollbacks accumulate garbage snapshot files with no cleanup mechanism.

**Severity:** WARNING -- no data loss or correctness issue, but unbounded disk waste in pipelines with frequent rollbacks.

**Fix:** Skip the redundant `save_snapshot` on rollback -- the envelope was already snapshotted when it was first committed:

```python
# On rollback -- current_envelope already has a snapshot from its original commit
self._state.push_current_to_history()
return RollbackSuccess(
    value=current_envelope,
    reason=validation_result.value.contradiction_details or "Contradiction detected",
)
```

---

### WR-02: _do_rollback fragile against RollbackHandler returning Success

**File:** `src/relay/core_pipeline.py:380-384`
**File:** `src/relay/pipeline_rollback.py:44-48`

**Issue:** The `_do_rollback` method dispatches based on `isinstance(result, RollbackSuccess)` at line 380:

```python
result = self._rollback_handler.restore_to_previous(...)
if isinstance(result, RollbackSuccess):
    if consume:
        self._state.consume_last()
    self._state.set_current(result.value)
return result
```

Currently `restore_to_previous` returns `RollbackSuccess | Failure` (never `Success`). But if a future refactor introduces a `Success` return path, this guard would silently skip the state mutation (`set_current` is never called). The failure is returned to the caller but the pipeline state is left with the previous envelope still at peek level and current unchanged.

**Severity:** WARNING -- not triggered by current code, but a fragile pattern that would silently produce incorrect state if `RollbackHandler` is modified.

**Fix:** Add an explicit unreachable branch or assert:

```python
result = self._rollback_handler.restore_to_previous(...)
if isinstance(result, Failure):
    return result
# RollbackSuccess is the only non-Failure return from restore_to_previous
if consume:
    self._state.consume_last()
self._state.set_current(result.value)
return result
```

---

### WR-03: apply_join_strategy type-unsafe for FIRST_WINS path

**File:** `src/relay/parallel/join.py:141-162`

**Issue:** The `first_wins_coros` parameter defaults to `None` and raises `ValueError` when `None` is passed with FIRST_WINS:

```python
if strategy == JoinStrategy.FIRST_WINS:
    if first_wins_coros is None:
        raise ValueError("first_wins_coros must be provided for FIRST_WINS strategy")
```

This is a runtime crash that could be prevented at the type level. With `mypy --strict`, passing `None` for FIRST_WINS or a list for UNION/VOTE would not be caught.

**Severity:** WARNING -- not currently triggered, but creates an API surface that can't be statically type-checked.

**Fix:** Use `@overload` to encode the constraint in the type system:

```python
from typing import overload

@overload
async def apply_join_strategy(
    strategy: JoinStrategy,
    fork_results: list[ForkResult],
    first_wins_coros: list[tuple[int, ForkSpec, Coroutine[None, None, ForkResult]]],
) -> Result[JSONDict]: ...

@overload
async def apply_join_strategy(
    strategy: JoinStrategy,
    fork_results: list[ForkResult],
    first_wins_coros: None = None,
) -> Result[JSONDict]: ...
```

---

### WR-04: AutoGenAdapter accepts unvalidated agent object

**File:** `src/relay/runners/autogen.py:34-47`

**Issue:** The `AutoGenAdapter` stores `self.agent: object` without any structural validation at construction or call time. The only validation is via a Protocol cast inside `run()`:

```python
class _UserProxyWithChat(Protocol):
    def initiate_chat(self, agent: object, message: str, max_turns: int) -> object: ...
    chat_messages: object

def _make_user_proxy_with_chat(obj: object) -> _UserProxyWithChat:
    return cast(_UserProxyWithChat, obj)
```

If someone passes a non-AutoGen object as `agent`, the `run()` call will fail with a confusing `AttributeError` at line 70 or 73, masked by the `await asyncio.to_thread(...)` wrapper which obscures the traceback.

Other adapters have the same pattern (`LangChainAdapter.runnable: object`, `CrewAIAdapter.agent: object`), but those document the required interface. AutoGenAdapter relies on `__post_init__` not validating anything.

**Severity:** WARNING -- confusing failure mode for API misuse. Violates the fail-fast principle.

**Fix:** Add a structural check at construction time, at minimum verifying that the agent has `initiate_chat` and `chat_messages` attributes:

```python
def __post_init__(self) -> None:
    if not hasattr(self.agent, "initiate_chat") or not hasattr(self.agent, "chat_messages"):
        raise ValueError(
            "AutoGenAdapter.agent must satisfy the AssistantAgent protocol "
            "(require: initiate_chat, chat_messages)"
        )
```

---

## Info

### IN-01: _finalize_step calls save_snapshot(rollback) with current_envelope which is not a new checkpoint

**File:** `src/relay/core_pipeline.py:309`

**Description:** On rollback, `current_envelope` is saved as a snapshot. But this envelope was already persisted at the end of its original `_finalize_step` (same method, line 320 in the success path). The duplicate snapshot is wasteful but harmless (the correct state is restored from it on `load_snapshot`).

**Severity:** INFO -- addressed by WR-01 fix.

---

### IN-02: Duplicate token estimation logic across envelope.py and budget/token_counter.py

**File:** `src/relay/envelope.py:253-269`
**File:** `src/relay/budget/token_counter.py:33-37`

**Description:** `estimate_tokens` in `envelope.py` and `HeuristicCounter.count` in `token_counter.py` both implement the same `len(text) // 3` heuristic with identical edge-case handling (`max(1, ...)`). This duplicated logic could diverge if one is updated and the other is not.

**Severity:** INFO -- code duplication, no immediate bug.

**Fix:** Have `estimate_tokens` delegate to a `HeuristicCounter` instance:

```python
from relay.budget.token_counter import HeuristicCounter
_ESTIMATOR = HeuristicCounter()

def estimate_tokens(payload: JSONDict) -> int:
    json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _ESTIMATOR.count(json_str)
```

---

### IN-03: _load_index silently drops non-string keys from index

**File:** `src/relay/snapshot.py:262-265`

**Description:** When loading the index file, only string keys are preserved:

```python
for k, v in data.items():
    if isinstance(k, str):
        data_dict[k] = v
```

Non-string keys are silently discarded with no warning. If a manually-edited index contains numeric keys, they disappear without trace.

**Severity:** INFO -- the index is only written by Relay code which always uses string keys.

**Fix:** Add a log warning for dropped non-string keys:

```python
for k, v in data.items():
    if isinstance(k, str):
        data_dict[k] = v
    else:
        logger.warning("Non-string key '%s' dropped from index", k)
```

---

### IN-04: HardCapEnforcer.check validates projected_cost < 0 but the counter can never return negative

**File:** `src/relay/budget/enforcer.py:35-39`

**Description:** The check `if projected_cost < 0` is dead code. Both `HeuristicCounter.count` (`max(1, len(text) // 3)`) and `_TiktokenCounter.count` (`len(enc.encode(text))`) can never return a negative value. `len()` is always `>= 0` and `max(1, ...)` ensures at least 1.

**Severity:** INFO -- defensive code with no runtime impact.

**Fix:** Either remove the dead branch or keep it as defense-in-depth (documented as such).

---

### IN-05: Typo: "persist" misspelled as "persist" in snapshot.py comment

**File:** `src/relay/snapshot.py:2`

**Description:** Module docstring reads "persistence" instead of "persistence":

```
"""Snapshot persistence layer for Relay."""
```

**Severity:** INFO -- cosmetic.
