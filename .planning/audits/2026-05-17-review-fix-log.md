# Phase: Code Review Fix Report

**Fixed at:** 2026-05-17T15:00:00Z
**Source review:** REVIEW.md
**Iteration:** 2

**Summary (all iterations):**
- Total findings in scope: 12 (11 from review + 1 supplemental WR-05)
- Fixed: 9
- Skipped: 2
- Tests updated for compatibility: 3 files (test_budget.py, test_pipeline.py, test_autogen.py)

## Fixed Issues

### CR-01: Budget enforcement checks input slice cost against token budget, but accounting tracks only output size

**Files modified:** `src/relay/core_pipeline.py`
**Commit:** 523d478
**Applied fix:** Changed `_check_budget` to project output size based on `manifest.writes` (via `serialize_slice(dict[str, object]({s: "<output>" for s in manifest.writes}))`) instead of serializing the input payload via `_slice_payload`. This ensures the budget enforcement measures the same quantity as `token_budget_used` tracking (output size).

### CR-02: Per-agent max_tokens limit compared against input slice instead of output

**Files modified:** `src/relay/core_pipeline.py`
**Commit:** 523d478
**Applied fix:** The same `projected` variable now contains the output stub estimate (from the CR-01 fix), so the per-agent `max_tokens` check at line 275-284 now correctly compares against an output size projection rather than the input slice.

### WR-01: _finalize_step creates orphaned snapshot files on rollback

**Files modified:** `src/relay/core_pipeline.py`
**Commit:** 3f2ad0b
**Applied fix:** Removed the redundant `save_snapshot(current_envelope)` and `register_snapshot(...)` calls from both the `_finalize_step` rollback path and the `execute_parallel_step` rollback path. The envelope was already snapshotted when originally committed, so re-saving creates orphaned snapshot files.

### WR-02: _do_rollback fragile against RollbackHandler returning Success

**Files modified:** `src/relay/core_pipeline.py`
**Commit:** 77d5f90
**Applied fix:** Changed the type dispatch in `_do_rollback` from `isinstance(result, RollbackSuccess)` to `isinstance(result, Failure)`. This ensures that if a refactor ever introduces a `Success` return from `restore_to_previous`, the state mutation (`set_current`) is still reached rather than silently skipped.

### WR-03: apply_join_strategy type-unsafe for FIRST_WINS path

**Files modified:** `src/relay/parallel/join.py`
**Commit:** 10cf0ec
**Applied fix:** Added `@overload` decorators to `apply_join_strategy` to encode the constraint that `first_wins_coros` is required for FIRST_WINS but not for UNION/VOTE. Two overload signatures distinguish the cases at the type level.

### WR-04: AutoGenAdapter accepts unvalidated agent object

**Files modified:** `src/relay/runners/autogen.py`
**Commit:** 5394ec1
**Applied fix:** Added `__post_init__` method to `AutoGenAdapter` that validates the `agent` object has `initiate_chat` and `chat_messages` attributes at construction time, providing fail-fast feedback instead of a confusing `AttributeError` at call time.

### WR-05: delete_snapshot untested in InMemorySnapshotStore

**Files modified:** `tests/unit/test_snapshot_in_memory.py`
**Commit:** 6a64d26
**Applied fix:** Added `TestInMemorySnapshotStoreDelete` test class with 4 tests covering:
1. Happy path: save then delete, verify `Success` and that `list_snapshots` no longer includes the deleted snapshot.
2. Invalid snapshot ID returns `Failure` with `ErrorCode.INVALID_SNAPSHOT_ID`.
3. Non-existent snapshot returns `Failure` with `ErrorCode.SNAPSHOT_NOT_FOUND`.
4. After deleting the last snapshot, `list_snapshots` returns empty and `get_latest_snapshot` returns `NO_SNAPSHOTS`.

### IN-02: Duplicate token estimation logic across envelope.py and budget/token_counter.py

**Files modified:** `src/relay/envelope.py`
**Commit:** 905997f
**Applied fix:** Imported `HeuristicCounter` from `relay.budget.token_counter` and added a module-level `_ESTIMATOR` instance. Updated `estimate_tokens` to delegate to `_ESTIMATOR.count(json_str)`, eliminating the duplicated `max(1, len(text) // 3)` heuristic.

### IN-03: _load_index silently drops non-string keys from index

**Files modified:** `src/relay/snapshot.py`
**Commit:** 37151a4
**Applied fix:** Added an `else` branch in the `_load_index` key filter loop that calls `logger.warning("Non-string key '%s' dropped from index", k)` for dropped non-string keys.

### IN-04: HardCapEnforcer.check validates projected_cost < 0 (dead code)

**Files modified:** `src/relay/budget/enforcer.py`
**Commit:** 1b9b4ba
**Applied fix:** Removed the dead `projected_cost < 0` check and its associated `INVALID_TOKEN_COUNT` error return from `HardCapEnforcer.check`. Both `HeuristicCounter.count` (returns `max(1, len(text) // 3) >= 1`) and `_TiktokenCounter.count` (returns `len(enc.encode(text)) >= 0`) can never return negative.

## Skipped Issues

### IN-01: _finalize_step calls save_snapshot(rollback) with current_envelope which is not a new checkpoint

**File:** `src/relay/core_pipeline.py:309`
**Reason:** Already addressed by WR-01 fix (same root cause — redundant snapshot on rollback). This is a duplicate finding.

### IN-05: Typo: "persistence" → "persistence"

**File:** `src/relay/snapshot.py:2`
**Reason:** The source file at `snapshot.py:2` already reads `"""Snapshot persistence layer for Relay.` with the correct spelling "persistence". The review's claim of a typo appears mistaken — the actual code has the correct spelling.

## Supporting Changes

### Test updates

- **`tests/unit/test_budget.py`**: Removed `test_negative_count_returns_failure` — the dead code path it tested was removed in IN-04.
- **`tests/unit/test_pipeline.py`**: Updated `test_check_budget_returns_invalid_token_count` to verify successful budget check with valid projection (negative count path no longer exists). Removed `test_check_budget_fails_when_slice_packer_fails` — budget check no longer calls the slice packer.
- **`tests/unit/test_runners/test_autogen.py`**: Added `_MockAgent` class with the required `initiate_chat`/`chat_messages` attributes and replaced all `object()` mock agents with `_MockAgent()` instances. This supports the WR-04 `__post_init__` validation.

**Verification:**
- `mypy --strict src/relay`: 28 files, 0 issues
- `pytest tests/unit/`: 332 passed, 1 skipped (pre-existing benchmark skip)

---

_Fixed: 2026-05-17T15:00:00Z_
_Fixer: gsd-code-fixer_
_Iteration: 2_
