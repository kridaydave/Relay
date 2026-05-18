---
phase: 02-structured-audit-logging
plan: 02
subsystem: audit
tags: [audit, logging, events, core_pipeline, step_execution, budget, validation, rollback, snapshot]

requires:
  - phase: 02-structured-audit-logging
    plan: 01
    provides: 17 typed audit event types, AuditSink Protocol, _emit_audit_event helper, FixedAuditSink test double

provides:
  - Step execution events (started/succeeded/failed) emitted from execute_step_with_manifest and execute_step_with_runner
  - Budget check events (passed/failed) emitted from _check_budget
  - Handoff validation events (passed/contradiction) emitted from _finalize_step
  - Rollback events (triggered/completed) emitted from _do_rollback
  - Snapshot saved event emitted from _finalize_step after save_snapshot succeeds
  - 12 audit event types wired into 5 core_pipeline methods
  - Event type string verification test for all 17 event types

affects:
  - Phase 2 Plan 3 (parallel events): fork/join event integration pattern
  - Phase 2 Plan 4 (SEC-12 + signature): signature verification events

tech-stack:
  added: [none — all stdlib]
  patterns:
    - Event emission at the caller level (execute_step_with_manifest wraps step handlers)
    - Budget events emitted inline at failure/pass points inside _check_budget
    - Validation events emitted at the appropriate phase of _finalize_step
    - Rollback events emitted at trigger point and after successful restore

key-files:
  modified:
    - src/relay/core_pipeline.py — 10 audit event types emitted from 5 lifecycle methods
    - tests/unit/test_audit_events.py — 32 tests including lifecycle construction and event_type validation

key-decisions:
  - "Step execution events emitted from execute_step_with_manifest (caller level) rather than from individual step handlers — keeps emission at a single abstraction level"
  - "StepExecutionStarted emitted separately in both execute_step_with_manifest and execute_step_with_runner — runner provides richer adapter context at a different abstraction level"
  - "RollbackTriggered emitted in _do_rollback (not rollback()) — catches all rollback paths (manual and automatic)"
  - "StepExecutionFailed emitted for both Failure (with error_code) and RollbackSuccess (with ROLLBACK code) outcomes"

patterns-established:
  - "Caller-level emission: execute_step_with_manifest wraps _handle_initial_step/_handle_subsequent_step and emits started/succeeded/failed based on their result"
  - "Budget event scope: _check_budget emits BudgetCheckPassed only when budget enforcement was actually triggered"
  - "Rollback event dual emission: RollbackTriggered before restore, RollbackCompleted after successful restore"

requirements-completed: [AUD-01, AUD-02, AUD-04]

duration: 8min
completed: 2026-05-18
---

# Phase 2 Plan 2: Step/Budget/Validation/Rollback/Snapshot Event Integration Summary

**10 audit events wired into 5 core_pipeline methods: step execution (started/succeeded/failed), budget enforcement (passed/failed), handoff validation (passed/contradiction), rollback (triggered/completed), and snapshot saved — with event_type string tests for all 17 types**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-18T11:44:37Z
- **Completed:** 2026-05-18T11:52:56Z
- **Tasks:** 3 (plus 1 mypy fix)
- **Files modified:** 2

## Accomplishments

- **Step execution events**: `StepExecutionStarted` emitted from `execute_step_with_manifest` (initial + subsequent branches) and `execute_step_with_runner`. `StepExecutionSucceeded`/`StepExecutionFailed` emitted based on the result of each step execution, with error_code from Failure.code or "ROLLBACK" for RollbackSuccess outcomes.
- **Budget events**: `BudgetCheckPassed`/`BudgetCheckFailed` emitted from `_check_budget` — covers enforcer-level checks and per-agent max_tokens violations. Uses `_audit_budget_triggered` flag to only emit BudgetCheckPassed when budget enforcement was actually engaged.
- **Validation events**: `ValidationPassed` emitted after handoff validation succeeds (no Failure, no rollback). `ValidationContradiction` emitted before the RollbackSuccess return in the contradiction path.
- **Snapshot events**: `SnapshotSaved` emitted from `_finalize_step` after `save_snapshot` succeeds — carries `snapshot_id` from the save result.
- **Rollback events**: `RollbackTriggered` emitted at the start of `_do_rollback` (after guard checks). `RollbackCompleted` emitted after `restore_to_previous` succeeds, before state mutation.
- **Event type string tests**: Added `test_all_events_have_event_type_string` validating snake_case event_type for all 17 types, plus 3 new construction tests for adapter/agent fields, contradiction diff_summary, and snapshot_id/size.
- **mypy --strict**: Zero suppressions on all modified code (fixed `current_envelope` None type via assertion).

## Task Commits

Each task was committed atomically:

1. **Task 1: Emit step execution and budget events** - `f06e265` (feat)
2. **Task 2: Emit validation, rollback, and snapshot events** - `2c63f18` (feat)
3. **Task 3: Integration tests for all wired lifecycle events** - `68635cb` (test)
4. **Mypy fix: None assertion in execute_step_with_runner** - `8aae6bf` (fix)

## Files Created/Modified

### Modified
- `src/relay/core_pipeline.py` — 180 lines added: 12 audit event types imported, step execution/budget/validation/rollback/snapshot events emitted from 5 lifecycle methods
- `tests/unit/test_audit_events.py` — 57 lines added: 4 new tests for event field coverage and event_type string validation

## Decisions Made

- **Caller-level emission pattern**: Step execution events are emitted from `execute_step_with_manifest` (the caller wrapping `_handle_initial_step` and `_handle_subsequent_step`), not from within the step handlers themselves. This keeps emission at a single abstraction level and avoids duplicating event logic across multiple handler functions.
- **Separate runner-level StepExecutionStarted**: `execute_step_with_runner` emits its own `StepExecutionStarted` with full adapter context (adapter_name, agent_name). The inner `execute_step_with_manifest` call also emits `StepExecutionStarted` at a different detail level. This provides richer context for runner-originated steps.
- **RollbackTriggered in _do_rollback path**: Placed in `_do_rollback` (not the public `rollback()`) to catch all rollback paths — both manual calls from `rollback()` and automatic rollbacks triggered by validation contradictions.
- **StepExecutionFailed for RollbackSuccess**: When a step results in a rollback, `StepExecutionFailed` is emitted with `error_code="ROLLBACK"` to signal the external caller that the step did not succeed normally.

## Deviations from Plan

None - plan executed as written. Fixed one mypy `--strict` union-attr error during verification.

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added None assertion for current_envelope in execute_step_with_runner**
- **Found during:** Plan-level verification (mypy --strict)
- **Issue:** `current_envelope` from `self._state.transaction()` is typed as `ContextEnvelope | None`, so accessing `.step` triggers `union-attr` error.
- **Fix:** Added `assert current_envelope is not None` before the step computation. This is a safe assertion — `execute_step_with_runner` requires a prior step to exist.
- **Files modified:** `src/relay/core_pipeline.py`
- **Verification:** `python -m mypy --strict src/relay/core_pipeline.py` passes with zero errors
- **Committed in:** `8aae6bf`

---

**Total deviations:** 1 auto-fixed (Rule 3 - Blocking)
**Impact on plan:** Necessary for mypy --strict compliance. No scope creep.

## Issues Encountered

None.

## Threat Surface Scan

No new threat surface introduced. The events constructed in this plan carry only metadata (pipeline_id, step, adapter_name, agent_name, error_code) — never raw payload content. Threat register mitigations:
- T-02-P02-01: Only adapter_name, agent_name, error_code passed in step execution events — no payload content.
- T-02-P02-02: diff_summary is empty string in ValidationContradiction (contradiction_details from validator used as contradiction_type).
- T-02-P02-03: Event metadata comes from validated pipeline state parameters.
- T-02-P02-04: BudgetCheckFailed emits budget_used/budget_limit from pipeline config values.

## Next Phase Readiness

- All sequential pipeline operations now observable via audit events (step, budget, validation, rollback, snapshot)
- Ready for Phase 2 Plan 3 (parallel execution events: fork_started, fork_completed, join_completed)
- Ready for Phase 2 Plan 4 (SEC-12 signature verification events)
- 50 audit module tests passing, mypy --strict zero suppressions on core_pipeline.py

---

*Phase: 02-structured-audit-logging*
*Completed: 2026-05-18*
