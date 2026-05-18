# Internal Changelog

> Internal record of all changes. Will be refined into public changelog entries.

## 2026-05-17

### Code Review Fixes (commit `c3e979e`)
- **CR-01** — Fixed TOCTOU race in `LocalFileSnapshotStore.load_snapshot`: `open()` then `os.fstat(fd)` replaces `stat()` + `open()` pattern
- **CR-02** — Added module-level logger in `agent_output_to_payload` (`parallel/types.py`), replaced root `logging.warning()`
- **WR-03** — Added empty-keys guard to `ContextBroker.signing_secret` / `current_key_id` properties
- **WR-05** — Made `_remove_from_index` return `Failure(code=ErrorCode.CORRUPTED_INDEX)` on JSON errors (consistent with `_add_to_index`)
- **WR-06** — Added step-overflow pre-check in `create_next_envelope` (`envelope.py`)
- **WR-08** — Replaced silent non-dict conversion with `ValueError` in `LocalModelAdapter.run`
- **WR-02** — Removed stale/redundant local imports from `test_snapshot.py`
- **WR-04** — Fixed temp directory leaks in `TestPreV04SnapshotCompat` via `setup_method`/`teardown_method`
- **WR-07** — Added `test_load_snapshot_fails_when_body_pipeline_id_differs_from_filename` test

### Full Codebase Review
- Conducted comprehensive review of all 31 source modules + 24 test files
- Full report at `.planning/FULL-CODEBASE-REVIEW.md`

## 2026-05-17 (Phase 01 Fixes)

### Code Review Fix Round 2 (commit `ff32c25`)
- **IN-01** — Removed stale local imports in `test_snapshot.py`
- **IN-02** — Added signature verification docs to `InMemorySnapshotStore`
- **IN-03** — Fixed double `ContextBroker` creation in `CoreRelayPipeline.create()`
- **IN-04** — Conditional fork metadata serialization (omit None fields)
- **IN-05** — Added thread safety documentation to `LocalFileSnapshotStore`

### WR-01 Fix (commit `98c8a3e`)
- Reordered index sort before envelope storage in `InMemorySnapshotStore.save_snapshot` to prevent inconsistent state on sort failure

### WR-02 Fix (commit `9f8aadb`)
- Added `pipeline_id` cross-check in both `LocalFileSnapshotStore.load_snapshot()` and `InMemorySnapshotStore.load_snapshot()`

### WR-03 Fix (commit `3850c7d`)
- Promoted `_extract_step_from_snapshot_id` to public `extract_step_from_snapshot_id` in `snapshot_protocol.py`

### WR-04 Fix (commit `d87a4cc`)
- Added `logger.warning()` in `_remove_from_index` when overwriting non-conforming index files

## 2026-05-18

### Rule 7.1 Test Name Fix
- **50 test name violations** in `test_audit_events.py`, `test_audit_redactor.py`, `test_audit_sink.py` renamed to full sentences by appending connecting words (`_when_constructed`, `_when_provided`, `_when_called`, `_with_isinstance`, etc.)
- Commit `96de10b` — `fix(tests): rename 50 tests to full sentences per Rule 7.1`
- All 422 unit tests pass, mypy clean

### BranchReceipt Audit Event — Design Phase
- Identified gap: current fork-join audit (ForkStarted/ForkCompleted/JoinCompleted) provides aggregate counts but not per-branch audit trail
- Designed new `BranchReceipt` frozen dataclass event — one per fork, capturing parent/final snapshot hashes, agent ID + policy, tools/files touched, claims delta, conflicts, join rule, merge decision, and outcome
- Design doc written to `docs/superpowers/specs/2026-05-18-branch-receipt-event-design.md`
- User approved design; pending implementation

### Changelog
- Updated `CHANGELOG.md` with v0.5.1 section covering test name fixes and BranchReceipt design

## 2026-05-17 (Pre-Phase 01)

### Adapter Fixes
- Made `LocalModelAdapter` non-frozen, removed `object.__setattr__` hack
- Fixed 4 mypy errors in `context_broker.py` (lambda Any expressions)
- Added `__all__` to `pipeline_rollback.py`
- Warn on text key collision in `agent_output_to_payload`
- Added `asyncio_default_fixture_loop_scope` to suppress deprecation warning

### Audit Phase Fixes
- Added `INDEX_NOT_FOUND` failure code test
- Multiple source fixes (F-13 through F-24) in audit module

### Phase 01 — SnapshotStore Protocol Extraction
- Created `SnapshotStore` Protocol in `snapshot_protocol.py`
- Renamed `SnapshotStore` → `LocalFileSnapshotStore`
- Created `InMemorySnapshotStore` for testing
- Wired `snapshot_store` field injection into `CoreRelayPipeline`
- Updated all consumers: `core_pipeline.py`, `pipeline_rollback.py`, `__init__.py`
- Made `Closeable` Protocol `@runtime_checkable`
- Added Protocol acceptance tests
- 16 exhaustive tests for `InMemorySnapshotStore`
- 5 pipeline wiring tests
