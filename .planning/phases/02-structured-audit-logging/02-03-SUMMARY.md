---
phase: 02-structured-audit-logging
plan: 03
subsystem: audit
tags: [fork, join, parallel, audit-events, core-pipeline]

requires:
  - phase: 02-structured-audit-logging
    provides: ForkStarted, ForkCompleted, JoinCompleted event types (02-01)
provides:
  - Parallel audit event emission in execute_parallel_step
affects: [02-04, operation-monitoring]

tech-stack:
  added: []
  patterns:
    - "Emit fork events inside transaction block for state consistency"
    - "Emit ForkCompleted before merge strategy dispatch (UNION/VOTE) or after (FIRST_WINS)"

key-files:
  created: []
  modified:
    - src/relay/core_pipeline.py — 3 audit event emissions in execute_parallel_step
    - tests/unit/test_audit_events.py — TestParallelAuditEvents class (4 tests)

key-decisions:
  - "ForkStarted emitted inside the transaction block (before fork_coros) to ensure state lock is held"
  - "ForkCompleted emitted at different points per strategy: for FIRST_WINS after apply_join_strategy (since forks_succeeded depends on merged_result status), for UNION/VOTE before apply_join_strategy (after collect/gather)"
  - "JoinCompleted only emitted when merged_result is a Success — if join fails, no join_completed event"

patterns-established:
  - "fork_completed event captured per-strategy: FIRST_WINS infers forks_succeeded (0 or 1) from merged result; UNION/VOTE counts actual successful results from collected fork results"

requirements-completed: [AUD-01]

duration: 8min
completed: 2026-05-18
---

# Phase 02 Plan 03: Parallel Audit Events Summary

**Emitted 3 parallel execution audit events (fork_started, fork_completed, join_completed) in execute_parallel_step with aggregate fork/join metadata**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-18T06:28:00Z
- **Completed:** 2026-05-18T06:36:00Z
- **Tasks:** 2 (1 production, 1 test)
- **Files modified:** 2

## Accomplishments
- `fork_started` emitted inside transaction block with `fork_count=len(fork_specs)` for accurate fork count capture
- `fork_completed` emitted from both FIRST_WINS path (after `merged_result`) and UNION/VOTE path (after `asyncio.gather` + before `apply_join_strategy`) with `forks_succeeded` count
- `join_completed` emitted after successful merge with `join_strategy.value` — skipped when merged_result is Failure
- All 3 parallel event types imported from `relay.audit`
- 4 new tests verifying event metadata fields (`fork_count`, `forks_succeeded`, `join_strategy`) and immutability

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire fork_started, fork_completed, join_completed in execute_parallel_step** - `6ebf57b` (feat)
2. **Task 2: Add TestParallelAuditEvents tests** - `29e19e8` (test)

**Plan metadata:** Pending (final commit)

## Files Created/Modified
- `src/relay/core_pipeline.py` — Added 3 event emissions + 3 imports in `execute_parallel_step`
- `tests/unit/test_audit_events.py` — Added `TestParallelAuditEvents` class (4 tests)

## Decisions Made
- **ForkStarted in transaction block:** Emitted inside the `with self._state.transaction()` block because `pre_fork_envelope` is only guaranteed available there, and holding the lock during emit prevents race conditions between fork_started event emission and state changes
- **ForkCompleted placement per strategy:** FIRST_WINS path computes `forks_succeeded` from `merged_result` (0 or 1), UNION/VOTE path computes it from actual `collected` results — each path emits at the point where the count becomes available
- **JoinCompleted only on success:** No event emitted when merge returns Failure, matching the semantic that the "join" didn't complete

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
- AST-based verification script in plan couldn't detect multi-line event constructor calls (ForkStarted, ForkCompleted are Name nodes, not Attribute nodes) — fixed by extending the AST visitor to check both `ast.Name` and `ast.Attribute` function references

## Stub Tracking

No stubs identified — both production code and tests have real, wired implementations.

## Threat Surface Scan

No new threat surface introduced. Parallel events carry only aggregate counts (fork_count, forks_succeeded) and join_strategy string — never per-fork payload content, consistent with the threat model's T-02-P03-01 mitigation plan.

## Next Phase Readiness
- All 3 parallel execution events emitted and tested
- Ready for 02-04 (SEC-12 + signature events)
