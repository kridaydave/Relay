---
phase: 01-snapshotstore-protocol-extraction
plan: 01
subsystem: snapshot
tags: [protocol, refactor, snapshot-store, runtime-checkable]

requires: []
provides:
  - SnapshotStore Protocol (@runtime_checkable + Closeable)
  - LocalFileSnapshotStore renamed concrete class
  - Protocol acceptance tests for isinstance checks
affects: [02-structured-audit-logging]

tech-stack:
  added: []
  patterns:
    - Protocol-based dependency inversion for SnapshotStore
    - @runtime_checkable decorator on all pluggable protocols

key-files:
  created:
    - src/relay/snapshot_protocol.py
  modified:
    - src/relay/snapshot.py (class rename + close())
    - src/relay/types.py (Closeable made @runtime_checkable)
    - src/relay/core_pipeline.py (imports + __post_init__ fix)
    - src/relay/pipeline_rollback.py (import path)
    - src/relay/__init__.py (exports + imports)
    - tests/unit/test_snapshot.py (imports + Protocol tests)
    - tests/unit/test_pipeline.py (patch target)
    - tests/unit/test_pipeline_rollback.py (import path)

key-decisions:
  - "Closeable made @runtime_checkable to support isinstance checks in tests (required by Protocol acceptance test)"
  - "SnapshotStore Protocol inherits Closeable — all stores must implement close()"
  - "LocalFileSnapshotStore.close() is a no-op (filesystem handles released between operations)"

patterns-established:
  - "Snapshot storage backends implement SnapshotStore Protocol (dependency inversion)"
  - "Client code types against SnapshotStore Protocol, constructs LocalFileSnapshotStore"

requirements-completed: [STO-01, STO-02]

duration: 4 min
completed: 2026-05-17
---

# Phase 1 Plan 1: Extract SnapshotStore Protocol + Rename to LocalFileSnapshotStore

**SnapshotStore extracted as a @runtime_checkable Protocol extending Closeable, with LocalFileSnapshotStore as the renamed file-based implementation, all consumers and tests updated**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-17T16:23:00Z
- **Completed:** 2026-05-17T16:27:25Z
- **Tasks:** 5 (all committed atomically)
- **Files modified:** 9 (1 created, 8 modified)

## Accomplishments

- Created `src/relay/snapshot_protocol.py` with `SnapshotStore` `@runtime_checkable` Protocol extending `Closeable`, defining 5 methods with docstrings
- Renamed `SnapshotStore` class to `LocalFileSnapshotStore` in `src/relay/snapshot.py`, added `close()` no-op method
- Updated all consumer imports: `core_pipeline.py`, `pipeline_rollback.py`, `__init__.py` to import `SnapshotStore` from `snapshot_protocol` and `LocalFileSnapshotStore` from `snapshot`
- Fixed `core_pipeline.__post_init__` to construct `LocalFileSnapshotStore` (not the Protocol)
- Updated all test files: `test_snapshot.py` (imports + constructor calls), `test_pipeline.py` (patch target), `test_pipeline_rollback.py` (import source)
- Added `TestSnapshotStoreProtocol` with acceptance tests for `isinstance` checks, `@runtime_checkable`, method signatures, and `Closeable` subtyping
- Made `Closeable` Protocol `@runtime_checkable` in `types.py` (required by acceptance test)

## Task Commits

Each task was committed atomically:

1. **01-01-A: Create SnapshotStore Protocol** - `772ab1b` (feat)
2. **01-01-B: Rename SnapshotStore → LocalFileSnapshotStore** - `135eae6` (feat)
3. **01-01-C: Update consumer imports + fix __post_init__** - `5db65a7` (feat)
4. **01-01-D: Update tests** - `61d8ad7` (feat)
5. **01-01-E: Add Protocol acceptance test** - `dcfe292` (feat)

## Files Created/Modified

- `src/relay/snapshot_protocol.py` - New: SnapshotStore Protocol with 5 methods
- `src/relay/snapshot.py` - Rename class, add close(), update __all__
- `src/relay/types.py` - Added @runtime_checkable to Closeable
- `src/relay/core_pipeline.py` - Import from snapshot_protocol, construct LocalFileSnapshotStore
- `src/relay/pipeline_rollback.py` - Import SnapshotStore from snapshot_protocol
- `src/relay/__init__.py` - Export both SnapshotStore and LocalFileSnapshotStore
- `tests/unit/test_snapshot.py` - LocalFileSnapshotStore constructors + Protocol acceptance tests
- `tests/unit/test_pipeline.py` - Patch target: LocalFileSnapshotStore
- `tests/unit/test_pipeline_rollback.py` - Import from snapshot_protocol

## Decisions Made

- **Closeable made @runtime_checkable**: Required to support `isinstance(LocalFileSnapshotStore(...), Closeable)` in Protocol acceptance tests. No behavioral change.
- **LocalFileSnapshotStore.close() is a no-op**: Filesystem handles are not kept open between operations, so no cleanup is needed. The method exists to satisfy the Protocol contract.
- **SnapshotStore as the type annotation, LocalFileSnapshotStore for construction**: Client code types against the Protocol (dependency inversion) but constructs the concrete implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Closeable Protocol not @runtime_checkable**
- **Found during:** Task 01-01-E (Protocol acceptance test)
- **Issue:** `isinstance(LocalFileSnapshotStore(...), Closeable)` raised `TypeError` because `Closeable` was not decorated with `@runtime_checkable`
- **Fix:** Added `@runtime_checkable` decorator to `Closeable` class in `src/relay/types.py` and imported `runtime_checkable` from `typing`
- **Files modified:** `src/relay/types.py`
- **Verification:** `isinstance(store, Closeable)` returns `True` for `LocalFileSnapshotStore` instances
- **Committed in:** `dcfe292` (part of Task 01-01-E commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary fix — the plan required `isinstance` checks against `Closeable` to work. No scope creep.

## Issues Encountered

None — all tasks executed as specified with one auto-fix for Closeable runtime_checkable.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- SnapshotStore Protocol extracted and consumers updated
- `LocalFileSnapshotStore` ready for additional storage backends (Phase 7: Pluggable Backends)
- Ready for Plan 01-02: Structured Audit Logging

---

*Phase: 01-snapshotstore-protocol-extraction*
*Completed: 2026-05-17*
