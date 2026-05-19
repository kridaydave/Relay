---
phase: 01-snapshotstore-protocol-extraction
fixed_at: 2026-05-17T22:00:00Z
review_path: docs/history/01-snapshotstore-protocol-extraction/01-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 01: SnapshotStore Protocol Extraction — Code Review Fix Report

**Fixed at:** 2026-05-17T22:00:00Z
**Source review:** `docs/history/01-snapshotstore-protocol-extraction/01-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (Warnings only)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: InMemorySnapshotStore.save_snapshot — inconsistent state on sort failure

**Files modified:** `src/relay/snapshot_in_memory.py`
**Commit:** `98c8a3e`
**Applied fix:** Reordered the index-sort before the envelope storage. Previously, the envelope was stored first in `self._snapshots[pipeline_id]`, then the index was sorted. If `sort()` raised `InvalidSnapshotIdError`, the store would contain an orphaned envelope not visible to `list_snapshots()` or `get_latest_snapshot()`. Now the index is updated and sorted first; the envelope is stored after, so a sort failure leaves no inconsistent state.

### WR-02: load_snapshot — missing pipeline_id cross-check between filename and envelope body

**Files modified:**
- `src/relay/snapshot.py`
- `src/relay/snapshot_in_memory.py`

**Commit:** `9f8aadb`
**Applied fix:** Added a cross-check in both `LocalFileSnapshotStore.load_snapshot()` and `InMemorySnapshotStore.load_snapshot()` after envelope deserialization. If `envelope.pipeline_id != pipeline_id` (where `pipeline_id` is extracted from the snapshot ID), the method returns `Failure(code=ErrorCode.INVALID_SNAPSHOT)` with a descriptive message. This closes a defense-in-depth gap — the `step` field was already cross-checked but `pipeline_id` was not.

### WR-03: Private function import — _extract_step_from_snapshot_id used from external modules

**Files modified:**
- `src/relay/snapshot_protocol.py`
- `src/relay/snapshot_in_memory.py`
- `src/relay/snapshot.py`

**Commit:** `3850c7d`
**Applied fix:** Renamed `_extract_step_from_snapshot_id` to `extract_step_from_snapshot_id` (public) in `snapshot_protocol.py`. Added it to `__all__`. Updated all imports and call sites in `snapshot_in_memory.py` and `snapshot.py`. This promotes a de facto shared utility to a stable public API.

### WR-04: _remove_from_index silently rewrites non-conforming index files

**File modified:** `src/relay/snapshot.py`
**Commit:** `d87a4cc`
**Applied fix:** Added a `logger.warning()` call in `_remove_from_index()` when the loaded index data is not a `dict` (e.g., JSON array). Previously, the code silently replaced the non-conforming data with `{}` and rewrote the file as `{"snapshots": []}`. Now the user gets a warning log before the reset. The existing module-level `logger` is used.

---

_Fixed: 2026-05-17T22:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
