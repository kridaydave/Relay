# Phase 2: Structured Audit Logging - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Emit structured, redacted audit events from pipeline lifecycle with a pluggable `AuditSink` Protocol, payload redaction, per-step timing, and `max_age_seconds` enforcement on signature verification.

**Requirements:** AUD-01, AUD-02, AUD-03, AUD-04, SEC-12
**Success criteria:**
1. 17 audit events emitted at lifecycle points across 8 categories (pipeline lifecycle, step execution, budget, validation, rollback, parallel, snapshot, signature)
2. Payload values redacted by default via redaction transform with default-deny allowlist — only metadata in events
3. `AuditSink` Protocol with default JSON-formatted stdlib logging sink
4. Per-step timing via ISO timestamps on every event; duration computed at sink
5. `verify_signature` enforces `max_age_seconds` (default 86400) with stale-signature audit event

</domain>

<decisions>
## Implementation Decisions

### Audit Event Schema
- **D-01:** 17 event types across 8 categories: `pipeline_created`, `pipeline_closed`, `step_execution_started`, `step_execution_succeeded`, `step_execution_failed`, `budget_check_passed`, `budget_check_failed`, `validation_passed`, `validation_contradiction`, `rollback_triggered`, `rollback_completed`, `fork_started`, `fork_completed`, `join_completed`, `snapshot_saved`, `signature_verification_passed`, `signature_verification_stale`.
- **D-02:** Event naming in `snake_case` (e.g. `step_execution_succeeded`).
- **D-03:** Event structure is a union of typed frozen dataclasses (one class per event type), not a single generic event with optional fields.
- **D-04:** Every event carries: `event_type`, `pipeline_id`, `step`, `outcome` (one of: success/failure/rollback/skipped), `latency_ms`, `timestamp` (ISO 8601), plus event-specific fields (agent name, adapter type, snapshot ID, budget limits, fork details, etc.).
- **D-05:** Events emitted synchronously (inline), not queued to a background thread.

### Sink Failure Model
- **D-06:** `AuditSink.emit()` is fire-and-forget. On failure, the error is logged at ERROR level via `logging.getLogger(__name__)`. The pipeline step continues regardless — audit is observability, not control flow.

### Payload Redaction
- **D-07:** Redaction is a transform step applied at event construction time (not at sink time). A `PayloadRedactor` takes raw pipeline data and returns only allowlisted-safe fields.
- **D-08:** Default-deny allowlist — only fields explicitly listed as safe are included in audit events. No "redact by pattern" or blocklist approach.

### Timing Capture
- **D-09:** No explicit timing instrumentation. Every audit event carries an ISO 8601 `timestamp` field. Duration between events is computed at the sink or by log consumers.

### AuditSink Protocol
- **D-10:** `AuditSink` Protocol will be defined following the same pattern as `TokenCounter` and `SnapshotStore` (`@runtime_checkable`, dedicated file).
- **D-11:** Default sink: JSON-formatted stdlib `logging` sink, following existing pattern in `snapshot.py` and `join.py`.

### SEC-12: max_age_seconds
- **D-12:** `verify_signature()` in `src/relay/envelope.py` gains a `max_age_seconds: int = 86400` parameter. When the envelope timestamp exceeds this threshold, returns `Failure` with a new error code.
- **D-13:** A `signature_verification_stale` audit event is emitted when the max_age check triggers.

### the agent's Discretion
- Exact error code for stale signature — use existing pattern from `ErrorCode` enum.
- `AuditSink` method signature detail (single `emit()` or also `flush()`/`close()`) — follow `Closeable` Protocol pattern.
- Payload redactor implementation details — must implement allowlist-safe transform at construction time.
- Integration call sites in `core_pipeline.py` — inject audit emit calls into the 17 lifecycle points.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — AUD-01 through AUD-04, SEC-12 with full traceability

### Roadmap
- `.planning/ROADMAP.md` — Phase 2 goal, success criteria, mode (mvp)

### Source files (pipeline lifecycle — audit integration points)
- `src/relay/core_pipeline.py` — All lifecycle methods where audit events fire (create, execute_step, execute_step_with_manifest, execute_step_with_runner, execute_parallel_step, rollback)
- `src/relay/envelope.py` — `verify_signature()` for SEC-12 `max_age_seconds` integration
- `src/relay/pipeline_rollback.py` — Rollback lifecycle events
- `src/relay/parallel/fork_runner.py` — Fork execution events
- `src/relay/parallel/join.py` — Join completion events
- `src/relay/pipeline_state.py` — State transitions for audit context
- `src/relay/budget/enforcer.py` — Budget check events

### Patterns to follow
- `src/relay/snapshot.py` — Existing logging pattern (`logging.getLogger(__name__)`)
- `src/relay/runners/protocol.py` — `AgentRunner` Protocol pattern for `AuditSink`
- `src/relay/budget/token_counter.py` — `TokenCounter` Protocol pattern for optional injection
- `src/relay/types.py` — `ErrorCode` enum, `Result[T]` pattern, `Closeable` Protocol

### Prior phase context
- `docs/history/01-snapshotstore-protocol-extraction/01-CONTEXT.md` — Protocol patterns, optional injection convention

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`@runtime_checkable` Protocol pattern**: Established by `AgentRunner`, `TokenCounter`, `SnapshotStore`. `AuditSink` follows the same structure.
- **Optional injection with fallback**: `token_counter`, `slice_packer`, `registry`, `snapshot_store` all use `field: Type | None = None`, check in `__post_init__`, construct default if None. `audit_sink` follows same pattern.
- **Logging via stdlib `logging`**: `logging.getLogger(__name__)` in `snapshot.py` and `join.py` — default `AuditSink` uses same approach with JSON formatting.

### Established Patterns
- **`Result[T]` for all fallible operations**: However, audit emit is fire-and-forget (D-06) — `AuditSink.emit()` returns `None`, not `Result`.
- **Module docstrings**: Three-line format (summary, Owns, Does NOT) required for new `audit` module.
- **Explicit `__all__`**: Every public module exports via `__all__`.
- **Layer dependency**: Audit module must sit below `core_pipeline.py` and above `types.py` in the dependency chain. Likely position: after `validator.py`, before `context_broker.py` in the layer order.

### Integration Points
- `CoreRelayPipeline.execute_step()` (core_pipeline.py:153-155) — emit started/succeeded/failed
- `CoreRelayPipeline.execute_step_with_runner()` (core_pipeline.py:429-487) — emit fork_started/fork_completed
- `CoreRelayPipeline.execute_parallel_step()` (core_pipeline.py:489-629) — emit join_completed
- `CoreRelayPipeline.rollback()` (core_pipeline.py:414-422) — emit rollback_triggered/completed
- `CoreRelayPipeline._check_budget()` (core_pipeline.py:237-286) — emit budget_check_passed/failed
- `RollbackHandler.restore_to_previous()` — rollback completion events
- `HardCapEnforcer.check()` — budget check results
- `envelope.py verify_signature()` — SEC-12 max_age_seconds parameter + stale signature event

### File Organization
- New module: `src/relay/audit/` directory with:
  - `src/relay/audit/__init__.py` — exports `AuditSink`, `AuditEvent`, default sink
  - `src/relay/audit/events.py` — All 17 typed event dataclasses
  - `src/relay/audit/sink.py` — `AuditSink` Protocol + `JsonLogSink` default implementation
  - `src/relay/audit/redactor.py` — `PayloadRedactor` transform (default-deny allowlist)

</code_context>

<specifics>
## Specific Ideas

### Event Categories (approved concrete list)

| Category | Events |
|----------|--------|
| Pipeline lifecycle | `pipeline_created`, `pipeline_closed` |
| Step execution | `step_execution_started`, `step_execution_succeeded`, `step_execution_failed` |
| Budget enforcement | `budget_check_passed`, `budget_check_failed` |
| Handoff validation | `validation_passed`, `validation_contradiction` |
| Rollback | `rollback_triggered`, `rollback_completed` |
| Parallel execution | `fork_started`, `fork_completed`, `join_completed` |
| Snapshot | `snapshot_saved` |
| Signature (SEC-12) | `signature_verification_passed`, `signature_verification_stale` |

### Common event fields
- `event_type: str` — snake_case identifier
- `pipeline_id: str`
- `step: int`
- `outcome: AuditOutcome` — enum: SUCCESS, FAILURE, ROLLBACK, SKIPPED
- `timestamp: str` — ISO 8601
- `latency_ms: float` — computed at sink from timestamps

### Per-category specific fields
- Pipeline: `relay_version`, `storage_path`
- Step execution: `adapter_name`, `agent_name`, `error_code` (on failure)
- Budget: `budget_used`, `budget_limit`
- Validation: `contradiction_type`, `diff_summary`
- Rollback: `restored_step`, `snapshot_id`
- Parallel: `fork_count`, `join_strategy`, `per_fork_results` (adapter_name + outcome per fork)
- Snapshot: `snapshot_id`, `snapshot_size_bytes`
- Signature: `envelope_age_seconds`, `max_age_seconds`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Structured Audit Logging*
*Context gathered: 2026-05-17*

