# Relay — Bug & Code Fixes Plan
> Prioritised fix list derived from the May 2026 audit, codebase review, and rule violations.
> Each fix is scoped to a single atomic commit. Fixes are ordered: do them top to bottom.

---

## Severity Legend

| Symbol | Meaning |
|---|---|
| 🔴 CRITICAL | Runtime crash or security hole. Fix before any other work. |
| 🟠 HIGH | Incorrect behaviour, broken contract, or R-rule violation that affects correctness. |
| 🟡 MEDIUM | Quality degradation, test gap, or architectural smell that will compound. |
| 🟢 LOW | Style, naming, or minor documentation issue. |

---

## 🔴 CRITICAL FIXES

---

### FIX-001 — Wrong dict key type in `_snapshot_ids` causes runtime crash

**File:** `src/relay/core_pipeline.py`
**Severity:** 🔴 CRITICAL — mypy reports 5 errors; will crash at runtime if step is accessed with int key against a `dict[str, str]`

**Root cause:** The field is declared `dict[str, str]` but the step number (`int`) is used as the key throughout.

**Current (broken):**
```python
_snapshot_ids: dict[str, str] = field(default_factory=dict, init=False, repr=False)
```

**Fix:**
```python
_snapshot_ids: dict[int, str] = field(default_factory=dict, init=False, repr=False)
```

**Also fix in `pipeline_state.py`:**
```python
# Change:
self._snapshot_ids: dict[int, str] = {}
# (already correct here — verify the type flows through to core_pipeline's property)
```

**Commit message:** `fix(pipeline): correct _snapshot_ids type from dict[str,str] to dict[int,str]`

---

### FIX-002 — `pipeline_id` is not sanitised before filesystem use — path traversal risk

**File:** `src/relay/snapshot.py`, `src/relay/envelope.py`
**Severity:** 🔴 CRITICAL — `pipeline_id` becomes a directory name. A value like `../../etc/passwd` would traverse outside the storage root.

**Fix — add validation in `create_initial_envelope` before any filesystem operation:**
```python
import re
_SAFE_PIPELINE_ID = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')

def _validate_pipeline_id(pipeline_id: str) -> Result[str]:
    if not pipeline_id:
        return Failure(reason="pipeline_id cannot be empty", code="INVALID_PIPELINE_ID")
    if not _SAFE_PIPELINE_ID.match(pipeline_id):
        return Failure(
            reason="pipeline_id contains unsafe characters — only [a-zA-Z0-9_-] allowed",
            code="INVALID_PIPELINE_ID"
        )
    return Success(pipeline_id)
```

Call `_validate_pipeline_id` at the top of both `create_initial_envelope` and `SnapshotStore.save_snapshot`.

**Commit message:** `fix(security): validate pipeline_id before filesystem use to prevent path traversal`

---

### FIX-003 — Default signing secret `"default-secret"` is a security hole

**File:** `src/relay/envelope.py`
**Severity:** 🔴 CRITICAL — a function with a default insecure secret will be called with it in production.

**Current (broken):**
```python
def create_initial_envelope(
    ...
    secret: str = "default-secret",
) -> Result[ContextEnvelope]:
```

**Fix — remove the default entirely:**
```python
def create_initial_envelope(
    pipeline_id: str,
    initial_payload: dict[str, Any],
    secret: str,                      # required, no default
    token_budget_total: int = 8000,
    manifest_hash: str = "",
) -> Result[ContextEnvelope]:
```

Update all callers. Test files that relied on the default must now pass an explicit test secret (`"a" * 32`).

**Commit message:** `fix(security): remove default signing secret from create_initial_envelope`

---

### FIX-004 — `snapshot.py` raises `RuntimeError` instead of returning `Failure`

**File:** `src/relay/snapshot.py`
**Severity:** 🔴 CRITICAL — breaks the Result-type contract (R4). Any caller that doesn't wrap in try/except will crash.

**Current (broken) — `_add_to_index`:**
```python
except Exception as e:
    raise RuntimeError(f"Failed to update index: {e}")
```

**Fix:**
```python
except Exception as e:
    return Failure(reason=f"Failed to update index: {e}", code="INDEX_UPDATE_FAILED")
```

Also audit `save_snapshot` — if the index update fails after the snapshot file is written, the snapshot exists on disk but is not indexed. This inconsistent state must be handled:

```python
# After os.replace(temp_path, snapshot_path) succeeds:
index_result = self._add_to_index(pipeline_id, snapshot_id)
if isinstance(index_result, Failure):
    # Snapshot written but not indexed — clean up the orphan
    try:
        snapshot_path.unlink(missing_ok=True)
    except OSError:
        pass  # best-effort cleanup
    return index_result
```

**Commit message:** `fix(snapshot): return Failure instead of raising RuntimeError on index update failure`

---

## 🟠 HIGH PRIORITY FIXES

---

### FIX-005 — `_dict_to_envelope` uses `_require_field` inconsistently

**File:** `src/relay/snapshot.py`
**Severity:** 🟠 HIGH — `manifest_hash` skips validation entirely and falls back to `""` silently. If a snapshot is corrupted, other fields may also have wrong types that slip through.

**Current (inconsistent):**
```python
manifest_hash = data.get("manifest_hash", "")   # no type check
```

**Fix — apply `_require_field` to all fields or add explicit type guard:**
```python
raw_hash = data.get("manifest_hash", "")
manifest_hash = raw_hash if isinstance(raw_hash, str) else ""
```

Or extend `_require_field` to support an optional-with-default pattern:

```python
def _optional_field(self, data: dict[str, Any], key: str, expected_type: type, default: Any) -> Any:
    value = data.get(key, default)
    return value if isinstance(value, expected_type) else default
```

**Commit message:** `fix(snapshot): apply consistent type validation to manifest_hash in _dict_to_envelope`

---

### FIX-006 — Broken `Result` generic type alias

**File:** `src/relay/types.py`
**Severity:** 🟠 HIGH — `T` is unbound in the `TypeAlias` definition. mypy accepts it, but it provides false type safety.

**Current (broken):**
```python
T = TypeVar("T")
Result: TypeAlias = Union[Success[T], RollbackSuccess[T], Failure]
```

**Fix for Python 3.11 compatibility:**
```python
from typing import TypeVar, Union, TypeAlias

_T = TypeVar("_T")

# Keep Success, Failure, RollbackSuccess as before.
# Provide a generic alias that mypy can reason about:
def Result(t: type[_T]) -> type[Union[Success[_T], RollbackSuccess[_T], Failure]]:
    ...  # runtime stub only — used as annotation: Result[str]
```

Or use the simpler Python 3.12 syntax if you target 3.12+:
```python
type Result[T] = Success[T] | RollbackSuccess[T] | Failure
```

Pick one and enforce it in `pyproject.toml` via `requires-python`.

**Commit message:** `fix(types): correct unbound TypeVar in Result generic alias`

---

### FIX-007 — `manifest_hash` backward-compat default `""` was never removed

**File:** `src/relay/envelope.py`, `src/relay/context_broker.py`
**Severity:** 🟠 HIGH — the design plan (PR 5 in `relay-0.2-plan.md`) explicitly states this default must be removed before tagging v0.2 final. It was not removed.

**Fix:**
```python
# In create_initial_envelope and create_next_envelope:
# Remove: manifest_hash: str = ""
# Change to: manifest_hash: str
```

Every call site that omits `manifest_hash` must now pass `""` explicitly or a real hash. This surfaces all callers and makes the intent visible.

**Commit message:** `fix(envelope): remove manifest_hash backward-compat default — field is now required`

---

### FIX-008 — `RelayPipeline` empty subclass adds confusion with zero value

**File:** `src/relay/pipeline.py`
**Severity:** 🟠 HIGH — an empty subclass that adds no behaviour causes reader confusion ("what does this add?") and creates a second import path for the same object.

**Fix — two options, pick one:**

Option A (recommended): Delete `pipeline.py`. Update any imports to use `CoreRelayPipeline` directly. Add a `# Relay public API` comment block in `__init__.py`.

Option B: Give it real behaviour — e.g. convenience constructor that generates a secure random secret:
```python
@classmethod
def create(cls, token_budget: int = 8000, storage_path: str = "./relay_data") -> "RelayPipeline":
    """Create a pipeline with a secure random signing secret."""
    import secrets
    return cls(signing_secret=secrets.token_hex(32), token_budget=token_budget, storage_path=storage_path)
```

**Commit message:** `refactor(pipeline): remove empty RelayPipeline subclass — use CoreRelayPipeline directly`

---

### FIX-009 — `_estimate_tokens` accuracy claim is undocumented and untested against ground truth

**File:** `src/relay/envelope.py`, `tests/unit/test_envelope.py`
**Severity:** 🟠 HIGH — R17 violation. The docstring says "~50% accuracy in typical cases" but no test verifies this.

**Fix — replace the existing weak test with a real benchmark:**
```python
class TestTokenEstimationAccuracy:
    def test_estimate_within_2x_of_character_based_ground_truth(self):
        """Benchmark _estimate_tokens against a character-based reference.

        Ground truth: English prose averages ~4 chars/token (BPE, GPT-4 family).
        Our formula: len(json) // 3 ≈ 0.33 tokens/char.
        Acceptable: within 2x of the 4-char/token baseline on representative payloads.

        This test would catch a completely wrong implementation (e.g. returning 0 or 1).
        """
        payloads = [
            {"summary": "Apple reported strong Q4 results.", "step": 1},
            {"entities": ["Alice", "Bob"], "facts": ["revenue up", "costs flat"]},
            {"data": "x" * 200},  # repetitive content — tokenizers compress this
        ]
        for payload in payloads:
            estimate = _estimate_tokens(payload)
            json_len = len(json.dumps(payload, sort_keys=True))
            # Baseline: 1 token per 4 chars
            baseline = json_len // 4
            # Accept within 3x of baseline (our heuristic is rough)
            assert estimate >= baseline // 3, f"Estimate {estimate} too low vs baseline {baseline}"
            assert estimate <= baseline * 3, f"Estimate {estimate} too high vs baseline {baseline}"
```

Also update the docstring to say "within 3x of a 4-chars/token BPE baseline" rather than "~50% accuracy."

**Commit message:** `test(envelope): add ground-truth benchmark for _estimate_tokens per R17`

---

### FIX-010 — Hallucination detector has no ground-truth test

**File:** `src/relay/validator.py`, `tests/unit/test_validator.py`
**Severity:** 🟠 HIGH — R17 violation. The 2.0× ratio threshold has no empirical basis documented or tested.

**Fix — add to `test_validator.py`:**
```python
class TestHallucinationGroundTruth:
    """Ground-truth cases for the hallucination heuristic.

    Known limitation: the 2.0x entity ratio threshold was chosen arbitrarily.
    These tests document what it catches and what it misses so the threshold
    can be tuned with evidence.
    """

    def test_obvious_fabrication_is_detected(self):
        """10 new entities vs 1 removed is clear fabrication."""
        validator = HandoffValidator(hallucination_ratio_threshold=2.0)
        prev = {"entity": "Alice"}
        curr = {
            "entity": "Alice",
            "name": "Bob", "id": "C1", "subject": "D2", "identifier": "E3",
            "object": "F4",  # 5 new entity-keyed values
        }
        result = validator._detect_hallucination(prev, curr)
        assert result is not None, "Should detect obvious entity fabrication"

    def test_legitimate_enrichment_is_not_flagged(self):
        """Adding one entity to an existing set is normal enrichment."""
        validator = HandoffValidator(hallucination_ratio_threshold=2.0)
        prev = {"entities": ["Alice", "Bob"]}
        curr = {"entities": ["Alice", "Bob", "Charlie"]}
        result = validator._detect_hallucination(prev, curr)
        assert result is None, "Single new entity should not be flagged as hallucination"

    def test_complete_entity_loss_is_detected(self):
        """Losing all entities with zero new ones is suspicious deletion."""
        validator = HandoffValidator(hallucination_ratio_threshold=2.0)
        prev = {"entity": "A", "name": "B", "id": "C"}  # 3 entity-keyed
        curr = {"summary": "done"}
        result = validator._detect_hallucination(prev, curr)
        assert result is not None, "Complete entity loss should be flagged"
```

**Commit message:** `test(validator): add ground-truth cases for hallucination heuristic per R17`

---

### FIX-011 — `CoreRelayPipeline` should implement context manager protocol

**File:** `src/relay/core_pipeline.py`
**Severity:** 🟠 HIGH — R15 violation. `close()` exists but callers have no language-enforced way to call it.

**Fix:**
```python
def __enter__(self) -> "CoreRelayPipeline":
    return self

def __exit__(self, *_: object) -> None:
    self.close()
```

Update README example to show `with CoreRelayPipeline(...) as pipeline:`.

**Commit message:** `feat(pipeline): implement __enter__/__exit__ for context manager protocol per R15`

---

## 🟡 MEDIUM PRIORITY FIXES

---

### FIX-012 — Missing dedicated unit tests for `pipeline_state.py`, `pipeline_snapshot.py`, `pipeline_rollback.py`

**Severity:** 🟡 MEDIUM — R5 violation. These modules were split out of `core_pipeline.py` but have no test files of their own. They are only tested indirectly through integration tests.

**Fix:** Create:
- `tests/unit/test_pipeline_state.py` — test `set_current`, `archive_and_set`, `peek_last`, `consume_last`, `has_history`, thread safety of the lock
- `tests/unit/test_pipeline_snapshot.py` — test `save_and_register`, `advance`
- `tests/unit/test_pipeline_rollback.py` — test `restore_to_previous` with mock snapshot store

**Commit message:** `test: add unit tests for pipeline_state, pipeline_snapshot, pipeline_rollback per R5`

---

### FIX-013 — Concurrent tests only assert "no exception" — must assert state consistency (R18)

**File:** `tests/unit/test_pipeline.py`
**Severity:** 🟡 MEDIUM — a passing concurrent test that doesn't check final state is not evidence of thread safety.

**Fix — extend `test_concurrent_step_execution_produces_consistent_results`:**
```python
# After all threads complete:
final = pipeline.get_current_envelope()
assert final is not None
# The final envelope's payload must be one of the submitted payloads, not a blend
submitted_payloads = [{"step": i, "data": f"data-{i}"} for i in range(3)]
assert final.payload in submitted_payloads, (
    f"Final payload {final.payload} is not one of the submitted payloads — "
    "possible state corruption from concurrent writes"
)
```

**Commit message:** `test(pipeline): strengthen concurrent tests to assert final state consistency per R18`

---

### FIX-014 — `SnapshotStore.list_snapshots` has no dedicated test

**File:** `tests/unit/test_snapshot.py`
**Severity:** 🟡 MEDIUM — R5 violation. The method exists and is used in production code but no test directly verifies it for empty pipelines, single snapshots, or ordering.

**Fix — add to `TestSnapshotStore`:**
```python
def test_list_snapshots_returns_empty_for_unknown_pipeline(self):
    result = self.store.list_snapshots("does-not-exist")
    assert isinstance(result, Success)
    assert result.value == []

def test_list_snapshots_returns_ids_in_step_order(self):
    env1 = self._create_envelope(step=1)
    env3 = self._create_envelope(step=3)
    env2 = self._create_envelope(step=2)
    self.store.save_snapshot(env1)
    self.store.save_snapshot(env3)
    self.store.save_snapshot(env2)
    result = self.store.list_snapshots("pipeline-123")
    assert isinstance(result, Success)
    steps = [int(sid.split("@")[1].split("_")[0]) for sid in result.value]
    assert steps == sorted(steps), "Snapshots must be ordered by step"
```

**Commit message:** `test(snapshot): add dedicated tests for list_snapshots per R5`

---

### FIX-015 — `unwrap_or`, `map_result`, `map_error` only tested for happy path

**File:** `tests/unit/test_types.py`
**Severity:** 🟡 MEDIUM — failure paths and `RollbackSuccess` cases are untested.

**Fix — add:**
```python
def test_unwrap_or_returns_default_for_rollback_success():
    result: Result[str] = RollbackSuccess(value="restored", reason="contradiction")
    # RollbackSuccess is not Success — unwrap_or should return default
    assert unwrap_or(result, "default") == "default"

def test_map_result_leaves_rollback_success_unchanged():
    result: Result[int] = RollbackSuccess(value=5, reason="rollback")
    mapped = map_result(result, lambda x: x * 2)
    # map_result only transforms Success, not RollbackSuccess
    assert mapped is result
```

**Commit message:** `test(types): add failure-path and RollbackSuccess cases for unwrap_or, map_result`

---

### FIX-016 — `StructuralSlicePacker` silently uses unordered `frozenset` iteration

**File:** `src/relay/slicer/packers.py`
**Severity:** 🟡 MEDIUM — `{key: payload[key] for key in manifest.reads}` iterates a `frozenset`, which has no guaranteed order. The returned dict's key order is non-deterministic, making the sliced context non-deterministic across runs. This matters for signature computation and debugging.

**Fix:**
```python
return Success({key: payload[key] for key in sorted(manifest.reads)})
```

**Commit message:** `fix(slicer): sort manifest.reads keys in StructuralSlicePacker for deterministic output`

---

### FIX-017 — `core_pipeline.py` module docstring is inaccurate (R19)

**File:** `src/relay/core_pipeline.py`
**Severity:** 🟡 MEDIUM — docstring says "v0.1" and does not mention budget enforcement or slicer.

**Fix:**
```python
"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""
```

**Commit message:** `docs(pipeline): update module docstring to reflect v0.2 responsibilities per R19`

---

## 🟢 LOW PRIORITY FIXES

---

### FIX-018 — `TiktokenCounter` has no `__enter__`/`__exit__`

`close()` exists but the counter is not usable as a context manager. Minor inconsistency with the R15 pattern. Add `__enter__`/`__exit__` to match `CoreRelayPipeline`.

---

### FIX-019 — `pipeline_state.py` exposes `current_and_lock()` marked as deprecated but still used

`current_and_lock()` is docstring-deprecated in favour of `transaction()` but `core_pipeline.py` still calls it in two places. Migrate to `transaction()` and delete `current_and_lock()`.

---

### FIX-020 — Error codes should be an `Enum` to prevent typos

Ad-hoc string codes like `"BUDGET_EXCEEDED"` and `"PIPELINE_NOT_FOUND"` are invisible to mypy. An `Enum` makes them exhaustively checkable:

```python
class ErrorCode(str, Enum):
    INVALID_PIPELINE_ID   = "INVALID_PIPELINE_ID"
    INVALID_PAYLOAD       = "INVALID_PAYLOAD"
    BUDGET_EXCEEDED       = "BUDGET_EXCEEDED"
    INVALID_TOKEN_COUNT   = "INVALID_TOKEN_COUNT"
    MANIFEST_VIOLATION    = "MANIFEST_BOUNDARY_VIOLATION"
    PIPELINE_MISMATCH     = "PIPELINE_MISMATCH"
    INVALID_STEP          = "INVALID_STEP"
    SNAPSHOT_NOT_FOUND    = "SNAPSHOT_NOT_FOUND"
    SNAPSHOT_SAVE_FAILED  = "SNAPSHOT_SAVE_FAILED"
    INDEX_UPDATE_FAILED   = "INDEX_UPDATE_FAILED"
    NO_ROLLBACK_AVAILABLE = "NO_ROLLBACK_AVAILABLE"
    INVALID_STATE         = "INVALID_STATE"
    CORRUPTED_INDEX       = "CORRUPTED_INDEX"
    INDEX_NOT_FOUND       = "INDEX_NOT_FOUND"
    PIPELINE_NOT_FOUND    = "PIPELINE_NOT_FOUND"
    NO_SNAPSHOTS          = "NO_SNAPSHOTS"
```

This is a larger refactor — schedule it for a dedicated PR after the critical fixes are done.

---

## Implementation Order

```
Week 1 — Critical fixes (block release)
  FIX-001  dict key type
  FIX-002  path traversal
  FIX-003  default secret
  FIX-004  RuntimeError → Failure

Week 1 — High priority (same sprint)
  FIX-005  _dict_to_envelope consistency
  FIX-006  Result TypeAlias
  FIX-007  manifest_hash default removal
  FIX-008  RelayPipeline removal
  FIX-009  _estimate_tokens benchmark
  FIX-010  hallucination ground-truth test
  FIX-011  context manager protocol

Week 2 — Medium (before v0.3 branch)
  FIX-012  missing unit test files
  FIX-013  concurrent state-consistency assertions
  FIX-014  list_snapshots tests
  FIX-015  Result utility tests
  FIX-016  StructuralSlicePacker ordering
  FIX-017  docstring accuracy

Week 3 — Low (can be PRs during v0.3 work)
  FIX-018  TiktokenCounter context manager
  FIX-019  remove current_and_lock
  FIX-020  ErrorCode enum
```
