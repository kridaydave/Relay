---
phase: 02-structured-audit-logging
plan: 01
subsystem: audit
tags: [audit, logging, events, protocol, redaction, json]

requires:
  - phase: 01-snapshotstore-protocol-extraction
    provides: Closeable Protocol, Protocol injection patterns, test double convention

provides:
  - Audit module (audit/events.py, sink.py, redactor.py, __init__.py) with 17 typed event types
  - AuditSink Protocol extending Closeable with fire-and-forget emit()
  - JsonLogSink default implementation via stdlib JSON logging
  - PayloadRedactor with default-deny allowlist
  - FixedAuditSink test double in conftest.py
  - audit_sink integration in CoreRelayPipeline (optional, JsonLogSink default)
  - pipeline_created and pipeline_closed lifecycle events

affects:
  - Phase 2 plans (02-02 through 02-04): will add remaining 15 events at lifecycle points

tech-stack:
  added: [none — all stdlib]
  patterns:
    - AuditSink(Closeable, Protocol) following SnapshotStore/TokenCounter pattern
    - Fire-and-forget emit() — errors caught and logged, never propagated
    - Default-deny PayloadRedactor with frozenset allowlist
    - _emit_audit_event helper on CoreRelayPipeline

key-files:
  created:
    - src/relay/audit/events.py — 17 frozen dataclass event types + AuditOutcome enum + AuditEvent union type
    - src/relay/audit/sink.py — AuditSink Protocol, JsonLogSink default implementation
    - src/relay/audit/redactor.py — PayloadRedactor with default-deny frozenset allowlist
    - src/relay/audit/__init__.py — module exports with __all__
    - tests/unit/test_audit_events.py — 28 tests for event types
    - tests/unit/test_audit_sink.py — 12 tests for Protocol compliance and sink behavior
    - tests/unit/test_audit_redactor.py — 6 tests for redaction logic
  modified:
    - src/relay/core_pipeline.py — audit_sink field, _emit_audit_event helper, pipeline_created/pipeline_closed
    - src/relay/__init__.py — audit type exports (AuditSink, AuditEvent, AuditOutcome, JsonLogSink)
    - tests/conftest.py — FixedAuditSink test double

key-decisions:
  - "Used cast(JSONDict, vars(event)) for event serialization instead of asdict() to satisfy mypy --strict (asdict returns dict[str, Any])"
  - "Implemented _event_to_json_dict helper abandoned due to dataclasses.fields() also containing Any; cast(JSONDict, vars(event)) is the minimal strict-mode-safe pattern"
  - "AuditSink.emit() returns None (fire-and-forget), not Result — ensures pipeline never blocks on audit failures per D-06"

patterns-established:
  - "AuditSink Protocol: @runtime_checkable, extends Closeable, emit() returns None"
  - "Default-deny redaction: PayloadRedactor.ALLOWED_FIELDS frozenset as single chokepoint"
  - "Pipeline event emission: _emit_audit_event() helper, no import leakage at call sites"
  - "Test double: FixedAuditSink with events list and emitted_types property"

requirements-completed: [AUD-01, AUD-03]

duration: 13min
completed: 2026-05-18
---

# Phase 2 Plan 1: Structured Audit Core Module Summary

**17 typed audit event types with AuditSink Protocol, JsonLogSink default, PayloadRedactor, and pipeline lifecycle events wired into CoreRelayPipeline**

## Performance

- **Duration:** 13 min
- **Started:** 2026-05-18T11:26:16Z
- **Completed:** 2026-05-18T11:39:16Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Created `relay.audit` package with 4 files: events, sink, redactor, and `__init__`
- Defined 17 typed frozen dataclass events across 8 categories (pipeline lifecycle, step, budget, validation, rollback, parallel, snapshot, signature)
- `AuditSink` Protocol extends `Closeable` and is `@runtime_checkable` — same pattern as `SnapshotStore` and `TokenCounter`
- `JsonLogSink` serializes events to JSON via stdlib logging with fire-and-forget on failure
- `PayloadRedactor` with default-deny frozenset allowlist for safe event construction
- `audit_sink` optional injection in `CoreRelayPipeline` (defaults to `JsonLogSink`)
- `pipeline_created` emitted on construction, `pipeline_closed` on close()
- `FixedAuditSink` test double in `tests/conftest.py`
- All 46 unit tests passing, mypy --strict zero suppressions on all modified code

## Task Commits

Each task was committed atomically:

1. **Task 1: Create audit module with all 17 event types, Protocol, sinks, and redactor** - `40a5e22` (feat)
2. **Task 2: Wire audit_sink into CoreRelayPipeline and add pipeline_created/pipeline_closed events** - `99ad4d5` (feat)
3. **Task 3: Write unit tests for audit events, sink, redactor, and FixedAuditSink integration** - `7ac0328` (test)

## Files Created/Modified

### Created
- `src/relay/audit/events.py` - 17 frozen dataclass events + AuditOutcome enum + AuditEvent type alias (267 lines)
- `src/relay/audit/sink.py` - AuditSink Protocol, JsonLogSink default implementation (74 lines)
- `src/relay/audit/redactor.py` - PayloadRedactor default-deny allowlist redactor (63 lines)
- `src/relay/audit/__init__.py` - Module exports with explicit __all__ (52 lines)
- `tests/unit/test_audit_events.py` - 28 tests for event types (224 lines)
- `tests/unit/test_audit_sink.py` - 12 tests for Protocol compliance + sink behavior (112 lines)
- `tests/unit/test_audit_redactor.py` - 6 tests for redaction logic (75 lines)

### Modified
- `src/relay/core_pipeline.py` - audit_sink field, _emit_audit_event helper, pipeline_created/pipeline_closed
- `src/relay/__init__.py` - Added audit exports (AuditSink, AuditEvent, AuditOutcome, JsonLogSink)
- `tests/conftest.py` - Added FixedAuditSink test double

## Decisions Made

- **Event serialization approach:** Used `cast(JSONDict, vars(event))` instead of `asdict()` because `dataclasses.asdict()` returns `dict[str, Any]` which violates mypy `--strict`'s `disallow_any_expr` check. `cast` overrides the type without suppression.
- **AuditSink Protocol placement:** Defined in `sink.py` alongside `JsonLogSink` (single-responsibility grouping), matching the `TokenCounter`/`HeuristicCounter` pattern in `budget/token_counter.py`.
- **Fire-and-forget emit:** `AuditSink.emit()` returns `None`, not `Result`, ensuring pipeline never blocks on audit failures per decision D-06.
- **Layer position:** `audit/` module sits after `validator.py` and before `context_broker.py` in the dependency chain — imports only from `types.py` and `envelope.py` (under TYPE_CHECKING in redactor).

## Deviations from Plan

None - plan executed exactly as written.

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed mypy strict error with asdict() returning dict[str, Any]**
- **Found during:** Task 1 (creating sink.py)
- **Issue:** `dataclasses.asdict()` returns `dict[str, Any]` which triggers mypy `--strict` error `Expression type contains "Any" (has type "dict[str, Any]")`. Also tried `dataclasses.fields()` which also fails due to `Field[Any]` type.
- **Fix:** Replaced `asdict(event)` with `cast(JSONDict, vars(event))` — `vars()` returns the dataclass instance's `__dict__`, and `cast` satisfies mypy strict by overriding the expression type to `JSONDict` (`dict[str, object]`) without `# type: ignore`.
- **Files modified:** `src/relay/audit/sink.py`
- **Verification:** mypy passes clean on sink.py
- **Committed in:** `40a5e22` (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed RuntimeError in close() accessing _state.current() without lock**
- **Found during:** Task 2 verification (testing pipeline lifecycle events)
- **Issue:** `close()` called `self._state.current()` which requires holding the pipeline lock via `transaction()` context manager. Raised `RuntimeError: Lock must be held via transaction() context manager`.
- **Fix:** Wrapped the `current_step` extraction in a `with self._state.transaction() as envelope:` context manager, capturing the step if an envelope exists, defaulting to 0.
- **Files modified:** `src/relay/core_pipeline.py`
- **Verification:** Pipeline close now works correctly without RuntimeError
- **Committed in:** `99ad4d5` (Task 2 commit)

**3. [Rule 3 - Blocking] Fixed mypy strict error with untyped event list in test**
- **Found during:** Task 3 verification (running mypy on test files)
- **Issue:** `test_all_events_have_timestamp` used an untyped list of heterogeneous event types. mypy inferred `list[object]`, causing `error: "object" has no attribute "timestamp"`.
- **Fix:** Added explicit `list[AuditEvent]` type annotation to the events list variable.
- **Files modified:** `tests/unit/test_audit_events.py`
- **Verification:** mypy passes clean on all test files
- **Committed in:** `7ac0328` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 3 - Blocking)
**Impact on plan:** All fixes were necessary to satisfy project constraints (mypy --strict, pipeline lock discipline). No scope creep.

## Issues Encountered

- **`dataclasses.asdict()` vs mypy --strict:** The `asdict()` function returns `dict[str, Any]`, which fails mypy's `disallow_any_expr` check in strict mode. Solution: `cast(JSONDict, vars(event))` is the minimal strict-mode-safe approach that produces equivalent output.
- **Pipeline lock discipline:** `close()` needs to read the current step for the `pipeline_closed` event, but `_state.current()` requires the lock to be held. Fixed by wrapping access in a `transaction()` context manager.

## Threat Surface Scan

No new threat surface introduced beyond what the plan's `<threat_model>` captured. All threat mitigations verified:
- T-02-P01-01 (Information Disclosure): PayloadRedactor default-deny allowlist — tests confirm non-allowlisted fields stripped
- T-02-P01-02 (Tampering): Fire-and-forget emit (D-06) — errors caught and logged, never propagate
- T-02-P01-03 (Spoofing): pipeline_id comes from validated pipeline source, not user input

## Next Phase Readiness

- Core audit module complete with all 17 event types defined
- AuditSink Protocol ready for consumption by future plans
- Pipeline lifecycle events (pipeline_created, pipeline_closed) wired and firing
- Ready for Phase 2 Plan 2 (step/budget/validation/rollback/snapshot event integration)
- Ready for Phase 2 Plan 3 (parallel execution events: fork/join)
- Ready for Phase 2 Plan 4 (SEC-12 signature verification event)
- No blockers for subsequent plans

---

*Phase: 02-structured-audit-logging*
*Completed: 2026-05-18*
