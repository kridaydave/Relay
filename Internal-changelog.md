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
- Full report at `docs/audits/2026-05-17-full-codebase-review.md`

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

### BranchReceipt Audit Event — Implementation
- **Design phase**: Identified gap, designed `BranchReceipt` frozen dataclass event, wrote design doc to `docs/superpowers/specs/2026-05-18-branch-receipt-event-design.md`, user approved
- **Task 1** (commit `0260996`): Added `BranchReceipt` dataclass to `events.py` with 22 fields, added to `AuditEvent` union + `__all__`, 4 construction tests. Code review fix in `01557e6`.
- **Task 2** (commit `d0841e1`): `_apply_first_wins` returns `tuple[Result[JSONDict], list[ForkResult]]`. `apply_join_strategy` public signature unchanged.
- **Task 3** (commit `9628159`): `execute_parallel_step` emits one `BranchReceipt` per fork after all forks complete. FIRST_WINS runs all forks (no early cancellation). Added `BranchReceipt` export to `relay/audit/__init__.py`. All 426 tests pass, mypy clean.
- **Task 4 fixes** (commit `734622c`): Added `isinstance(join_strategy, JoinStrategy)` early validation in `execute_parallel_step`. Fixed FIRST_WINS integration timing test for all-forks-run behavior. 454 tests pass, mypy clean.
- Implementation plan at `docs/superpowers/plans/2026-05-18-branch-receipt-event.md`
- Public changelog v0.5.1 updated with full implementation details

### Integration Test Fixes
- `test_parallel_step_with_invalid_join_strategy_returns_failure` — added early validation in `execute_parallel_step` (before `.value` access) to return `Failure(INVALID_JOIN_STRATEGY)` for raw strings
- `test_first_wins_commits_envelope_before_slow_fork_completes` → `test_first_wins_commits_envelope_after_all_forks_complete` — timing assertion changed from `< 1.0` to `>= 2.0`

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
