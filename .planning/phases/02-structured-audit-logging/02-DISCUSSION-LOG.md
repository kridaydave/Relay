# Phase 2: Structured Audit Logging - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-17
**Phase:** 2-Structured Audit Logging
**Areas discussed:** Audit event schema & lifecycle points, Sink failure model, Payload redaction approach, Timing capture pattern, SEC-12: max_age_seconds

---

## Audit Event Schema & Lifecycle Points

| Option | Description | Selected |
|--------|-------------|----------|
| Core flow events | Pipeline created, step start/success/failure, rollback triggered/done. ~6 events. | |
| Core + enforcement events | Above + budget pass/fail, validation pass/fail/contradiction. ~10 events. | |
| Full coverage | Above + parallel: fork start/done, join done, snapshot saved, signature events. ~14+ events. | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal (metadata only) | event type, pipeline ID, step, outcome, latency | |
| Rich metadata | Above + agent name, adapter type, snapshot ID, event-specific data | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| snake_case | pipeline_created, step_execution_succeeded | ✓ |
| Dotted hierarchy | pipeline.step.completed, pipeline.budget.exceeded | |

| Option | Description | Selected |
|--------|-------------|----------|
| Inline (synchronous) | Emit immediately. Simple, matches logging pattern. | ✓ |
| Background queue | Queue to thread that processes batches. Won't slow pipeline. | |

| Option | Description | Selected |
|--------|-------------|----------|
| Single dataclass + optional fields | One AuditEvent with optional event_specific_data | |
| Union of typed events | PipelineCreated, StepSucceeded, etc — all frozen dataclasses | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Simple: success / failure | Two values matches Result pattern | |
| Four values | success / failure / rollback / skipped | ✓ |

**User's choice:** Full coverage — 17 events across 8 categories, rich metadata, snake_case naming, inline synchronous emit, union of typed events, four outcome values.

**Concrete event list:** pipeline_created, pipeline_closed, step_execution_started, step_execution_succeeded, step_execution_failed, budget_check_passed, budget_check_failed, validation_passed, validation_contradiction, rollback_triggered, rollback_completed, fork_started, fork_completed, join_completed, snapshot_saved, signature_verification_passed, signature_verification_stale. Approved.

---

## Sink Failure Model

| Option | Description | Selected |
|--------|-------------|----------|
| Fire-and-forget (silent) | Sink error silently logged, pipeline continues | |
| Reliable (Result) | emit() returns Result, pipeline can fail step on sink error | |
| Buffered with retry | Events queued, retry on failure, drop oldest if full | |

**User's choice:** "Throw a big error and continue" — ERROR-level log, pipeline proceeds.

---

## Payload Redaction Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Schema-level (no payload fields) | AuditEvent types never carry payload content | |
| Redaction transform | Events can reference payload; redactor strips before emit | ✓ |
| Pattern substitution | List of field patterns to redact. Most dynamic. | |

| Option | Description | Selected |
|--------|-------------|----------|
| Default-deny (allowlist) | Only explicitly safe fields kept | ✓ |
| Default-allow (blocklist) | Specify fields to strip by pattern | |

| Option | Description | Selected |
|--------|-------------|----------|
| At event construction | Event never carries raw payload | ✓ |
| At sink emit | Event carries raw payload, sink calls redactor | |

**User's choice:** Redaction transform, default-deny allowlist, applied at event construction time.

---

## Timing Capture Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Timer context manager | with timer('name'): wraps the code | |
| Manual time.monotonic() calls | Explicit start/stop at each audit point | |
| Timestamp-only (compute at sink) | Each event has a timestamp; duration = current - previous | ✓ |

**User's choice:** Timestamp-only, duration computed at sink.

---

## SEC-12: max_age_seconds

| Option | Description | Selected |
|--------|-------------|----------|
| Simple parameter + audit event | Add max_age_seconds to verify_signature(), emit stale event | ✓ |
| Let the agent decide | Use judgment for implementation | |

**User's choice:** Simple parameter on verify_signature() + stale-signature audit event.

---

## the agent's Discretion

- Exact error code for stale signature
- AuditSink method signature detail (emit only or also flush/close)
- Payload redactor implementation details
- Integration call sites in core_pipeline.py

## Deferred Ideas

None — discussion stayed within phase scope.
