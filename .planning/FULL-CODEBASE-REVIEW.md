---
phase: full-codebase
reviewed: 2026-05-17T23:00:00Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - src/relay/__init__.py
  - src/relay/types.py
  - src/relay/envelope.py
  - src/relay/snapshot_protocol.py
  - src/relay/snapshot.py
  - src/relay/snapshot_in_memory.py
  - src/relay/validator.py
  - src/relay/context_broker.py
  - src/relay/core_pipeline.py
  - src/relay/pipeline_state.py
  - src/relay/pipeline_rollback.py
  - src/relay/budget/__init__.py
  - src/relay/budget/enforcer.py
  - src/relay/budget/token_counter.py
  - src/relay/slicer/__init__.py
  - src/relay/slicer/manifest.py
  - src/relay/slicer/packers.py
  - src/relay/slicer/providers.py
  - src/relay/parallel/__init__.py
  - src/relay/parallel/types.py
  - src/relay/parallel/fork_runner.py
  - src/relay/parallel/join.py
  - src/relay/runners/__init__.py
  - src/relay/runners/protocol.py
  - src/relay/runners/registry.py
  - src/relay/runners/local_model.py
  - src/relay/runners/langchain.py
  - src/relay/runners/crewai.py
  - src/relay/runners/autogen.py
  - src/relay/runners/raw_sdk.py
  - tests/conftest.py
  - tests/unit/__init__.py
  - tests/unit/test_types.py
  - tests/unit/test_envelope.py
  - tests/unit/test_snapshot.py
  - tests/unit/test_snapshot_in_memory.py
  - tests/unit/test_validator.py
  - tests/unit/test_context_broker.py
  - tests/unit/test_pipeline.py
  - tests/unit/test_pipeline_state.py
  - tests/unit/test_pipeline_rollback.py
  - tests/unit/test_budget.py
  - tests/unit/test_slicer.py
  - tests/unit/test_parallel/__init__.py
  - tests/unit/test_parallel/conftest.py
  - tests/unit/test_parallel/test_types.py
  - tests/unit/test_parallel/test_fork_runner.py
  - tests/unit/test_parallel/test_join.py
  - tests/unit/test_runners/conftest.py
  - tests/unit/test_runners/test_protocol.py
  - tests/unit/test_runners/test_registry.py
  - tests/unit/test_runners/test_local_model.py
  - tests/integration/test_pipeline_integration.py
  - tests/integration/test_parallel_pipeline.py
  - tests/integration/test_runners_integration.py
findings:
  critical: 2
  warning: 8
  info: 2
  total: 12
status: issues_found
---

# Phase: Full Codebase — Code Review Report

**Reviewed:** 2026-05-17T23:00:00Z
**Depth:** standard
**Files Reviewed:** 55
**Status:** issues_found

## Summary

This comprehensive review covers all source modules across 55 files (31 source + 24 test). The codebase is well-structured with strong typing, consistent error handling via `Result[T]`, and good test coverage. However, 12 findings were identified: 2 blockers (security/behavior), 8 warnings, and 2 info items.

**Previous review context:** Phase 01 review (`.planning/phases/01-snapshotstore-protocol-extraction/01-REVIEW.md`) had 4 warnings (all fixed) and 5 info items. Of the info items:
- IN-01 (stale imports): **NOT FIXED** — re-reported as WR-02
- IN-02 (signature verification docs): **FIXED** — docstring present in `snapshot_in_memory.py`
- IN-03 (double ContextBroker in create()): **NOT FIXED** — re-reported as WR-01
- IN-04 (None fork metadata in JSON): **FIXED** — conditionally serialized in `_envelope_to_dict`
- IN-05 (thread safety docs): **FIXED** — docstring present in `snapshot.py`

**New findings in this review:**
1. TOCTOU race between stat() and open() in `LocalFileSnapshotStore.load_snapshot` (BLOCKER)
2. `agent_output_to_payload` uses root logger, warnings silently lost (BLOCKER)
3. `_add_to_index` / `_remove_from_index` inconsistent error handling for corrupted JSON
4. `create_next_envelope` doesn't guard against step overflow to `_MAX_STEP`
5. `ContextBroker` signing_secret/current_key_id crash on empty keys
6. PreV04Compat temp directory leaks in tests
7. Missing test coverage for pipeline_id cross-check in load_snapshot
8. `LocalModelAdapter.run` silently converts non-dict API responses to empty dict

---

## Critical Issues

### CR-01: TOCTOU race in `LocalFileSnapshotStore.load_snapshot` between stat() and open()

**File:** `src/relay/snapshot.py:222-228`
**Issue:** The `load_snapshot` method calls `snapshot_path.stat()` to check file size against `MAX_SNAPSHOT_BYTES`, then separately opens the file with `open(snapshot_path, "r")`. Between these two operations, an attacker with local filesystem write access could replace the small file with a large one, bypassing the size check. This is a time-of-check-time-of-use (TOCTOU) vulnerability.

The `save_snapshot` path correctly uses `os.open()` with `O_CREAT | O_EXCL | O_NOFOLLOW` for atomic file creation, but the load path lacks equivalent protection.

```python
# Current code (lines 222-228):
stat_result = snapshot_path.stat()
if stat_result.st_size > MAX_SNAPSHOT_BYTES:
    return Failure(...)
with open(snapshot_path, "r") as f:    # <-- TOCTOU: file could be replaced here
    data: object = json.load(f)
```

**Fix:** Open the file first, then stat the open file descriptor to eliminate the race window:

```python
try:
    fd = os.open(snapshot_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r") as f:
        stat_result = os.fstat(fd)
        if stat_result.st_size > MAX_SNAPSHOT_BYTES:
            return Failure(
                reason=f"Snapshot file exceeds maximum size of {MAX_SNAPSHOT_BYTES} bytes",
                code=ErrorCode.SNAPSHOT_LOAD_FAILED,
            )
        data: object = json.load(f)
except (FileNotFoundError, OSError) as e:
    ...
```

---

### CR-02: `agent_output_to_payload` uses root logger, warnings silently lost in production

**File:** `src/relay/parallel/types.py:71`
**Issue:** The function uses `logging.warning(...)` which sends output to the **root logger**. Python's root logger by default has `WARNING` level but **no configured handler**, meaning the warning is silently discarded unless the application has explicitly configured logging. This warning is important — it signals data loss when `output.text` overwrites a `"text"` key in `output.structured`. Users debugging unexpected payloads would never see this warning.

```python
def agent_output_to_payload(output: AgentOutput) -> JSONDict:
    raw: JSONDict = dict(output.structured)
    if "text" in raw:
        logging.warning(    # <-- root logger, may be silently dropped
            "agent_output_to_payload: output.structured already contains a 'text' key; "
            "overwriting with output.text (structured value lost)"
        )
    raw["text"] = output.text
```

**Fix:** Use a module-level logger:

```python
import logging
logger = logging.getLogger(__name__)

def agent_output_to_payload(output: AgentOutput) -> JSONDict:
    raw: JSONDict = dict(output.structured)
    if "text" in raw:
        logger.warning(
            "agent_output_to_payload: output.structured already contains a 'text' key; "
            "overwriting with output.text (structured value lost)"
        )
    raw["text"] = output.text
```

---

## Warnings

### WR-01: `CoreRelayPipeline.create()` double-creates `ContextBroker` (formerly IN-03, unfixed)

**File:** `src/relay/core_pipeline.py:99-122`
**Issue:** The `create()` factory method calls `create_context_broker()` solely for validation (line 99-101), then overwrites the validated broker in `__post_init__` (line 119-122). The `create_signing_key()` call in `__post_init__` (line 119) generates a key that is immediately thrown away when line 113 replaces the broker. This wastes computation and creates a maintenance hazard if the two construction paths diverge. Reported as IN-03 in the previous review and **not fixed**.

**Fix:** Remove the redundant `ContextBroker` construction from `__post_init__`. Since `create()` already sets `pipeline._context_broker` after construction (line 113), the `__post_init__` broker is never used:

```python
def __post_init__(self) -> None:
    self._pipeline_id = uuid.uuid4().hex
    self._state = PipelineState(pipeline_id=self._pipeline_id)
    # REMOVE: key = create_signing_key(self.signing_secret)
    # REMOVE: self._context_broker = ContextBroker(...)
    self._handoff_validator = HandoffValidator()
    ...
```

`create()` already:
```python
pipeline = cls(...)
pipeline._context_broker = broker_result.value  # replaces the orphan broker
```

---

### WR-02: Stale local imports in `test_snapshot.py` (formerly IN-01, unfixed)

**File:** `tests/unit/test_snapshot.py`
**Issue:** Multiple test methods re-import modules already imported at the top of the file. These are copy-paste artifacts that clutter the code.

| Line(s) | Local import | Already imported at line |
|---------|-------------|--------------------------|
| 125-127 | `import json` / `from pathlib import Path` | 5 / 7 |
| 179-182 | `from pathlib import Path` | 7 |
| 192-197 | `from pathlib import Path` / `from unittest.mock import patch` | 7 / 9 |
| 207-210 | `from pathlib import Path` | 7 |
| 583-584 | `from relay.envelope import create_initial_envelope` | 13 |
| 642-643 | `import tempfile` | 6 |

**Fix:** Remove the redundant local imports.

---

### WR-03: `ContextBroker.signing_secret` and `current_key_id` crash on empty keys dict

**File:** `src/relay/context_broker.py:78-88`
**Issue:** The `signing_secret` and `current_key_id` properties call `max(self.keys.values(), key=_by_created_at)` which raises `ValueError: max() arg is an empty sequence` if the `keys` dict is empty. While direct construction with empty keys is not the intended API (documented as "internal use with pre-validated secrets" in the class docstring), there is no guard. A typo or bug during construction that results in empty keys would cause a hard crash rather than a clear error.

```python
@property
def signing_secret(self) -> str:
    return max(self.keys.values(), key=_by_created_at).secret  # ValueError if empty

@property
def current_key_id(self) -> str:
    return max(self.keys.values(), key=_by_created_at).key_id  # ValueError if empty
```

**Fix:** Add an explicit guard:

```python
@property
def signing_secret(self) -> str:
    if not self.keys:
        raise ValueError("ContextBroker has no signing keys configured")
    return max(self.keys.values(), key=_by_created_at).secret
```

---

### WR-04: PreV04Compat tests in `test_snapshot.py` leak temporary directories

**File:** `tests/unit/test_snapshot.py:618-682`
**Issue:** Three methods in `TestPreV04SnapshotCompat` create temp directories via `tempfile.mkdtemp()` inline but never clean them up:

- `test_loading_snapshot_without_fork_fields_succeeds` (line 620)
- `test_envelope_to_dict_includes_fork_fields_when_serialized` (line 642)
- `test_roundtrip_envelope_with_fork_fields` (line 660 — has try/finally cleanup for one, but the other methods don't)

These accumulate temp directories across test runs, consuming disk space. This is a test reliability concern.

**Fix:** Use `tempfile.mkdtemp()` in `setup_method` with `shutil.rmtree` in `teardown_method`, or use `tmp_path` fixture if pytest >= 7.3.

---

### WR-05: `_add_to_index` and `_remove_from_index` inconsistent error handling for corrupted index

**Files:**
- `src/relay/snapshot.py:331-339` (`_add_to_index`)
- `src/relay/snapshot.py:109-110` (`_remove_from_index`)

**Issue:** When the index file contains corrupted JSON:
- `_add_to_index` returns `Failure(code=ErrorCode.CORRUPTED_INDEX)` — properly surfaces the error.
- `_remove_from_index` catches `(json.JSONDecodeError, OSError)` and returns `Success(None)` — silenty ignores the corruption.

This asymmetry means: if the index file is corrupted, a `save_snapshot` call surfaces the error, but a `delete_snapshot` call silently succeeds without updating the index, leaving the snapshot file orphaned (file exists but not tracked in index).

```python
# _remove_from_index (line 109-110):
except (json.JSONDecodeError, OSError):
    return Success(None)  # <-- silently discards error

# _add_to_index (line 331-335):
except json.JSONDecodeError as e:
    return Failure(
        reason=f"Corrupted index JSON: {e}",
        code=ErrorCode.CORRUPTED_INDEX,  # <-- properly surfaces error
    )
```

**Fix:** Make `_remove_from_index` either propagate the corruption error like `_add_to_index` does, or document why silent swallowing is intentional:

```python
except json.JSONDecodeError as e:
    return Failure(
        reason=f"Corrupted index JSON: {e}",
        code=ErrorCode.CORRUPTED_INDEX,
    )
except OSError as e:
    # File may have been deleted between check and open — not an error
    return Success(None)
```

---

### WR-06: `create_next_envelope` doesn't guard against step overflow to `_MAX_STEP`

**File:** `src/relay/envelope.py:274-288`
**Issue:** `ContextEnvelope.__post_init__` raises `ValueError` if `step > _MAX_STEP` (lines 98-99). However, `create_next_envelope` increments the step at line 279 (`step=previous_envelope.step + 1`) without checking against `_MAX_STEP`. If enough steps are taken (10^6 sequential calls), the `ContextEnvelope(...)` constructor would raise `ValueError`.

This ValueError propagates as an **unhandled exception**, not a `Result[Failure]`, violating the contract that all operational errors are returned as `Failure`. The callers in `core_pipeline.py` (`_handle_subsequent_step`, `execute_parallel_step`) check for `Failure` return, but not for exceptions.

```python
envelope = ContextEnvelope(
    ...
    step=previous_envelope.step + 1,  # 10^6+1 -> ValueError in __post_init__
    ...
)
```

While reaching 10^6 steps is practically impossible in normal use, the contract violation matters for correctness. `create_initial_envelope` has the same issue if `step=1` exceeds `_MAX_STEP` — but `_MAX_STEP = 10^6` so step=1 always passes.

**Fix:** Add a pre-check before constructing the envelope:

```python
def create_next_envelope(...) -> Result[ContextEnvelope]:
    if not agent_output:
        return Failure(reason=..., code=ErrorCode.INVALID_PAYLOAD)
    next_step = previous_envelope.step + 1
    if next_step > _MAX_STEP:
        return Failure(
            reason=f"Step {next_step} exceeds maximum {_MAX_STEP}",
            code=ErrorCode.INVALID_STEP,
        )
    ...
```

---

### WR-07: Missing test coverage for pipeline_id cross-check in `load_snapshot`

**Files:**
- `tests/unit/test_snapshot.py:123-139`
- `tests/unit/test_snapshot_in_memory.py`

**Issue:** The WR-02 fix from the Phase 01 review added a cross-check in `load_snapshot` that validates `envelope.pipeline_id` matches the pipeline_id extracted from the snapshot filename. Both stores return `Failure(code=ErrorCode.INVALID_SNAPSHOT)` on mismatch.

However, the existing test (`test_load_snapshot_fails_when_body_pipeline_id_is_invalid` at line 123) modifies the body `pipeline_id` to `"../../../etc"` — which fails at the `validate_pipeline_id()` format check, returning `ErrorCode.INVALID_PIPELINE_ID`. This test never reaches the cross-check. There is no test that sets the body pipeline_id to a **different but valid** pipeline_id (e.g., `"other-pipe"`), which would be required to exercise the cross-check path.

The in-memory store has no test for the cross-check path at all.

**Fix:** Add tests for both stores that set the body pipeline_id to a different valid value:

```python
def test_load_snapshot_fails_on_pipeline_id_mismatch(self) -> None:
    """Body pipeline_id differs from filename -> INVALID_SNAPSHOT."""
    env = self._create_envelope(pipeline_id="pipe-a", step=1)
    save_result = self.store.save_snapshot(env)
    assert isinstance(save_result, Success)
    snapshot_id = save_result.value

    path = Path(self.temp_dir) / "pipe-a" / f"{snapshot_id}.json"
    read_data = json.loads(path.read_text())
    read_data["pipeline_id"] = "other-valid-pipe"
    path.write_text(json.dumps(read_data))

    result = self.store.load_snapshot(snapshot_id)
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.INVALID_SNAPSHOT
```

---

### WR-08: `LocalModelAdapter.run` silently converts non-dict API response to empty dict

**File:** `src/relay/runners/local_model.py:98-102`
**Issue:** When the API returns a non-dict response (e.g., a JSON array or scalar), the code silently replaces it with an empty dict:

```python
data_raw: object = response.json()
if not isinstance(data_raw, dict):
    data_raw = {}  # <-- silently converts structural API error
data = cast(JSONDict, data_raw)
```

This disguises API misconfigurations. If a user accidentally points to an endpoint that returns an array instead of an object, the adapter would silently return an empty output rather than surfacing the structural mismatch. The only symptom would be empty text, which triggers `AgentOutput`'s validation ("At least one of text or structured must be non-empty"), but the root cause (wrong response format) is lost.

**Fix:** Return an error or log a warning when response is not a dict:

```python
if not isinstance(data_raw, dict):
    raise ValueError(
        f"Expected JSON object from API, got {type(data_raw).__name__}. "
        f"Response: {response.text[:500]}"
    )
```

---

## Info

### IN-01: `RecencySlicePacker._recency_sort_key` extracts last `_`-delimited segment which may lose meaning for multi-segment keys

**File:** `src/relay/slicer/packers.py:58-61`
**Issue:** The sort key extraction takes the last `_`-delimited segment as the numeric suffix:
```python
if "_" in k and k.split("_")[-1].isdigit():
    return (0, int(k.split("_")[-1]), k)
```
For flat keys like `section_5`, this correctly extracts 5. But for multi-segment keys like `section_5_part_2`, it would extract `2` instead of the more meaningful `5`. While this is a documented heuristic and unlikely to cause issues in practice (keys are typically flat), it could produce surprising sort order.

**Fix:** None required for correctness. Consider documenting the limitation, or using the first numeric segment found when scanning right-to-left.

---

### IN-02: `HeuristicCounter.count("")` returns 1 instead of 0

**File:** `src/relay/budget/token_counter.py:33-34`
**Issue:** `HeuristicCounter.count("")` returns `max(1, 0) = 1`. This means an empty slice always counts as 1 token, guaranteeing that an empty string always has a non-zero token count. While this prevents division-by-zero downstream, it means `count("") == 1` is always consumed from the budget even for zero-length inputs. This is by design (documented) but worth noting for future optimization.

**Fix:** None required — the behavior is documented and tested.

---

## Structural Findings (fallow)

No structural pre-pass was provided for this review. Cross-module analysis was performed as part of the standard-depth review.

---

_Reviewed: 2026-05-17T23:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
