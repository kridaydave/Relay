# Phase 2: Structured Audit Logging - Research

**Researched:** 2026-05-17
**Domain:** Structured audit logging with pluggable sinks, payload redaction, and per-step timing
**Confidence:** HIGH

## Summary

Phase 2 emits 17 typed, frozen dataclass audit events across 8 categories from the pipeline lifecycle into a pluggable `AuditSink` Protocol. The new module `src/relay/audit/` sits between `validator.py` and `context_broker.py` in the layer dependency chain — above the infrastructure that needs auditing (validators, signers) and below the orchestrators that emit events (core_pipeline, rollback, fork runner, join, budget enforcer).

SEC-12 (`max_age_seconds` on `verify_signature`) is already partially implemented — the parameter exists. Phase 2 adds the `signature_verification_stale` audit event, emitted by callers in `core_pipeline._apply_manifest()` and `snapshot.py` when the age check fails. No existing tests break; `verify_signature` return type stays `bool`.

The `AuditSink` Protocol follows the exact `@runtime_checkable(Closeable, Protocol)` pattern from `TokenCounter` and `SnapshotStore`. Default sink is JSON-formatted stdlib logging (same pattern as `logging.getLogger(__name__)` in `snapshot.py` and `join.py`). Audit emit is fire-and-forget — failures go to `logging.getLogger(__name__).error()`, pipeline continues.

No external packages are needed. Only stdlib: `logging`, `json`, `dataclasses`, `datetime`, `enum`, `typing`, `uuid`.

**Primary recommendation:** Four-file module (`__init__.py`, `events.py`, `sink.py`, `redactor.py`) + `ErrorCode.STALE_SIGNATURE` in `types.py` + integration points injected at the 17 lifecycle locations.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 17 event types across 8 categories
- **D-02:** Event naming in `snake_case`
- **D-03:** Event structure is a union of typed frozen dataclasses (one class per event type)
- **D-04:** Every event carries: `event_type`, `pipeline_id`, `step`, `outcome`, `latency_ms`, `timestamp` (ISO 8601), plus event-specific fields
- **D-05:** Events emitted synchronously (inline), not queued to a background thread
- **D-06:** `AuditSink.emit()` is fire-and-forget. On failure, error logged at ERROR level via `logging.getLogger(__name__)`. Pipeline continues.
- **D-07:** Redaction is a transform step applied at event construction time (not at sink time)
- **D-08:** Default-deny allowlist — only fields explicitly listed as safe are included
- **D-09:** No explicit timing instrumentation. ISO 8601 `timestamp` on every event. Duration computed at sink.
- **D-10:** `AuditSink` Protocol following `@runtime_checkable` pattern from `TokenCounter` and `SnapshotStore`
- **D-11:** Default sink: JSON-formatted stdlib `logging` sink
- **D-12:** `verify_signature()` gains `max_age_seconds: int = 86400` parameter. Returns `Failure` with new error code when envelope timestamp exceeds threshold.
- **D-13:** `signature_verification_stale` audit event emitted when max_age check triggers

### the agent's Discretion
- Exact error code for stale signature — use existing pattern from `ErrorCode` enum.
- `AuditSink` method signature detail (single `emit()` or also `flush()`/`close()`) — follow `Closeable` Protocol pattern.
- Payload redactor implementation details — must implement allowlist-safe transform at construction time.
- Integration call sites in `core_pipeline.py` — inject audit emit calls into the 17 lifecycle points.

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUD-01 | Emit structured audit events at key pipeline lifecycle points | 17 events across 8 categories mapped to exact integration points in Section: Integration Points |
| AUD-02 | Redact payload values from audit events by default (metadata only) | `PayloadRedactor` with default-deny allowlist; applied at event construction time (D-07, D-08) |
| AUD-03 | Support pluggable `AuditSink` Protocol with default JSON-logger sink | `AuditSink(Closeable, Protocol)` following `TokenCounter`/`SnapshotStore` pattern; `JsonLogSink` default |
| AUD-04 | Per-step timing data captured automatically via audit events | ISO 8601 `timestamp` on every event; `latency_ms` computed at sink (D-09) |
| SEC-12 | Enforce `max_age_seconds` on `verify_signature` calls (default 86400) | Parameter already exists; add `STALE_SIGNATURE` ErrorCode; emit audit event from callers |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event definition | Data model (`audit/events.py`) | — | Frozen dataclasses per AGENTS.md convention; no behavior, only shape |
| Event emission | Orchestration layer (core_pipeline, etc.) | — | Fire-and-forget at lifecycle points; D-05 mandates inline emission |
| Sink Protocol | Contract layer (`audit/sink.py`) | — | `@runtime_checkable` Protocol — same tier as `TokenCounter`, `SnapshotStore` |
| Default sink | Infrastructure (`audit/sink.py`) | — | JSON stdlib logging — no external dependencies, matches existing pattern |
| Payload redaction | Data transform (`audit/redactor.py`) | — | Applied at event construction time; isolates redaction logic from event definition |
| SEC-12 enforcement | Data integrity (`envelope.py`) | Audit event from callers | `verify_signature()` checks age; callers emit stale event |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib `logging` | built-in | Default audit sink format | Existing pattern in `snapshot.py:16` and `join.py:11` — zero deps |
| stdlib `json` | built-in | JSON serialization for log sink | `json.dumps` with `default=str` for dataclass serialization |
| stdlib `dataclasses` | built-in | All 17 event types as frozen dataclasses | Mandated per AGENTS.md: "Every domain value type is `@dataclass(frozen=True)`" |
| stdlib `datetime` | built-in | ISO 8601 timestamps with UTC offset | `datetime.now(timezone.utc).isoformat(timespec="seconds")` pattern |
| stdlib `enum` | built-in | `AuditOutcome` enum, `EventCategory` enum | Matches `ErrorCode(str, Enum)` pattern from `types.py:44` |
| stdlib `typing`/`Protocol` | built-in | `AuditSink` Protocol | Matches `TokenCounter` in `token_counter.py:14` and `SnapshotStore` in `snapshot_protocol.py:17` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AuditSink(Closeable, Protocol)` | `typing.Protocol` without `Closeable` | `Closeable` enables uniform cleanup pattern; consistent with `SnapshotStore` |
| Fire-and-forget emit | Return `Result[None]` on emit | Pipeline robustness trumps audit accuracy per D-06; `Result` would create error-handling complexity at every call site |
| ISO 8601 timestamps with sink-computed latency | Explicit start/end timestamps per event | D-09: simpler events; sink computes delta between consecutive events |

**Installation:**
No installation — only stdlib. Zero new dependencies.

**Version verification:** All libraries are stdlib/built-in — no registry verification needed for new packages. Zero external packages introduced by this phase.

## Package Legitimacy Audit

> This phase introduces **zero external packages**. All libraries used are Python stdlib: `logging`, `json`, `dataclasses`, `datetime`, `enum`, `typing`, `uuid`. No npm/PyPI registry verification needed.

| Package | Registry | slopcheck | Disposition |
|---------|----------|-----------|-------------|
| (stdlib only) | — | — | N/A — no external packages |

**Packages removed due to slopcheck [SLOP] verdict:** None
**Packages flagged as suspicious [SUS]:** None

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────┐
                          │   CoreRelayPipeline  │
                          │  (event emitter)     │
                          └──┬──────┬──────┬─────┘
                             │      │      │
               ┌─────────────┘      │      └─────────────┐
               ▼                    ▼                    ▼
     ┌─────────────────┐  ┌────────────────┐  ┌─────────────────┐
     │  PipelineRollback│  │  ForkRunner/   │  │  HardCapEnforcer│
     │  (rollback evts) │  │  Join (par evts)│  │  (budget evts)  │
     └────────┬────────┘  └───────┬────────┘  └────────┬────────┘
              │                   │                     │
              └───────────────┬───┴─────────────────────┘
                              ▼
                    ┌──────────────────┐
                    │  Audit Module    │
                    │  (audit/ events, │
                    │   sink, redactor)│
                    └────────┬─────────┘
                             │ emit(event)
                             ▼
                    ┌──────────────────┐
                    │   AuditSink      │  ← Protocol: pluggable
                    │   Protocol       │
                    └───────┬──────────┘
                            │
                    ┌───────┴──────────┐
                    │                  │
                    ▼                  ▼
            ┌──────────────┐  ┌──────────────┐
            │ JsonLogSink  │  │ TestSink     │
            │ (std default)│  │ (test double)│
            └──────────────┘  └──────────────┘

    Event flow: Lifecycle code → construct event →
    redact payload if needed → emit to sink →
    sink serializes/logs (fire-and-forget)
```

### Architectural Responsibility Map (detailed)

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event definitions | Data model (`audit/events.py`) | — | Frozen dataclasses per AGENTS.md convention |
| Event emission | Orchestration (core_pipeline, rollback, fork, join, enforcer) | — | Emitted inline at lifecycle points; orchestration has access to all required data |
| Sink Protocol | Contract (`audit/sink.py`) | — | `@runtime_checkable` — same pattern as `TokenCounter` |
| Default sink | Infrastructure (`audit/sink.py`) | — | JSON stdlib logging — zero deps, matches existing pattern in `snapshot.py` |
| Payload redaction | Data transform (`audit/redactor.py`) | — | Applied at event construction time; isolates redaction logic from event shape |
| SEC-12 stale detection | Data integrity (`envelope.py`) | Audit callers | `verify_signature()` checks age; callers emit event when false return is due to staleness |

### Layer Position

The `audit/` module sits after `validator.py` but before `context_broker.py`:

```
types.py → envelope.py → snapshot.py → validator.py → audit/
  → context_broker.py → budget/ + slicer/ → pipeline_state.py
  → pipeline_rollback.py + parallel/ → core_pipeline.py
```

This places `audit/` above all infrastructure it needs (types, envelope for datatypes) and below all consumers (core_pipeline, pipeline_rollback, parallel/, budget/enforcer).

**Justification:** 
- `audit/` imports from `types.py` (for `Closeable` Protocol, `Result`, `ErrorCode`)
- `audit/` imports from `envelope.py` (for `ContextEnvelope` type hints in events — the step execution events reference `envelope.step`, `envelope.pipeline_id`, etc.)
- `audit/` does NOT import from `core_pipeline.py`, `pipeline_rollback.py`, `parallel/`, or `budget/` — they import from it
- `core_pipeline.py`, `pipeline_rollback.py`, `fork_runner.py`, `join.py`, `enforcer.py` all consume events by calling `.emit()` — they import from `audit`

### Recommended Project Structure

```
src/relay/
├── audit/                          # NEW — structured audit logging
│   ├── __init__.py                 # Exports AuditSink, AuditEvent, JsonLogSink, PayloadRedactor, AuditOutcome
│   ├── events.py                   # 17 typed frozen dataclass events + AuditOutcome enum + EventCategory
│   ├── sink.py                     # AuditSink Protocol + JsonLogSink default impl
│   └── redactor.py                 # PayloadRedactor with default-deny allowlist
└── types.py                        # +STALE_SIGNATURE ErrorCode
```

Tests:
```
tests/unit/
├── test_audit_events.py            # Event construction, redaction, serialization
├── test_audit_sink.py              # AuditSink Protocol + JsonLogSink + TestSink
└── ...
tests/conftest.py                   # +FixedAuditSink test double
```

### Pattern 1: `AuditSink` Protocol (following `TokenCounter`/`SnapshotStore`)
**What:** A `@runtime_checkable` Protocol extending `Closeable` for pluggable audit sinks. Exactly matches established codebase pattern.

**When to use:** Any component that consumes audit events.

**Key design points:**
- `emit()` returns `None` (fire-and-forget per D-06)
- `close()` for cleanup (consistent with `Closeable` pattern)
- `@runtime_checkable` for `isinstance` checks in tests

```python
# Pattern source: relay/runners/protocol.py (AgentRunner), relay/budget/token_counter.py (TokenCounter)
# relay/snapshot_protocol.py (SnapshotStore extends Closeable, Protocol)

@runtime_checkable
class AuditSink(Closeable, Protocol):
    """Protocol for audit event sinks.

    Implementations write events to a destination (log file, stdout,
    test buffer, etc.). All emit calls are fire-and-forget — errors
    must not propagate to the caller.
    """

    def emit(self, event: AuditEvent) -> None:
        """Write an audit event.

        Args:
            event: The fully-constructed audit event to record.

        Must NOT raise exceptions. On failure, log via
        logging.getLogger(__name__).error() and return.
        """
        ...

    def close(self) -> None:
        """Release any resources held by this sink."""
        ...
```

### Pattern 2: `audit_sink` Optional Injection (following `token_counter`/`snapshot_store`)
**What:** `CoreRelayPipeline` accepts `audit_sink: AuditSink | None = None`. When `None`, constructs `JsonLogSink` as default.

**When to use:** All pluggable components follow this pattern.

```python
# Pattern source: core_pipeline.py:68-71 (token_counter, slice_packer, registry, snapshot_store)
from relay.audit import AuditSink, JsonLogSink

@dataclass
class CoreRelayPipeline:
    signing_secret: str = field(repr=False)
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"
    token_counter: TokenCounter | None = None
    slice_packer: SlicePacker | None = None
    registry: AdapterRegistry | None = None
    snapshot_store: SnapshotStore | None = None
    audit_sink: AuditSink | None = None               # NEW

def __post_init__(self) -> None:
    # ... existing setup ...
    if self.audit_sink is not None:
        self._audit_sink = self.audit_sink
    else:
        self._audit_sink = JsonLogSink()
```

### Pattern 3: Default-deny PayloadRedactor
**What:** A transform that takes raw pipeline data and returns only allowlisted-safe fields. Applied at event construction time.

**When to use:** Any event that carries payload-like data (step execution, budget, etc.).

```python
class PayloadRedactor:
    """Default-deny allowlist-based payload redactor.

    Only fields present in ALLOWED_FIELDS are passed through.
    All other fields are stripped. Applied at event construction time.
    """

    ALLOWED_FIELDS: frozenset[str] = frozenset({
        "adapter_name", "agent_name", "step", "pipeline_id",
        "token_count", "budget_used", "budget_limit",
        # Metadata only — no actual payload content
    })

    def redact_payload(self, payload: JSONDict) -> JSONDict:
        """Return only allowlisted fields from payload."""
        return {k: v for k, v in payload.items() if k in self.ALLOWED_FIELDS}

    def redact_envelope(self, envelope: ContextEnvelope) -> JSONDict:
        """Return redacted envelope data: only metadata, no payload content."""
        return {
            "pipeline_id": envelope.pipeline_id,
            "step": envelope.step,
            "token_budget_used": envelope.token_budget_used,
            "token_budget_total": envelope.token_budget_total,
        }
```

### Pattern 4: Event Construction + Emission Helper
**What:** A private method on `CoreRelayPipeline` that constructs an event and calls `self._audit_sink.emit(event)` — reducing boilerplate at 17 call sites.

```python
def _emit_audit_event(self, event: AuditEvent) -> None:
    """Construct and emit a redacted audit event.

    Fire-and-forget per D-06. Failures logged but not propagated.
    """
    self._audit_sink.emit(event)
```

### Anti-Patterns to Avoid
- **Not using `Closeable` on `AuditSink`**: Inconsistent with `SnapshotStore(Closeable, Protocol)`. Always extend `Closeable`.
- **Returning `Result[None]` from `emit()`**: Violates D-06 fire-and-forget. Pipeline must not handle audit failures.
- **Mutable event dataclasses**: Violates AGENTS.md strict frozen requirement. Use `@dataclass(frozen=True)`.
- **Passing raw payloads to events**: Violates D-07. Redact before constructing event.
- **Threading/queuing events**: Violates D-05. Emit inline synchronously.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Event serialization | Custom JSON encoder per event | `dataclasses.asdict()` + `json.dumps(default=str)` | dataclass fields serialize uniformly; `default=str` handles ISO datetimes |
| Test audit sink | Mock with complex assertions | `FixedAuditSink` (collects events in list) | Test double pattern from `FixedCounter` in `tests/conftest.py:6-22` |
| Circular import detection | Manual dependency tracking | Layer order in AGENTS.md | Audit sits after validator but before context_broker — verify against existing order |
| ISO 8601 timestamp formatting | Manual `strftime` | `datetime.now(timezone.utc).isoformat(timespec="seconds")` | Established pattern in `envelope.py:146` (`_canonical_timestamp`) |
| Signature age computation | Manual timedelta | `(datetime.now(timezone.utc) - envelope.timestamp).total_seconds()` | Established pattern in `envelope.py:201` |

**Key insight:** All patterns already exist in the codebase. This phase composes them — no novel infrastructure needed.

## Runtime State Inventory

> Not a rename/refactor/migration phase. Omitted.

## Common Pitfalls

### Pitfall 1: Circular imports from layer violation
**What goes wrong:** Putting `audit/` module at the wrong layer causes circular imports. If `audit/` imports from `envelope.py` for `ContextEnvelope` type hints, but `envelope.py` later imports from `audit/`, the dependency cycle breaks module loading.

**Why it happens:** AGENTS.md layer order is strict. `audit/` must stay below all consumers.

**How to avoid:** Place `audit/` after `validator.py` but before `context_broker.py`. Verify:
- `audit/` imports only from `types.py`, `envelope.py` (for ContextEnvelope type hints)
- `audit/` does NOT import from `context_broker`, `core_pipeline`, `pipeline_rollback`, `budget/`, `parallel/`

**Warning signs:** `ImportError` at module load time. Mypy `cannot import name X from partially initialized module`.

### Pitfall 2: Forgetting to redact payloads
**What goes wrong:** An event carries raw payload content (agent output, envelope payload) in an audit log, exposing data that should be metadata-only.

**Why it happens:** The 17 event types each have specific fields. Some (like `step_execution_succeeded`) need to know the payload size or adapter name but must NOT include the payload text.

**How to avoid:** `PayloadRedactor` is the single chokepoint. Only `PayloadRedactor.redact_envelope()` and `PayloadRedactor.redact_payload()` produce event-safe dicts. Never pass raw envelope.payload to an event.

**Warning signs:** An event field contains `payload`, `content`, `text`, or `output` in its event-specific fields.

### Pitfall 3: sync I/O blocking from logging
**What goes wrong:** The default `JsonLogSink` writes to stdlib `logging`, which can block on I/O (file write, network handler). Since audit is fire-and-forget, this blocking propagates to the pipeline thread.

**Why it happens:** stdlib `logging` handlers (FileHandler, SocketHandler) do blocking I/O.

**How to avoid:** Use `logging.Handler.emit()` which runs in the caller's thread. If perf is a concern, wrap handlers with `logging.handlers.QueueHandler` (future AUD-05). The success criteria don't require async audit.

### Pitfall 4: mypy --strict violations with Protocol unions
**What goes wrong:** The 17 event types are separate frozen dataclasses. The union type `AuditEvent` = `PipelineCreated | StepExecStarted | ...` (17 variants) can cause mypy exhaustiveness issues.

**Why it happens:** `AuditSink.emit(event: AuditEvent)` with a union parameter — mypy may require `assert_never` checks.

**How to avoid:** Use Python 3.12 `type` alias:
```python
type AuditEvent = (
    PipelineCreated
    | PipelineClosed
    | StepExecutionStarted
    | StepExecutionSucceeded
    | StepExecutionFailed
    | BudgetCheckPassed
    | BudgetCheckFailed
    | ValidationPassed
    | ValidationContradiction
    | RollbackTriggered
    | RollbackCompleted
    | ForkStarted
    | ForkCompleted
    | JoinCompleted
    | SnapshotSaved
    | SignatureVerificationPassed
    | SignatureVerificationStale
)
```
This is a mypy-compatible type alias (not `Union[...]`) in Python 3.12.

### Pitfall 5: Duplicating timestamp capture at every call site
**What goes wrong:** Every event emission call site needs to capture `datetime.now(timezone.utc)`. Duplicating this at 17+ call sites creates noise.

**How to avoid:** Capture timestamp once in the emission helper:
```python
def _emit_audit_event(self, event_builder: Callable[[str], AuditEvent]) -> None:
    """Capture timestamp, build event, emit."""
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ...
```

Or accept timestamp as a field in each event's constructor. Since events are frozen dataclasses, the constructor naturally captures fields.

## Code Examples

### Event type definitions (pattern for all 17)

```python
# Source: relay/types.py:44-78 (ErrorCode), relay/validator.py:35-43 (ValidationResult)
# Pattern: frozen dataclass with snake_case type discriminator field

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AuditOutcome(str, Enum):
    """Outcome of a pipeline operation."""
    SUCCESS = "success"
    FAILURE = "failure"
    ROLLBACK = "rollback"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelineCreated:
    """Emitted when a pipeline is created."""
    event_type: str = field(default="pipeline_created", init=False)
    pipeline_id: str
    step: int = 0
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    latency_ms: float = 0.0
    relay_version: str = ""
    storage_path: str = ""


@dataclass(frozen=True)
class StepExecutionStarted:
    """Emitted when a step begins execution."""
    event_type: str = field(default="step_execution_started", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    latency_ms: float = 0.0
    adapter_name: str = ""
    agent_name: str = ""
```

### AuditSink Protocol + JsonLogSink

```python
# Source: relay/budget/token_counter.py:13-24 (TokenCounter Protocol)
# Source: relay/snapshot_protocol.py:16-86 (SnapshotStore extends Closeable, Protocol)
# Source: snapshot.py:16 (logging.getLogger), join.py:11 (logging.getLogger)

import logging
import json
from typing import Protocol, runtime_checkable
from relay.types import Closeable

logger = logging.getLogger(__name__)


@runtime_checkable
class AuditSink(Closeable, Protocol):
    """Protocol for audit event sinks."""

    def emit(self, event: AuditEvent) -> None:
        """Write an audit event. Fire-and-forget per D-06."""
        ...

    def close(self) -> None:
        """Release any resources held by this sink."""
        ...


class JsonLogSink:
    """Default audit sink: JSON-formatted lines via stdlib logging.

    Formats each event as a single-line JSON object with ISO 8601
    timestamps. Uses json.dumps with default=str for dataclass fields.
    """

    def __init__(self, logger_name: str = "relay.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, event: AuditEvent) -> None:
        try:
            record = json.dumps(
                asdict(event), default=str, sort_keys=True
            )
            self._logger.info(record)
        except Exception:
            logger.error("Failed to serialize audit event: %s", type(event).__name__, exc_info=True)

    def close(self) -> None:
        pass
```

### SEC-12 integration in `verify_signature`

```python
# Source: envelope.py:184-205 (current verify_signature)
# No change to return type. Callers detect stale vs invalid.

# In core_pipeline.py _apply_manifest (line 364):
if not verify_signature(envelope, self._context_broker.signing_secret):
    # Check if stale — need max_age from somewhere
    age = (datetime.now(timezone.utc) - envelope.timestamp).total_seconds()
    if age > _MAX_AGE_SECONDS:
        self._audit_sink.emit(SignatureVerificationStale(
            pipeline_id=envelope.pipeline_id,
            step=envelope.step,
            envelope_age_seconds=age,
            max_age_seconds=_MAX_AGE_SECONDS,
        ))
    return Failure(
        reason="Cannot apply manifest to envelope with invalid signature",
        code=ErrorCode.INVALID_SNAPSHOT,
    )
```

### Integration point for `_handle_initial_step`

```python
# Source: core_pipeline.py:188-221 (_handle_initial_step)
# Add event emission at entry and exit

def _handle_initial_step(self, agent_output, manifest):
    # Emit: pipeline_created + step_execution_started
    self._emit_audit_event(PipelineCreated(
        pipeline_id=self._pipeline_id,
        relay_version=RELAY_VERSION,
        storage_path=self.storage_path,
    ))
    self._emit_audit_event(StepExecutionStarted(
        pipeline_id=self._pipeline_id,
        step=1,
        adapter_name="",
        agent_name=manifest.agent_id if manifest else "",
    ))

    budget_result = self._check_budget(manifest, None, agent_output)
    if isinstance(budget_result, Failure):
        self._emit_audit_event(BudgetCheckFailed(...))
        return budget_result
    self._emit_audit_event(BudgetCheckPassed(...))

    # ... rest of existing logic ...

    # On success:
    self._emit_audit_event(StepExecutionSucceeded(
        pipeline_id=self._pipeline_id,
        step=1,
        adapter_name="",
        agent_name=manifest.agent_id if manifest else "",
    ))
    return Success(new_envelope)
```

### Test double: `FixedAuditSink`

```python
# Source: tests/conftest.py:6-22 (FixedCounter)

@dataclass
class FixedAuditSink:
    """AuditSink that collects events for test assertions."""

    events: list[AuditEvent] = field(default_factory=list)

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass

    @property
    def emitted_types(self) -> list[str]:
        return [e.event_type for e in self.events]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No audit logging | Structured typed events via pluggable sinks | This phase | All pipeline operations become observable |
| `verify_signature` returns `bool` | Still returns `bool`; stale detected by callers | This phase | No API breakage; stale detection pattern documented |
| No payload redaction | Default-deny allowlist via PayloadRedactor | This phase | Payload content never leaks to audit logs |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `verify_signature` return type stays `bool` (not changed to `Result`) | SEC-12 Integration | Callers must duplicate age check logic; could refactor later |
| A2 | `audit/` sits after `validator.py` in layer order | Layer Position | If `audit/` needs something from `context_broker.py`, must re-evaluate position |
| A3 | `AuditSink` extends `Closeable` | Standard Stack | If sinks have no resources to release, `close()` is a no-op — harmless |
| A4 | `JsonLogSink` uses `json.dumps(asdict(event), default=str)` | Code Examples | `asdict()` may not handle nested dataclasses cleanly; test first |

## Open Questions (RESOLVED)

1. **How does `verify_signature` communicate stale vs. invalid to callers?** *(RESOLVED by Plan 04 Task 1)*
   - Resolution: `verify_signature()` return type changed from `bool` to `Result[None]`. Returns `Success(None)` for valid, `Failure(code=STALE_SIGNATURE)` for stale, `Failure(code=INVALID_SNAPSHOT)` for invalid. This matches D-12's requirement to return Failure with a new error code.
   - All 5 caller files updated to handle `Result[None]`: `core_pipeline.py`, `snapshot.py`, `test_envelope.py`, `test_parallel_pipeline.py`, `test_pipeline_integration.py`.

2. **What is the `max_age_seconds` value used by `core_pipeline._apply_manifest`?** *(RESOLVED by Plan 04 Task 1)*
   - Resolution: `max_signature_age: int = 86400` field added to `CoreRelayPipeline` @dataclass. `_apply_manifest` passes `self.max_signature_age` to `verify_signature()` and uses the same value for `signature_verification_stale` event emission.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All code | ✓ | 3.13.13 | — |
| stdlib `logging` | JsonLogSink | ✓ | built-in | — |
| stdlib `json` | JsonLogSink, serialization | ✓ | built-in | — |
| stdlib `dataclasses` | Event definitions | ✓ | built-in | — |
| stdlib `datetime` | Timestamps | ✓ | built-in | — |
| pytest | Tests | TBD | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | (pyproject.toml contains pytest config) |
| Quick run command | `pytest tests/unit/test_audit*.py -v` |
| Full suite command | `pytest tests/unit -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUD-01 | 17 events emitted at lifecycle points | unit | `pytest tests/unit/test_audit_*.py -x` | ❌ Wave 0 |
| AUD-01 | Empty pipeline emits pipeline_created + pipeline_closed | unit | `pytest tests/unit/test_audit_events.py -x` | ❌ Wave 0 |
| AUD-02 | PayloadRedactor strips non-allowlisted fields | unit | `pytest tests/unit/test_audit_redactor.py -x` | ❌ Wave 0 |
| AUD-02 | PayloadRedactor passes allowlisted fields | unit | as above | ❌ Wave 0 |
| AUD-03 | AuditSink Protocol is @runtime_checkable and extended Closeable | unit | `pytest tests/unit/test_audit_sink.py -x` | ❌ Wave 0 |
| AUD-03 | JsonLogSink formats events as JSON | unit | as above | ❌ Wave 0 |
| AUD-04 | ISO 8601 timestamps on every event | unit | `pytest tests/unit/test_audit_events.py -x` | ❌ Wave 0 |
| AUD-04 | Sink can compute latency between consecutive events | unit | `pytest tests/unit/test_audit_sink.py -x` | ❌ Wave 0 |
| SEC-12 | verify_signature with max_age creates stale event | unit | `pytest tests/unit/test_envelope.py -x` | ❌ Wave 0 |
| SEC-12 | STALE_SIGNATURE ErrorCode exists | unit | `pytest tests/unit/test_types.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_audit*.py -x` + mypy
- **Per wave merge:** Full `pytest tests/unit -v`
- **Phase gate:** Full suite green + `python -m mypy --strict src/relay` zero suppressions

### Wave 0 Gaps
- [ ] `tests/unit/test_audit_events.py` — covers AUD-01, AUD-04
- [ ] `tests/unit/test_audit_sink.py` — covers AUD-03, `FixedAuditSink` test double
- [ ] `tests/unit/test_audit_redactor.py` — covers AUD-02
- [ ] `tests/unit/test_types.py` — add `STALE_SIGNATURE` ErrorCode test (or add to `test_audit_events.py`)
- [ ] `tests/conftest.py` — add `FixedAuditSink` test double
- [ ] No new framework install needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Audit events constructed via typed dataclasses — type-safe by construction |
| V6 Cryptography | partial | SEC-12: `verify_signature` uses `hmac.compare_digest` (already established); stale signature detection |
| V7 Logging & Monitoring | yes (core to this phase) | All pipeline events structured-logged; fire-and-forget pattern; payload redaction |

### Known Threat Patterns for audit module

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Sensitive data in audit logs | Information Disclosure | Default-deny PayloadRedactor (D-07, D-08); only allowlisted metadata fields survive |
| Audit log injection | Tampering | `json.dumps` serialization; event types are fixed enums, not free-form strings |
| Stale envelope acceptance | Spoofing | `max_age_seconds` on `verify_signature`; `signature_verification_stale` event emitted when triggered |
| Sink failure masking pipeline errors | DoS | Fire-and-forget (D-06) — sink failure never affects pipeline outcome |

## Integration Points

### Exact integration points for all 17 events

| # | Event | File | Method/Line | When | Data Available |
|---|-------|------|-------------|------|----------------|
| 1 | `pipeline_created` | `core_pipeline.py` | `__post_init__()` ~line 116 | After state init, before first step | `pipeline_id`, `relay_version`, `storage_path` |
| 2 | `pipeline_closed` | `core_pipeline.py` | `close()` ~line 152 | Resource cleanup | `pipeline_id`, step count, total runtime |
| 3 | `step_execution_started` | `core_pipeline.py` | `_handle_initial_step()` ~line 188 OR `execute_step_with_manifest()` ~line 174 | At entry, before budget check | `pipeline_id`, `step`, adapter name |
| 4 | `step_execution_succeeded` | `core_pipeline.py` | After `_finalize_step()` returns Success ~line 341 | After snapshot save, state advance | `pipeline_id`, `step`, latency |
| 5 | `step_execution_failed` | `core_pipeline.py` | Before returning Failure from any step method | Budget failure, validation failure, etc. | `pipeline_id`, `step`, `error_code` |
| 6 | `budget_check_passed` | `core_pipeline.py` | `_check_budget()` ~line 289 after Success | After enforcer.check passes | `pipeline_id`, `step`, `budget_used`, `budget_limit` |
| 7 | `budget_check_failed` | `core_pipeline.py` | `_check_budget()` ~line 289 after Failure | After enforcer.check fails | `pipeline_id`, `step`, `budget_used`, `budget_limit` |
| 8 | `validation_passed` | `core_pipeline.py` | `_finalize_step()` ~line 320 after validate passes | After handoff validation passes | `pipeline_id`, `step`, `confidence_score` |
| 9 | `validation_contradiction` | `core_pipeline.py` | `_finalize_step()` ~line 326 when should_rollback | Before rollback trigger | `pipeline_id`, `step`, `contradiction_type`, `diff_summary` |
| 10 | `rollback_triggered` | `core_pipeline.py` | `_do_rollback()` ~line 375 OR `rollback()` ~line 429 | At rollback entry | `pipeline_id`, `step`, `reason` |
| 11 | `rollback_completed` | `core_pipeline.py` | After `_do_rollback()` returns ~line 406 | After restore_to_previous succeeds | `pipeline_id`, `restored_step`, `snapshot_id` |
| 12 | `fork_started` | `core_pipeline.py` | `execute_parallel_step()` ~line 558 before fork | Before concurrent execution | `pipeline_id`, `step`, `fork_count` |
| 13 | `fork_completed` | `core_pipeline.py` | `execute_parallel_step()` after gather ~line 582 | After all forks complete | `pipeline_id`, `step`, `forks_succeeded` |
| 14 | `join_completed` | `core_pipeline.py` | `execute_parallel_step()` after `apply_join_strategy` ~line 584 | After merge | `pipeline_id`, `step`, `join_strategy` |
| 15 | `snapshot_saved` | `core_pipeline.py` | `_finalize_step()` after save_snapshot ~line 335 | After successful snapshot save | `pipeline_id`, `step`, `snapshot_id`, `snapshot_size` |
| 16 | `signature_verification_passed` | `core_pipeline.py` | `_apply_manifest()` ~line 364 | After verify_signature returns True | `pipeline_id`, `step` |
| 17 | `signature_verification_stale` | `core_pipeline.py` | `_apply_manifest()` after verify_signature returns False for age reason | When max_age_seconds exceeded | `pipeline_id`, `step`, `envelope_age_seconds`, `max_age_seconds` |

### Event dependency chain (which modules consume which events)

| Consumer Module | Events It Emits |
|-----------------|----------------|
| `core_pipeline.py` | 1-17 (all) |
| `pipeline_rollback.py` | 10-11 (rollback_triggered, rollback_completed) — or emitted from core_pipeline which calls it |
| `fork_runner.py` | 12 (fork_started) — or emitted from core_pipeline |
| `join.py` | 13-14 (fork_completed, join_completed) — or emitted from core_pipeline |
| `budget/enforcer.py` | 6-7 (budget_check_passed, budget_check_failed) — or emitted from core_pipeline |

**Decision:** All events are emitted from `core_pipeline.py` which orchestrates the lifecycle. The sub-components (RollbackHandler, ForkRunner, etc.) don't have access to the audit_sink — they return data to core_pipeline, which handles event emission. This is simpler and avoids threading audit_sink through every component.

### How `audit_sink` flows through `CoreRelayPipeline.create()`

```python
# core_pipeline.py — create() factory
@classmethod
def create(
    cls,
    signing_secret: str,
    token_budget: int = 8000,
    storage_path: str = "./relay_data/snapshots",
    token_counter: TokenCounter | None = None,
    slice_packer: SlicePacker | None = None,
    registry: AdapterRegistry | None = None,
    snapshot_store: SnapshotStore | None = None,
    audit_sink: AuditSink | None = None,                         # NEW
) -> Result["CoreRelayPipeline"]:
    broker_result = create_context_broker(
        signing_secret=signing_secret, token_budget_total=token_budget
    )
    if isinstance(broker_result, Failure):
        return broker_result
    pipeline = cls(
        signing_secret=signing_secret,
        token_budget=token_budget,
        storage_path=storage_path,
        token_counter=token_counter,
        slice_packer=slice_packer,
        registry=registry,
        snapshot_store=snapshot_store,
        audit_sink=audit_sink,                                    # NEW
    )
    pipeline._context_broker = broker_result.value
    return Success(pipeline)
```

### `__post_init__` — construct default JsonLogSink

```python
# core_pipeline.py — __post_init__()
self._audit_sink: AuditSink
# ... in __post_init__:
if self.audit_sink is not None:
    self._audit_sink = self.audit_sink
else:
    self._audit_sink = JsonLogSink()
```

### `__init__.py` Export Changes

```python
# src/relay/__init__.py — add:
from relay.audit import AuditSink, AuditEvent, AuditOutcome, JsonLogSink

__all__ += [
    "AuditEvent",
    "AuditOutcome",
    "AuditSink",
    "JsonLogSink",
]
```

### `audit/__init__.py` — exports

```python
"""Structured audit logging for Relay pipeline lifecycle.

Owns: AuditSink Protocol, 17 typed event types, default JSON logging sink, payload redactor.
Does NOT: perform any pipeline logic, capture timing separately from ISO timestamps, or
         handle sink failures (fire-and-forget per D-06).
"""

from relay.audit.events import (
    AuditEvent,
    AuditOutcome,
    PipelineCreated,
    PipelineClosed,
    StepExecutionStarted,
    StepExecutionSucceeded,
    StepExecutionFailed,
    BudgetCheckPassed,
    BudgetCheckFailed,
    ValidationPassed,
    ValidationContradiction,
    RollbackTriggered,
    RollbackCompleted,
    ForkStarted,
    ForkCompleted,
    JoinCompleted,
    SnapshotSaved,
    SignatureVerificationPassed,
    SignatureVerificationStale,
)
from relay.audit.sink import AuditSink, JsonLogSink
from relay.audit.redactor import PayloadRedactor

__all__ = [
    "AuditEvent",
    "AuditOutcome",
    "AuditSink",
    "JsonLogSink",
    "PayloadRedactor",
    "PipelineCreated",
    "PipelineClosed",
    "StepExecutionStarted",
    "StepExecutionSucceeded",
    "StepExecutionFailed",
    "BudgetCheckPassed",
    "BudgetCheckFailed",
    "ValidationPassed",
    "ValidationContradiction",
    "RollbackTriggered",
    "RollbackCompleted",
    "ForkStarted",
    "ForkCompleted",
    "JoinCompleted",
    "SnapshotSaved",
    "SignatureVerificationPassed",
    "SignatureVerificationStale",
]
```

## Sources

### Primary (HIGH confidence)
- `src/relay/types.py` — `Closeable` Protocol, `ErrorCode` enum, `Result[T]` pattern
- `src/relay/budget/token_counter.py` — `TokenCounter` Protocol (`@runtime_checkable`)
- `src/relay/snapshot_protocol.py` — `SnapshotStore(Closeable, Protocol)` pattern
- `src/relay/runners/protocol.py` — `AgentRunner` Protocol pattern
- `src/relay/core_pipeline.py` — all 17+ integration points verified via source read
- `src/relay/envelope.py` — `verify_signature()` with existing `max_age_seconds` parameter (lines 184-205)
- `src/relay/snapshot.py` — `logging.getLogger(__name__)` pattern (line 16)
- `src/relay/parallel/join.py` — `logging.getLogger(__name__)` pattern (line 11)
- `src/relay/pipeline_rollback.py` — rollback lifecycle (lines 23-52)
- `src/relay/parallel/fork_runner.py` — fork execution (lines 24-123)
- `src/relay/parallel/join.py` — join strategies (lines 21-181)
- `src/relay/budget/enforcer.py` — budget check (lines 23-41)
- `AGENTS.md` — layer order, `@dataclass(frozen=True)` convention, mypy strict, test doubles
- `.planning/config.json` — `workflow.nyquist_validation: true` → include Validation Architecture section
- `tests/conftest.py` — `FixedCounter` test double pattern (lines 6-22)

### Secondary (MEDIUM confidence)
- `tests/unit/test_envelope.py` — existing SEC-12 tests validate `verify_signature(max_age_seconds=...)` behavior (lines 266-338)
- `src/relay/pipeline_state.py` — `transaction()` context manager pattern (lines 57-78)

### Tertiary (LOW confidence)
- None — all findings confirmed via primary source code reading

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — confirmed via source code reading; all stdlib, no new packages
- Architecture: HIGH — layer order confirmed in AGENTS.md; all integration points verified in source
- Pitfalls: HIGH — all issues derived from known codebase constraints (mypy strict, frozen dataclasses, layer order)
- SEC-12 integration: MEDIUM — D-12 says "returns Failure" but existing code returns `bool`. Minor tension to resolve in planning. Decision A1 documented in Assumptions Log.

**Research date:** 2026-05-17
**Valid until:** 2026-06-17 (stable — all patterns are stdlib and established codebase conventions)
