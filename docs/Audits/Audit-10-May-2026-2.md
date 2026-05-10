# Code Audit — 10 May 2026

**Scope:** Full codebase review against Relay Engineering Standards  
**Reviewer:** Claude Code (automated/sonnet-4-6-1M)  
**Branch:** main @ d7ca3ca
**Passes:** 1 
---

## SECURITY

### `snapshot.py:106-120` — CRITICAL: Path traversal in `load_snapshot`

`pipeline_id` extracted from caller-controlled `snapshot_id` string, used directly in `Path` construction with no validation.

```python
pipeline_id, rest = snapshot_id.split("@", 1)
snapshot_path = self._storage_path / pipeline_id / f"{snapshot_id}.json"
```

Input `"../../../etc@1_abc"` → path escapes storage root. Fix: validate extracted `pipeline_id` against `PIPELINE_ID_PATTERN` before any `Path` use.  
**Rules violated:** 4.3, 9.3

---

### `core_pipeline.py:13,299` — HIGH: Private function imported and used across module boundary

```python
from relay.envelope import _compute_signature  # private — crosses module boundary
```

`compute_signature` (public) already delegates to `_compute_signature`. Use the public one.  
**Rules violated:** 1.2, encapsulation

---

## TYPE SAFETY

### `core_pipeline.py:224` — CRITICAL: Dead None-check on non-optional field

```python
if manifest.max_tokens is not None:  # manifest.max_tokens: int — never None
```

`AgentManifest.max_tokens` is typed `int`, not `int | None`. mypy --strict flags this. Either the field should be `int | None` (if optional budget is valid) or the check must be removed.  
**Rules violated:** 2.1, 2.3

---

### `core_pipeline.py:463` — HIGH: `except BaseException` catches `KeyboardInterrupt` / `SystemExit`

```python
except BaseException as e:
    return Failure(...)
```

`KeyboardInterrupt` and `SystemExit` are silently swallowed and returned as `Failure`. Fix: `except Exception as e`.  
**Rule violated:** 3.2

---

## ERROR HANDLING

### `core_pipeline.py:390-394` — HIGH: Silent Failure discard in `_slice_payload`

```python
def _slice_payload(self, manifest, current_envelope) -> str:
    pack_result = self.slice_packer.pack(current_envelope.payload, manifest)
    if isinstance(pack_result, Failure):
        return ""   # Failure swallowed, budget check proceeds with empty string
```

`_slice_payload` should return `Result[str]`; `_check_budget` should propagate the Failure. `StructuralSlicePacker.pack` can return `MISSING_SECTIONS` — this is a real error, not "empty is fine."  
**Rule violated:** 3.4

---

### `context_broker.py:71,86` — MEDIUM: `manifest_hash=""` default still present

```python
def create_initial_envelope(self, ..., manifest_hash: str = "") -> Result[ContextEnvelope]:
def create_next_envelope(self, ..., manifest_hash: str = "") -> Result[ContextEnvelope]:
```

Rule 10 table explicitly flags this: "Remove the default now — it was a migration scaffold." Keeping the default hides whether callers are actually setting a hash.  
**Rule violated:** Section 10

---

## MODULE DESIGN

### `context_broker.py:47-65` — LOW: Inaccurate docstring

```python
# "Direct construction bypasses validation - use the factory for boundary entry."
# But __post_init__ raises ValueError if secret is weak — validation IS present.
```

Comment contradicts code. Fix: remove the misleading note or rewrite to say `__post_init__` catches programmer errors while factory returns `Result`.  
**Rule violated:** 8.2

---

## RESOURCE LIFECYCLE

### `pipeline_state.py:43-46` — MEDIUM: `_assert_lock_held` false-negative under concurrency

```python
if not self._lock.locked():  # True if ANY thread holds the lock, not necessarily this one
    raise AssertionError(...)
```

Thread A holds lock. Thread B calls a mutation method. `self._lock.locked()` returns `True` — no assertion raised. Guard is ineffective in multithreaded scenarios. Python's `threading.Lock` has no `locked_by_me()` — use `threading.RLock` or track ownership explicitly if this guard matters.

---

### `pipeline_state.py:62-64` — LOW: Dead code in `transaction()`

```python
try:
    yield self._current_envelope
finally:
    pass  # no-op — remove it
```

---

## APPROXIMATIONS / HEURISTICS

### `validator.py:84-96` — MEDIUM: `_detect_hallucination` threshold undocumented and untested

`hallucination_ratio_threshold=2.0` has no empirical basis documented anywhere. Rule 6.1 requires the word "approximates"/"estimates" in the docstring. Rule 6.3 requires ground-truth benchmark test: one payload where a human would agree hallucination occurred, one where it did not. Currently untested against real cases.  
**Rules violated:** 6.1, 6.3

---

## TESTING

### Concurrent tests assert no exception only — HIGH

Rule 7.3: concurrent tests must assert **final state consistency**. Current tests confirm no crash, not correctness. Missing: after N concurrent `execute_step` calls, assert `final.step` is one of the submitted steps, not a blend.

```python
# Required pattern:
def test_concurrent_steps_final_envelope_is_consistent():
    pipeline = ...
    results = run_n_threads(pipeline.execute_step, payloads=[...] * 5)
    final = pipeline.get_current_envelope()
    valid_steps = {1, 2, 3, 4, 5}
    assert final.step in valid_steps
    assert final.payload in [p for p in payloads]
```

**Rule violated:** 7.3

---

### Test names are identifiers not sentences — MEDIUM

```python
def test_pipeline_creates_envelope_on_first_step():  # passable
def test_enforcer_1():                               # rule violation — means nothing
```

Rule 7.1: names must be sentences describing scenario and expected outcome.  
**Rule violated:** 7.1

---

### Missing Failure-path tests — MEDIUM

Per rules 7.2 and 7.5, the following are untested or only happy-path tested:

- `_slice_payload` Failure path (`StructuralSlicePacker` returns `MISSING_SECTIONS`)
- `unwrap_or`, `map_result`, `map_error` — only happy-path tested
- `pipeline_state.py` concurrent mutation assertions
- Each distinct `Failure` code from `validate_manifest_boundaries`

---

## ARCHITECTURE DEBT (Rule 10 Table)

| Item | Status |
|------|--------|
| `RelayPipeline` empty subclass | Not found — resolved |
| `manifest_hash=""` default | Still present in `context_broker.py:71,86` |
| Error code registry as Enum | Done (`ErrorCode` enum exists) |
| `_estimate_tokens` benchmark | Docstring claims benchmark exists (`test_envelope.py::TestTokenEstimation`) — verify comprehensiveness |
| `ContextBroker.__post_init__` docstring | Claims direct construction bypasses validation — incorrect, `__post_init__` validates |

---

## Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 2 | Path traversal in `load_snapshot`, dead None-check on `int` field |
| HIGH | 4 | `except BaseException`, `_slice_payload` swallows Failure, private func import, concurrent test gaps |
| MEDIUM | 5 | `manifest_hash` default, lock assertion false-negative, hallucination heuristic undocumented/untested, test name violations, missing Failure-path tests |
| LOW | 2 | Inaccurate docstring in `context_broker`, dead `try/finally: pass` |
