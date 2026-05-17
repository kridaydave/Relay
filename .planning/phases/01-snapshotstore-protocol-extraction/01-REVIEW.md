---
phase: 01-snapshotstore-protocol-extraction
reviewed: 2026-05-17T21:45:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - src/relay/snapshot_protocol.py
  - src/relay/snapshot.py
  - src/relay/types.py
  - src/relay/core_pipeline.py
  - src/relay/pipeline_rollback.py
  - src/relay/__init__.py
  - src/relay/snapshot_in_memory.py
  - tests/unit/test_snapshot.py
  - tests/unit/test_pipeline.py
  - tests/unit/test_pipeline_rollback.py
  - tests/unit/test_snapshot_in_memory.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 01: SnapshotStore Protocol Extraction — Code Review Report

**Reviewed:** 2026-05-17T21:45:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

This is a follow-up review of Phase 1 (SnapshotStore Protocol extraction) after fixes from a prior review (which found 5 warnings, 3 info items). The following issues from the previous review have been **fixed**:

| Previous Finding | Status |
|---|---|
| WR-01: Backward-compat SnapshotStore alias in snapshot.py | **FIXED** — now uses proper re-export: `from relay.snapshot_protocol import SnapshotStore as SnapshotStore` |
| WR-03: TOCTOU race in save_snapshot | **FIXED** — uses `os.open()` with `O_CREAT \| O_EXCL \| O_NOFOLLOW` |
| WR-05: delete_snapshot untested | **FIXED** — `TestLocalFileSnapshotStoreDelete` and `TestInMemorySnapshotStoreDelete` added |
| IN-03: Test cleanup NameError in Protocol tests | **FIXED** — uses separate `tmp` variable |

**Partially fixed:**
| Previous Finding | Status |
|---|---|
| WR-02: Private function import | **PARTIALLY FIXED** — import source changed to `snapshot_protocol.py`, but `_extract_step_from_snapshot_id` is still `_`-prefixed |
| WR-04: Inconsistent state on sort failure (in-memory) | **NOT FIXED** — still no try/except rollback |
| IN-01: Stale local imports | **NOT FIXED** — redundant imports remain |
| IN-02: Missing signature verification documentation | **NOT FIXED** — still undocumented |

**New findings in this review:**
1. `load_snapshot` in both stores does not cross-check `pipeline_id` consistency between filename and envelope body
2. `_remove_from_index` silently rewrites non-conforming index files without logging
3. `CoreRelayPipeline.create()` double-creates `ContextBroker` instances
4. None fork metadata fields produce verbose JSON
5. `LocalFileSnapshotStore` has no thread safety documentation

---

## Warnings

### WR-01: `InMemorySnapshotStore.save_snapshot` can leave inconsistent state if sort raises

**File:** `src/relay/snapshot_in_memory.py:59-63`

**Issue:** The method stores the deep-copied envelope in `self._snapshots` (line 59), then sorts the index using `_extract_step_from_snapshot_id` (line 63). If `sort()` raises `InvalidSnapshotIdError`, the exception propagates while `self._snapshots[pipeline_id]` already contains the entry. The store ends up with a snapshot that is not in the sorted index, making it invisible to `list_snapshots()` and `get_latest_snapshot()`.

While the ID is constructed internally (step+uuid) and would only fail if the format changes, this is a latent data-consistency bug. The same finding was reported in the previous review (WR-04) and has not been addressed.

**Fix:** Wrap the append-and-sort in a try/except that rolls back the snapshot insertion on failure, or move the sort above the envelope storage:

```python
# Option A: try/except rollback
try:
    if snapshot_id not in self._index[pipeline_id]:
        self._index[pipeline_id].append(snapshot_id)
        self._index[pipeline_id].sort(key=_extract_step_from_snapshot_id)
except InvalidSnapshotIdError:
    del self._snapshots[pipeline_id][snapshot_id]
    raise

# Option B: sort before store
if snapshot_id not in self._index[pipeline_id]:
    self._index[pipeline_id].append(snapshot_id)
    self._index[pipeline_id].sort(key=_extract_step_from_snapshot_id)
self._snapshots[pipeline_id][snapshot_id] = deepcopy(envelope)
```

---

### WR-02: `load_snapshot` does not cross-check pipeline_id between filename and envelope body

**Files:**
- `src/relay/snapshot.py:193-249` — `LocalFileSnapshotStore.load_snapshot`
- `src/relay/snapshot_in_memory.py:67-103` — `InMemorySnapshotStore.load_snapshot`

**Issue:** Both `load_snapshot` implementations extract `pipeline_id` from the snapshot ID (the part before `@`) and use it for filesystem/dict lookup, but neither validates that the loaded envelope's `pipeline_id` field matches the filename-derived pipeline_id. The `step` field IS cross-checked (line 227 in `snapshot.py`, line 94 in `snapshot_in_memory.py`), creating a false sense of consistency verification.

If a snapshot file is tampered with locally (changing `pipeline_id` in the envelope body without changing the filename), a rollback operation could restore an envelope whose `pipeline_id` differs from the expected value. This could cause pipeline_id confusion in downstream code that reads the restored envelope's `pipeline_id` field.

While this requires local filesystem access, it's a defense-in-depth gap that makes the tampering surface asymmetric between `step` (protected) and `pipeline_id` (unprotected).

**Fix:** Add a cross-check in both `load_snapshot` implementations after deserializing the envelope:

```python
# In LocalFileSnapshotStore.load_snapshot (after line 225):
if envelope.pipeline_id != pipeline_id:
    return Failure(
        reason=(
            f"Snapshot integrity error: filename indicates pipeline {pipeline_id} "
            f"but envelope body contains pipeline {envelope.pipeline_id}"
        ),
        code=ErrorCode.INVALID_SNAPSHOT,
    )

# Same pattern in InMemorySnapshotStore.load_snapshot (after line 93):
if envelope.pipeline_id != pipeline_id:
    return Failure(
        reason=(
            f"Snapshot integrity error: snapshot ID indicates pipeline {pipeline_id} "
            f"but envelope body contains pipeline {envelope.pipeline_id}"
        ),
        code=ErrorCode.INVALID_SNAPSHOT,
    )
```

---

### WR-03: `InMemorySnapshotStore` imports private helper despite better import location

**File:** `src/relay/snapshot_in_memory.py:12`

**Issue:** The import `from relay.snapshot_protocol import SNAPSHOT_ID_PATTERN, _extract_step_from_snapshot_id` now correctly sources from the protocol module rather than `snapshot.py` (which was the previous concern). However, `_extract_step_from_snapshot_id` remains a private function (underscore-prefixed). The previous review recommended promoting it to a public function to signal cross-module stability.

Using a private function from another module is fragile — if its signature, exception type, or behavior changes, the in-memory store breaks without warning. The function is also used by `snapshot.py` itself (imported at line 19), making it a de facto shared utility that should be public.

**Fix:** Rename to `extract_step_from_snapshot_id` (no underscore prefix) in `snapshot_protocol.py`:

```python
# In snapshot_protocol.py:
def extract_step_from_snapshot_id(s_id: str) -> int:
    ...

# In snapshot_in_memory.py:
from relay.snapshot_protocol import SNAPSHOT_ID_PATTERN, extract_step_from_snapshot_id

# In snapshot.py:
from relay.snapshot_protocol import (
    SNAPSHOT_ID_PATTERN, InvalidSnapshotIdError, extract_step_from_snapshot_id,
)
```

Or keep the private name and create a public alias. Either way, make the public contract explicit.

---

### WR-04: `_remove_from_index` silently rewrites non-conforming index files

**File:** `src/relay/snapshot.py:89-126`

**Issue:** The `_remove_from_index` method handles index files that are valid JSON but not a `dict` (e.g., a JSON array) by silently replacing the file with `{"snapshots": []}`. The relevant code:

```python
data: object = json.load(f)
index_data = cast(JSONDict, data) if isinstance(data, dict) else {}
```

When `data` is not a `dict`, `index_data` becomes `{}`. Then `existing = index_data.get("snapshots", [])` returns `[]`, and the file is rewritten as `{"snapshots": []}`, silently erasing whatever content was in the file.

While the expected schema is `{"snapshots": list[str]}`, there is no log message or warning when this silent replacement occurs. If a user's index file had a valid but unexpected structure (e.g., `{"snapshots": {...}}`), the content is silently destroyed during a `delete_snapshot` call for a completely different pipeline.

The same pattern exists in `_add_to_index` (lines 302-308), where a non-dict file causes a fresh empty list to be used.

**Fix:** Log a warning before overwriting a non-conforming index, and consider returning a `Failure` instead of silently rewriting:

```python
except (json.JSONDecodeError, OSError):
    return Success(None)

if not isinstance(data, dict):
    logger.warning(
        "Index file %s has unexpected format (expected dict, got %s) — "
        "resetting to empty index", index_path, type(data).__name__,
    )
    index_data = {}
```

---

## Info

### IN-01: Stale local imports in test_snapshot.py

**File:** `tests/unit/test_snapshot.py`

**Issue:** Several test methods re-import modules already imported at the top of the file:

| Line(s) | Local import | Top-level import line |
|---------|-------------|----------------------|
| 125-127 | `import json` / `from pathlib import Path` | 5 / 7 |
| 179-182 | `from pathlib import Path` | 7 |
| 192-197 | `from pathlib import Path` / `from unittest.mock import patch` | 7 / 9 |
| 207-210 | `from pathlib import Path` | 7 |

These are copy-paste artifacts. They don't cause errors (Python's import system deduplicates), but they clutter the code and suggest the methods may have been extracted or copied without cleanup. This was reported in the previous review (IN-01) and has not been addressed.

**Fix:** Remove the redundant local imports.

---

### IN-02: `InMemorySnapshotStore` does not document missing signature verification

**File:** `src/relay/snapshot_in_memory.py:1-4` (module docstring) and `lines 67-103` (`load_snapshot`)

**Issue:** The `InMemorySnapshotStore.load_snapshot` method does not verify HMAC signatures, while `LocalFileSnapshotStore.load_snapshot` does (when `signing_secret` is set). This is acceptable for the documented purpose ("testing and lightweight pipelines"), but the class and method docstrings do not explicitly state that signatures are not verified.

A user switching from `LocalFileSnapshotStore` to `InMemorySnapshotStore` in production (e.g., for speed) would silently lose integrity guarantees.

**Fix:** Add explicit documentation:

```python
# Class docstring:
# NOTE: InMemorySnapshotStore does NOT verify envelope signatures.
# Use LocalFileSnapshotStore with a signing_secret for integrity guarantees.
```

---

### IN-03: `CoreRelayPipeline.create()` double-creates `ContextBroker`

**File:** `src/relay/core_pipeline.py:99-122`

**Issue:** The `create()` factory method calls `create_context_broker(signing_secret=..., token_budget_total=...)` at line 99-101 solely for validation (checking signing_secret length). Then `__post_init__` at line 119-122 creates a *second* `ContextBroker` via raw construction:

```python
key = create_signing_key(self.signing_secret)
self._context_broker = ContextBroker(
    keys={key.key_id: key}, token_budget_total=self.token_budget
)
```

The broker from `create_context_broker` is discarded. This is wasteful (two instances created) and creates a maintenance hazard if the two construction paths diverge in behavior. The signing key created by `create_context_broker` is thrown away and a new one is generated by `__post_init__`.

**Fix:** Pass the broker validated by `create_context_broker` into the `cls()` call instead of re-creating it in `__post_init__`:

```python
@classmethod
def create(cls, ...) -> Result["CoreRelayPipeline"]:
    broker_result = create_context_broker(
        signing_secret=signing_secret, token_budget_total=token_budget
    )
    if isinstance(broker_result, Failure):
        return broker_result
    pipeline = cls(
        signing_secret=signing_secret,
        token_budget=token_budget,
        storage_path=storage_path,
        token_counter=token_counter,
        slice_packer=slice_packer,
        registry=registry,
        snapshot_store=snapshot_store,
    )
    # Replace the default broker with the validated one
    pipeline._context_broker = broker_result.value
    return Success(pipeline)
```

---

### IN-04: None fork metadata fields produce verbose JSON with null values

**File:** `src/relay/snapshot.py:396-404`

**Issue:** The `_envelope_to_dict` method unconditionally serializes all four fork metadata fields:

```python
"fork_id": envelope.fork_id,      # None for non-fork steps
"join_strategy": envelope.join_strategy,  # None for non-fork steps
"fork_count": envelope.fork_count,        # None for non-fork steps
"forks_succeeded": envelope.forks_succeeded,  # None for non-fork steps
```

For the vast majority of snapshots (non-fork steps), these serialize as `null` in JSON. This adds ~50 bytes per snapshot file and means that every `_dict_to_envelope` call for a pre-v0.4 snapshot will log `SnapShot missing key_id field` warnings.

While backward compatibility is handled correctly (lines 496-530), omitting None-valued fields would produce cleaner output and reduce file size.

**Fix:** Use a conditionally-built dict, or wrap fields in a helper:

```python
result: JSONDict = {
    "relay_version": envelope.relay_version,
    # ... core fields ...
}
if envelope.fork_id is not None:
    result["fork_id"] = envelope.fork_id
    result["join_strategy"] = envelope.join_strategy
    result["fork_count"] = envelope.fork_count
    result["forks_succeeded"] = envelope.forks_succeeded
```

---

### IN-05: `LocalFileSnapshotStore` has no thread safety documentation

**File:** `src/relay/snapshot.py:31-36`

**Issue:** `InMemorySnapshotStore` explicitly documents its thread safety model (module docstring, line 22-23): *"Thread safety: uses threading.Lock for per-method atomicity but does not provide snapshot-level atomicity across method calls."*

`LocalFileSnapshotStore` has no such documentation and uses no locking. Concurrent calls to `save_snapshot` and `delete_snapshot`, or concurrent saves for the same pipeline, can race on index file reads and writes. While `os.replace` provides atomic file replacement, the read-modify-write cycle in `_add_to_index` / `_remove_from_index` is not atomic across calls.

This is acceptable if the store is only used from a single-threaded context (which is typical for `CoreRelayPipeline` holding a single pipeline lock), but the lack of documentation means consumers may not realize they need external synchronization.

**Fix:** Add thread safety documentation to `LocalFileSnapshotStore` class docstring:

```python
# Thread safety: This implementation is NOT thread-safe by itself.
# Concurrent access must be serialized externally (e.g., via
# CoreRelayPipeline's transaction lock).
```

---

_Reviewed: 2026-05-17T21:45:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
