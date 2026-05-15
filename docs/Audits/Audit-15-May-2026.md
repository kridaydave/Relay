# Relay Post-Ship Audit — 15 May 2026
**Date:** 15 May 2026  
**Auditor:** Eric  
**Scope:** Full codebase — all 25 source modules, all 29 test modules  
**Checked against:** `docs/Relay Coding Rules.md`  
**Branch:** main @ c0d0d4a  
**Passes:** 1 (exhaustive read of all source + test files)  
**Status:** Fixed by Matt (J.Dev)

---

## Summary

Previous audit rounds (10 May 2026) fixed 17 bugs covering the rollback subsystem, path traversal, ghost index entries, and more. This pass finds what remained or was introduced during those fixes. 15 issues found. 1 is a real data-loss bug (incorrect failure code masks corrupted storage). 2 are dead code. 4 are rule violations with architectural impact. The rest are mediocre patterns that compound over time.

The most impactful cluster: `Failure.code` accepts `str` (Rule 3.3), tests compare against raw strings, and `get_latest_snapshot` already abuses this by silently replacing a real error code with a wrong one. These three reinforce each other and will get worse as the codebase grows.

---

## BUGS

---

### BUG-01 — `get_latest_snapshot` swallows real failure codes, returns wrong error
**File:** `snapshot.py:149–155`  
**Severity:** Medium

`_load_index` can return four distinct failures. `get_latest_snapshot` ignores all of them and emits a single `PIPELINE_NOT_FOUND` regardless:

```python
index_result = self._load_index(pipeline_id)
if isinstance(index_result, Failure):
    return Failure(
        reason=f"No snapshots found for pipeline: {pipeline_id}",
        code=ErrorCode.PIPELINE_NOT_FOUND,   # ← always, regardless of actual cause
    )
```

| `_load_index` failure code | Actual meaning | What caller receives |
|---|---|---|
| `INDEX_NOT_FOUND` | Pipeline never existed | `PIPELINE_NOT_FOUND` ✓ |
| `CORRUPTED_INDEX` | On-disk JSON is garbage | `PIPELINE_NOT_FOUND` ✗ |
| `INVALID_INDEX` | Schema mismatch | `PIPELINE_NOT_FOUND` ✗ |
| `INDEX_READ_FAILED` | OS-level read error | `PIPELINE_NOT_FOUND` ✗ |

A corrupted index — which may indicate data loss — is indistinguishable from "pipeline never ran." Callers that switch on `Failure.code` (Rule 3.3) silently take the wrong branch. Contradiction rollback reaching a corrupted index would return `PIPELINE_NOT_FOUND`, causing the caller to treat it as "no history" and proceed incorrectly.

Compare with `list_snapshots` (same file, lines 167–175) which correctly handles this:
```python
if index_result.code == ErrorCode.INDEX_NOT_FOUND:
    return Success([])
return Failure(reason=index_result.reason, code=index_result.code)
```

**Fix:**
```python
def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
    index_result = self._load_index(pipeline_id)
    if isinstance(index_result, Failure):
        if index_result.code == ErrorCode.INDEX_NOT_FOUND:
            return Failure(
                reason=f"No snapshots found for pipeline: {pipeline_id}",
                code=ErrorCode.PIPELINE_NOT_FOUND,
            )
        return index_result   # propagate CORRUPTED_INDEX, INVALID_INDEX, INDEX_READ_FAILED
    ...
```

---

## DEAD CODE

---

### DEAD-01 — `runners/protocol.py:9` — unused `import json`
**File:** `runners/protocol.py:9`  
**Severity:** Low

```python
import json
```

`json` is not referenced anywhere in `protocol.py`. The file only defines `ContextSlice`, `AgentOutput`, and `AgentRunner`. Dead import; fails mypy `--strict` unused-import pass.

**Fix:** Delete line 9.

---

### DEAD-02 — `core_pipeline.py:230–244` — `_apply_manifest_if_present` is a no-op wrapper
**File:** `core_pipeline.py:230–244`  
**Severity:** Low

```python
def _apply_manifest_if_present(
    self,
    envelope: ContextEnvelope,
    manifest: AgentManifest | None,
) -> Result[ContextEnvelope]:
    if manifest is None:
        return Success(envelope)
    return self._apply_manifest(envelope, manifest)
```

`_apply_manifest` (line 285) already opens with:
```python
if manifest is None:
    return Success(envelope)
```

The `_if_present` wrapper adds zero logic. It is also used inconsistently — `_handle_initial_step` calls `_apply_manifest` directly, `_handle_subsequent_step` calls `_apply_manifest_if_present`. Both paths do the same thing.

**Fix:** Delete `_apply_manifest_if_present`. Replace the single call-site in `_handle_subsequent_step` with a direct call to `_apply_manifest`.

---

## RULE VIOLATIONS

---

### RULE-01 — `types.py:60` — `Failure.code: ErrorCode | str` defeats the error code registry (Rule 3.3)
**File:** `types.py:60`  
**Severity:** High

```python
@dataclass(frozen=True)
class Failure:
    reason: str
    code: ErrorCode | str = ErrorCode.UNKNOWN_ERROR
```

Rule 3.3: *"Error codes are a public API — treat them as such. Once a code is shipped, changing it is a breaking change."* The `| str` escape hatch makes that guarantee hollow. Any caller can pass an arbitrary string. This cascades through the test suite — at least seven tests compare against raw strings rather than `ErrorCode` members (see TEST-01 below), which means typos in those strings would never be caught by the type system.

**Fix:** Change to `code: ErrorCode = ErrorCode.UNKNOWN_ERROR`. Any test or caller currently passing a string must be updated to use `ErrorCode.*`. The enum already covers every code in use.

---

### RULE-02 — `envelope.py:115–121` — `compute_signature` is an exact duplicate of `_compute_signature` (Rule 1.1)
**File:** `envelope.py:92–121`  
**Severity:** Medium

```python
def _compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature ... (field order is load-bearing) ..."""
    payload = json.dumps(...)
    message = f"..."
    return hmac.new(...).hexdigest()


def compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature ... (field order is load-bearing) ..."""  # identical docstring
    return _compute_signature(envelope, secret)   # one-line wrapper
```

Identical docstrings. Identical signatures. One is the other's one-line alias. This creates a 3-hop call chain: `_sign_envelope → compute_signature → _compute_signature`. The public function `compute_signature` is in `__all__` and used in `core_pipeline.py`. The private one is referenced only by `compute_signature` and `verify_signature`.

**Fix:** Delete `_compute_signature`. Move its implementation body into `compute_signature`. `verify_signature` and `_sign_envelope` already call `compute_signature` — no other changes needed.

---

### RULE-03 — `pipeline_state.py:34–35` — `snapshot_ids` bypasses lock guard (Rule 2.4 / R18)
**File:** `pipeline_state.py:34–35`  
**Severity:** Medium

```python
@property
def snapshot_ids(self) -> dict[int, str]:
    return self._snapshot_ids   # ← no _assert_lock_held(), no copy
```

Every other state accessor in `PipelineState` calls `_assert_lock_held()`:

| Method | Lock assert | Returns copy |
|---|---|---|
| `current()` | ✓ | — |
| `get_previous_envelopes()` | ✓ | ✓ |
| `set_current()` | ✓ | — |
| `archive_and_set()` | ✓ | — |
| `peek_last()` | ✓ | — |
| `consume_last()` | ✓ | — |
| `has_history()` | ✓ | — |
| **`snapshot_ids`** | **✗** | **✗ (exposes mutable dict)** |

`core_pipeline.py` writes to `snapshot_ids` inside `transaction()` blocks (lock is held), but the property itself does not enforce this. External callers — including tests at `test_pipeline.py:387–389` — read it without holding the lock.

**Fix:** Add `_assert_lock_held()` to the property body. Return a copy (`dict(self._snapshot_ids)`) so callers can't mutate internal state. Alternatively, replace the mutable property with a dedicated locked setter `register_snapshot(step: int, snapshot_id: str) -> None` on `PipelineState`, and remove direct dict access from `core_pipeline.py`.

---

### RULE-04 — `packers.py:33` — `SlicePacker` uses ABC instead of Protocol (Rule 1.3)
**File:** `slicer/packers.py:33`  
**Severity:** Low

```python
class SlicePacker(ABC):
    @abstractmethod
    def pack(self, payload, manifest) -> Result[dict[str, Any]]: ...
```

Rule 1.3: *"Protocols live in their own file, not next to implementations."* Every other interface in Relay uses `Protocol` (`TokenCounter`, `EmbeddingProvider`, `AgentRunner`). `SlicePacker` uses `ABC`, which forces nominal inheritance. A third-party packer must subclass `SlicePacker` rather than just satisfying the shape — unnecessary coupling.

**Fix:** Convert to `@runtime_checkable class SlicePacker(Protocol)`. Move it to `slicer/providers.py` alongside `EmbeddingProvider`, or to a new `slicer/protocol.py`. Existing `RecencySlicePacker`, `StructuralSlicePacker`, `RelevanceSlicePacker` satisfy the shape structurally — they no longer need to inherit.

---

## MEDIOCRE CODE

---

### MED-01 — `pipeline_snapshot.py` — `SnapshotManager` is a pure delegation facade with zero logic
**File:** `pipeline_snapshot.py`  
**Severity:** Low

```python
class SnapshotManager:
    def save(self, envelope: ContextEnvelope) -> Result[str]:
        return self._snapshot_store.save_snapshot(envelope)

    def load(self, snapshot_id: str) -> Result[ContextEnvelope]:
        return self._snapshot_store.load_snapshot(snapshot_id)
```

Both methods are one-line delegations that rename the call (`save` → `save_snapshot`, `load` → `load_snapshot`). `CoreRelayPipeline` already holds `self._snapshot_store` — it can call it directly. The wrapper adds one layer of indirection, two extra files to read when tracing a call, and no behavior. Consistent with the last audit's design concern entry on this class.

**Fix:** Delete `SnapshotManager`. In `core_pipeline.py`, call `self._snapshot_store.save_snapshot(envelope)` and `self._snapshot_store.load_snapshot(snapshot_id)` directly. Delete `_snapshot_manager` field and `pipeline_snapshot.py`.

---

### MED-02 — `core_pipeline.py:316–365` — `_rollback_with_reason`/`_rollback_and_consume` 85% duplicated
**File:** `core_pipeline.py:316–365`  
**Severity:** Low

Both methods: guard on `has_history()`, call `peek_last()`, call `_rollback_handler.restore_to_previous(...)`, call `set_current()`. The only difference: `_rollback_and_consume` additionally calls `consume_last()`.

```python
# _rollback_with_reason (lines 316–339)           # _rollback_and_consume (lines 341–365)
if not self._state.has_history(): ...              if not self._state.has_history(): ...
previous_envelope = self._state.peek_last()        previous_envelope = self._state.peek_last()
assert previous_envelope is not None               assert previous_envelope is not None
result = self._rollback_handler.restore_to_previous(...)   result = self._rollback_handler.restore_to_previous(...)
if isinstance(result, RollbackSuccess):            if isinstance(result, RollbackSuccess):
    self._state.set_current(result.value)              self._state.consume_last()         # ← only difference
return result                                          self._state.set_current(result.value)
                                                   return result
```

**Fix:** Extract a single private helper:
```python
def _do_rollback(self, reason: str, consume: bool) -> Result[ContextEnvelope]:
    if not self._state.has_history():
        return Failure(reason="No previous envelope to rollback to", code=ErrorCode.NO_ROLLBACK_AVAILABLE)
    previous_envelope = self._state.peek_last()
    assert previous_envelope is not None
    result = self._rollback_handler.restore_to_previous(
        previous_envelope, self._state.snapshot_ids, self._snapshot_store, reason
    )
    if isinstance(result, RollbackSuccess):
        if consume:
            self._state.consume_last()
        self._state.set_current(result.value)
    return result
```

---

### MED-03 — `validator.py:167–172` — `removed_count` mutated in-place for display; confusing variable lifetime
**File:** `validator.py:167–172`  
**Severity:** Low

```python
if new_count > 0:
    display_removed = removed_count          # save original before overwrite
    removed_count = max(removed_count, 1)    # mutate for division safety
    ratio = new_count / removed_count
    if ratio > self._hallucination_ratio_threshold:
        return f"... {new_count} new, {display_removed} removed ..."
```

`removed_count` is a loop variable that gets silently re-assigned mid-block to make division safe, requiring an alias just to remember the original. This is the source of the display bug noted in the previous audit (BUG-07 there). The previous audit's fix was accepted but the underlying pattern was left in.

**Fix:**
```python
if new_count > 0:
    effective_removed = max(removed_count, 1)
    ratio = new_count / effective_removed
    if ratio > self._hallucination_ratio_threshold:
        return f"... {new_count} new, {removed_count} removed (ratio: {ratio:.1f}x)"
```

---

### MED-04 — `core_pipeline.py:96–98` — `close()` docstring states wrong guard condition (Rule 8.2)
**File:** `core_pipeline.py:96–98`  
**Severity:** Low

```python
def close(self) -> None:
    """Cleans up token counter if it has a close method."""
    if self.token_counter is not None:
        self.token_counter.close()
```

The docstring says *"if it has a close method"* — but `TokenCounter` protocol always defines `close()`. The guard is `is not None` (optional field), not method existence. The docstring lies about what the check does.

**Fix:** `"""Release token counter resources if one was provided."""`

---

### MED-05 — `core_pipeline.py:90–91` — comment explains WHAT not WHY (comment guideline)
**File:** `core_pipeline.py:90–91`  
**Severity:** Low

```python
        self._rollback_handler = RollbackHandler()
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self._pipeline_id, self.token_counter)
        else:
            self._enforcer = None
        # registry is set directly from __init__ field, no additional setup needed
```

Comments must explain WHY (hidden constraint, workaround, non-obvious invariant). "No additional setup needed" explains WHAT — the absence of code already communicates that. Delete it.

---

## BUGS IN TESTS

---

### TEST-01 — Seven tests compare `result.code` against raw strings instead of `ErrorCode` members (Rule 3.3)
**Severity:** Medium

| File | Line | String used |
|---|---|---|
| `test_snapshot.py` | 110 | `"INVALID_SNAPSHOT"` |
| `test_snapshot.py` | 134 | `"INVALID_SNAPSHOT_ID"` |
| `test_snapshot.py` | 146 | `"PIPELINE_NOT_FOUND"` |
| `test_validator.py` | 63 | `"PIPELINE_MISMATCH"` |
| `test_validator.py` | 88 | `"INVALID_STEP"` |
| `test_pipeline_rollback.py` | 55 | `"NO_SNAPSHOT_REGISTERED"` |
| `test_pipeline_rollback.py` | 65 | `"DISK_ERROR"` ← not in `ErrorCode` at all |
| `test_runners/test_registry.py` | 22 | `"ADAPTER_NOT_FOUND"` |

The last entry (`"DISK_ERROR"`) is a mock failure code not present in the `ErrorCode` enum. If `Failure.code` is tightened to `ErrorCode` only (RULE-01), this test will break — which is exactly the point.

**Fix for all:** Replace string literals with `ErrorCode.*` enum members. For `"DISK_ERROR"`, use `ErrorCode.UNKNOWN_ERROR` or add a meaningful code to the enum.

---

### TEST-02 — `get_latest_snapshot` has no test for corrupted or unreadable index (Rule 7.5)
**Severity:** Medium

`get_latest_snapshot` has four distinct `Failure` paths through `_load_index`. Only one is tested: `INDEX_NOT_FOUND → PIPELINE_NOT_FOUND`. The three others (`CORRUPTED_INDEX`, `INVALID_INDEX`, `INDEX_READ_FAILED`) are untested. BUG-01 above was invisible in CI because of this gap.

After fixing BUG-01, add:

```python
def test_get_latest_snapshot_propagates_corrupted_index_failure(self):
    """Corrupted index must not be silently converted to PIPELINE_NOT_FOUND."""
    # write a non-JSON file as the index
    index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("not valid json {{{")

    result = self.store.get_latest_snapshot("pipeline-xyz")

    assert isinstance(result, Failure)
    assert result.code == ErrorCode.CORRUPTED_INDEX  # NOT PIPELINE_NOT_FOUND
```

---

## RULE VIOLATIONS SUMMARY TABLE

| Rule | Location | Issue |
|---|---|---|
| 3.3 (error code registry) | `types.py:60` | `Failure.code: ErrorCode \| str` — `str` escape hatch defeats the enum |
| 3.4 (propagate Failure) | `snapshot.py:149` | `get_latest_snapshot` swaps real failure codes for `PIPELINE_NOT_FOUND` |
| 1.1 (one owner) | `envelope.py:115` | `compute_signature` is a one-line alias of `_compute_signature` with identical docstring |
| 1.3 (Protocols in own file) | `slicer/packers.py:33` | `SlicePacker` is `ABC` not `Protocol`; lives next to implementations |
| R18 (concurrent state) | `pipeline_state.py:34` | `snapshot_ids` property skips `_assert_lock_held()` and exposes mutable dict |
| 8.2 (docstring accuracy) | `core_pipeline.py:96` | `close()` docstring says "if it has a close method" — guard is `is not None` |
| 3.3 (tests) | 7 test locations | `result.code == "STRING"` — should use `ErrorCode.*` |
| 7.5 (Failure path tests) | `test_snapshot.py` | No test for `get_latest_snapshot` when index is corrupted/unreadable |

---

## DEAD CODE SUMMARY

| Location | What | Fix |
|---|---|---|
| `runners/protocol.py:9` | `import json` — unused | Delete |
| `core_pipeline.py:230–244` | `_apply_manifest_if_present` — redundant wrapper around `_apply_manifest` | Delete; call `_apply_manifest` directly |
| `pipeline_snapshot.py` | `SnapshotManager` — pure 1-line delegation, zero logic | Delete; call `_snapshot_store` directly |

---

## DESIGN CONCERNS

**`SnapshotManager` indirection (repeat from 10 May audit)**  
The 10 May audit listed this under design concerns. Still present. `CoreRelayPipeline` holds `_snapshot_store` and `_snapshot_manager` that wraps it. One of them should be removed. The manager adds no caching, retry logic, or transformation — it renames two methods.

**`Failure.code: ErrorCode | str` enables covert protocol drift**  
With `str` accepted, any caller can invent a new failure code on-the-fly (`Failure(reason="x", code="MY_CUSTOM_CODE")`). Once callers switch on that string, it becomes a de facto public API with no registry entry, no doc, and no migration path. Rule 3.3 exists specifically to prevent this. Every string comparison in the test suite is a future `ErrorCode` entry waiting to be formalized.

---

## SCOPE CHECK — CLEAN

No features outside v0.1–v0.3 scope found. v0.4+ (async fork-join), v0.5 (OTEL/audit log/CLI), v0.6 (Redis/Postgres/S3) remain correctly absent.

---

## PRIORITY ORDER

| Priority | Item | Reason |
|---|---|---|
| 1 | BUG-01 `get_latest_snapshot` wrong error code | Corrupted storage reported as "pipeline not found" — data loss masked |
| 2 | RULE-01 `Failure.code: ErrorCode \| str` | Root cause of BUG-01 and TEST-01; gets worse as codebase grows |
| 3 | TEST-01 string comparisons → `ErrorCode.*` | Follows naturally from RULE-01 fix; 8 locations |
| 4 | TEST-02 missing corrupted-index test | Validates BUG-01 fix; prevents regression |
| 5 | RULE-03 `snapshot_ids` skips lock guard | Thread-safety invariant inconsistency; low probability but undetectable |
| 6 | DEAD-02 `_apply_manifest_if_present` | Dead code removal; simplifies `_handle_subsequent_step` |
| 7 | MED-01 `SnapshotManager` | Dead facade removal; reduces indirection |
| 8 | MED-02 rollback duplication | Code clarity; one helper replaces two near-identical methods |
| 9 | RULE-02 `compute_signature` duplicate | Clean up the 3-hop call chain |
| 10 | DEAD-01 `import json` in `protocol.py` | Trivial; delete one line |
| 11 | RULE-04 `SlicePacker` ABC → Protocol | Consistency with every other interface in the project |
| 12 | MED-03 `removed_count` mutation | Clarity; prevents re-introduction of BUG-07 from prior audit |
| 13 | MED-04 `close()` docstring | Accuracy; Rule 8.2 |
| 14 | MED-05 `# registry is set...` comment | Delete; explains WHAT |
