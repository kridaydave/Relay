# Relay Codebase Audit Report
**Date:** 10 May 2026
**Reviewer:** Claude Code (claude-opus-4-7)
**Version:** Relay v0.3.0
**Status:** Fixed  ✅
Full review of all 26 production source files against the [Relay Engineering Standards](../Relay%20Coding%20Rules.md). Covers bugs, rule violations, dead code, and unnecessary complexity.

---

## Bugs

### 1. `RecencySlicePacker` selects oldest sections, not most recent
**File:** `src/relay/slicer/packers.py:68`

`sorted_keys` is built with an ascending sort (section_1, section_2, …), then the loop fills until `max_tokens` is consumed. Ascending order puts the **oldest** sections first. The class docstring says "Selects most recent sections." These are opposites. Under budget pressure, the packer silently drops the newest context.

**Fix:** Sort descending, or reverse-iterate, so the most recent sections are packed first.

---

### 2. Hallucination detector uses ratio threshold as a count threshold
**File:** `src/relay/validator.py:167`

```python
if removed_count > 0 and new_count == 0:
    if removed_count > self._hallucination_ratio_threshold:
```

`_hallucination_ratio_threshold` is documented as a ratio (default `2.0`). This branch compares it to an entity **count**. "More than 2.0 entities removed" is not the same semantic as "removal-to-addition ratio exceeds 2.0." These are different checks. The threshold value leaks across two incompatible uses.

**Fix:** Add a separate `deletion_count_threshold` parameter, or document the dual-use explicitly with a test that validates both branches.

---

### 3. `validate_manifest_boundaries` has a dead parameter
**File:** `src/relay/validator.py:248`

```python
def validate_manifest_boundaries(
    envelope: ContextEnvelope,   # never read
    manifest: "AgentManifest",
    written_sections: set[str],
) -> Result[None]:
```

`envelope` is declared but the function body never touches it. Every call site passes it unnecessarily. Either use it or remove it.

---

### 4. `RELAY_VERSION` is stale
**File:** `src/relay/envelope.py:21`

```python
RELAY_VERSION = "0.2.3"
```

The project is at v0.3.0 (per CHANGELOG and the dist artifacts). Every envelope produced in v0.3 is stamped `0.2.3`. This will break any downstream version check.

---

### 5. Dead import in `runners/protocol.py`
**File:** `src/relay/runners/protocol.py:13`

```python
from relay.envelope import _estimate_tokens
```

`_estimate_tokens` is imported but never referenced in `protocol.py`. It is used in `core_pipeline.py` (line 427) which imports it directly. This import is dead.

---

## Rule Violations

### R2.2 — `Result` TypeAlias uses unbound TypeVar
**File:** `src/relay/types.py:72`

```python
Result: TypeAlias = Success[ResultT] | RollbackSuccess[ResultT] | Failure
```

`ResultT` is a free TypeVar, not bound to this alias. mypy accepts this silently but the generic relationship is a lie — callers cannot parameterise `Result[int]` and get correct inference. The rule document provides the exact fix:

```python
# Python 3.12+
type Result[T] = Success[T] | RollbackSuccess[T] | Failure
```

---

### R3.2 — Bare `except Exception` in three places
**File:** `src/relay/snapshot.py:88, 144, 205`

All three catch `Exception` and wrap it in a `Failure`. The rule requires catching specific exceptions so programmer errors (e.g., `TypeError`, `AttributeError`) are not silently converted to domain failures.

| Location | Should catch |
|---|---|
| `save_snapshot` (line 88) | `OSError`, `json.JSONDecodeError` |
| `load_snapshot` (line 144) | `json.JSONDecodeError`, `OSError` |
| `_add_to_index` (line 205) | `OSError`, `json.JSONDecodeError`, `InvalidSnapshotIdError` |

---

### R1.1 — `json.dumps` directly in `core_pipeline.py`
**File:** `src/relay/core_pipeline.py:331`

```python
return json.dumps(pack_result.value)
```

Rule 1.1 says `core_pipeline.py` must read like an orchestrator — "no direct `json.dumps`." Push this serialisation into a helper or into `pipeline_snapshot.py`.

---

### R4.2 — `manifest_hash` bypasses `_require_str` in `_dict_to_envelope`
**File:** `src/relay/snapshot.py:330`

```python
raw_hash = data.get("manifest_hash", "")
manifest_hash = raw_hash if isinstance(raw_hash, str) else ""
```

Every other field in `_dict_to_envelope` uses `_require_str` / `_require_int` / `_require_dict`. This field silently defaults to `""` on missing or corrupt data instead of returning `Failure`. Rule 4.2 says all field extractions must use the helper consistently. The "migration scaffold" justification was flagged for removal in v0.3 per Section 10 of the coding rules.

---

### R8.3 — `budget/enforcer.py` missing `Owns` / `Does NOT` docstring
**File:** `src/relay/budget/enforcer.py:1`

```python
"""Budget enforcement for token cap validation."""
```

Missing the mandatory two-section format. Every module must have all three lines. Required format:

```python
"""Budget enforcement for token cap validation.

Owns: hard-cap check before agent calls, negative-count validation.
Does NOT: count tokens, manage budgets, or execute agents.
"""
```

---

### R8.2 — `CoreRelayPipeline` class docstring is stale
**File:** `src/relay/core_pipeline.py:53`

```python
"""Does NOT: define agent behavior, manage prompts."""
```

The class also owns budget enforcement and slicer dispatch. The rule document explicitly called this out as a known violation. Still not fixed.

---

### R2.4 — Manual copy constructors instead of `dataclasses.replace()`
**File:** `src/relay/envelope.py:73, 86`

`with_manifest_hash` and `with_signature` manually restate every field. If a field is added to `ContextEnvelope`, these methods silently produce incomplete copies — the compiler will not catch it. Rule 2.4 says use `dataclasses.replace()`:

```python
def with_manifest_hash(self, manifest_hash: str) -> "ContextEnvelope":
    return dataclasses.replace(self, manifest_hash=manifest_hash)

def with_signature(self, signature: str) -> "ContextEnvelope":
    return dataclasses.replace(self, signature=signature)
```

---

## Dead Code

### `_MIN_SECRET_LENGTH` defined and unused in `envelope.py`
**File:** `src/relay/envelope.py:31`

```python
_MIN_SECRET_LENGTH = 32
```

Only used in `context_broker.py` (line 36), which defines its own copy. The constant in `envelope.py` is never referenced. One of the two must go; it should live in `context_broker.py` where validation happens.

---

### `SliceStrategy` enum is orphaned
**File:** `src/relay/slicer/strategy.py` (entire file)

`SliceStrategy` defines `RECENCY`, `RELEVANCE`, and `STRUCTURAL` variants but **no production code uses it to select a packer**. There is no factory function `make_packer(strategy: SliceStrategy) -> SlicePacker`. The enum is exported from `slicer/__init__.py` but is never consumed. Either wire it into a factory or delete it.

---

### `_apply_manifest(validate=False)` path is unreachable
**File:** `src/relay/core_pipeline.py:236`

The `validate: bool = False` parameter on `_apply_manifest` exists but every call site passes `validate=True` when `manifest` is not `None`. The `False` branch (apply hash without validating) is dead at runtime. Remove the parameter and inline the validation.

---

### Backward-compat properties in `core_pipeline.py`
**File:** `src/relay/core_pipeline.py:438-446`

```python
# Backward-compatible accessors for tests
@property
def _current_envelope(self) -> ContextEnvelope | None: ...

@property
def _snapshot_ids(self) -> dict[int, str]: ...
```

Rule says no backwards-compatibility hacks. `_snapshot_ids` returns the live mutable dict reference — callers can mutate pipeline state through it. Tests must be updated to use the public API; these properties must be deleted.

---

## Concurrency

### TOCTOU: budget check and execution not under the same lock
**File:** `src/relay/core_pipeline.py:385-401`

In `execute_step_with_runner`:
1. Acquire lock → run budget check → **release lock**
2. Call `adapter.run()` (correct — can't hold lock during I/O)
3. Call `execute_step_with_manifest()` → **re-acquire lock**

Between steps 1 and 3, another thread can advance the envelope, making the budget check stale. The budget may be exceeded by the time execution commits. Not catastrophic (the budget re-check inside the slicer would likely catch it) but the check at step 1 provides a false guarantee.

---

## Unnecessary Complexity

### Boolean flags controlling method behavior
**Files:** `src/relay/core_pipeline.py:272, 242`

`_rollback_with_reason(consume_history: bool)` and `_apply_manifest(validate: bool)` use boolean parameters to switch between two distinct behaviors. This is the boolean-parameter-as-control-flow anti-pattern.

- `consume_history=True` is only called from `rollback()`. Split into a dedicated `_rollback_and_consume(reason)` method.
- `validate=False` is dead code (see above). Remove it entirely.

---

### `SnapshotManager` is a zero-value passthrough
**File:** `src/relay/pipeline_snapshot.py`

```python
def save(self, envelope): return self._snapshot_store.save_snapshot(envelope)
def load(self, snapshot_id): return self._snapshot_store.load_snapshot(snapshot_id)
```

Both methods are one-liners with no transformation, no error wrapping, no caching. This layer adds indirection with no value. `core_pipeline.py` can call `SnapshotStore` directly. If `SnapshotManager` ever does add logic, introduce it then.

---

## Test Gaps

| Missing test | Rule |
|---|---|
| `RollbackSuccess` path in `map_result` (types.py:106) | R7.5 |
| `unwrap` called on `RollbackSuccess` raises `ValueError` | R7.5 |
| `isinstance(FixedCounter(5), TokenCounter)` protocol sanity check | R7.6 |
| Hallucination detector: positive case (fires) + negative case (silent) | R6.3 |
| `RecencySlicePacker` selects highest-numbered sections under budget pressure | R7.2 |
| `test_pipeline.py:32` — `timestamp: datetime = None` annotation wrong | R2.3 |

---

## Quick Fixes (< 10 min each)

1. `envelope.py:21` — bump `RELAY_VERSION` to `"0.3.0"`
2. `envelope.py:31` — delete `_MIN_SECRET_LENGTH` (unused)
3. `envelope.py:73, 86` — replace manual copy constructors with `dataclasses.replace()`
4. `protocol.py:13` — delete dead `_estimate_tokens` import
5. `validator.py:248` — remove unused `envelope` parameter
6. `test_envelope.py:146` — delete duplicate assertion
7. `enforcer.py:1` — add `Owns:` / `Does NOT:` docstring lines
8. `core_pipeline.py:57` — update class docstring to include budget/slicer ownership
