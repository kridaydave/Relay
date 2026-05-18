# Integration Architecture: Observability & Pluggable Storage

**Project:** Relay
**Researched:** 2026-05-17
**Mode:** Architecture analysis for v0.5 (observability) and v0.6 (pluggable backends) integration into existing 5-layer design.
**Overall confidence:** HIGH

---

## 1. Current Architecture Summary

Relay uses a strict **5-layer architecture** with one-directional dependency ordering:

```
types.py → envelope.py → snapshot.py → validator.py → context_broker.py
    → budget/ + slicer/ → pipeline_state.py → pipeline_rollback.py + parallel/
    → core_pipeline.py
```

Key constraints that any new feature must respect:
- **Lower layers never import upper layers** — circular imports are forbidden
- **`Result[T]` replaces exceptions** — every function returns `Success[T] | RollbackSuccess[T] | Failure`
- **`PipelineState.transaction()` is non-reentrant** — nested lock acquisition is a fatal programming error
- **All domain values are `@dataclass(frozen=True)`** — immutable data flow
- **Framework adapters are lazy-imported** — no hard third-party dependencies
- **Current logging** is stdlib `logging.getLogger(__name__)` in `snapshot.py` and `parallel/join.py` — no structured logging, no audit framework

---

## 2. Integration Strategy Overview

### Principle: Plumbing Layers, Not Adding Layers

The v0.5 and v0.6 features must NOT create new architectural layers. They are **cross-cutting concerns** that weave through existing layers via:

1. **Callback/hook injection** — components publish events at lifecycle points; the orchestrator listens and dispatches to sidecar components (audit, tracing)
2. **Protocol-based dependency inversion** — pluggable backends use `@runtime_checkable` Protocols, exactly like `TokenCounter`, `EmbeddingProvider`, and `AgentRunner` already do
3. **Lazy imports guarded by optional extras** — identical to the `_LAZY_ADAPTERS` pattern in `runners/__init__.py`

### Why Not New Layers?

| Approach | Problem |
|----------|---------|
| **Audit as Layer 6** | Audit needs to observe layers 1-5. A layer above can't observe below without violating layering. A layer below can't be inserted between all layers. |
| **OTEL as Layer 0** | OTEL spans need to wrap pipeline operations, not be called by them. Putting OTEL below all layers doesn't work — it needs access to domain objects from every layer. |
| **pluggable backends as Layer 5 replacement** | This works! SnapshotStore is already Layer 5 and can be extracted into a Protocol. |

**Decision:** Audit and OTEL are **observers**, not layers. Snapshot backends are a **within-layer extraction**. The pytest plugin is an **external consumer** (not a layer at all).

---

## 3. Structured Audit Logging

### Recommended Pattern: Sidecar Callback Dispatched by CoreRelayPipeline

```
┌──────────────────────────────────────────────────────┐
│                  CoreRelayPipeline                    │
│                                                       │
│  execute_step_with_manifest()                         │
│    ├─ _handle_initial_step()                          │
│    │   ├─ _check_budget()         ─→ emit BUDGET_CHECK │
│    │   ├─ create_initial_envelope()                   │
│    │   ├─ _apply_manifest()                           │
│    │   ├─ _snapshot_store.save()  ─→ emit SNAPSHOT    │
│    │   └─ emit STEP_COMPLETE                           │
│    │                                                  │
│    └─ _handle_subsequent_step()                       │
│        ├─ ...same pattern...                          │
│        └─ _finalize_step()                            │
│            ├─ validate_handoff()  ─→ emit VALIDATION   │
│            ├─ snapshot            ─→ emit SNAPSHOT     │
│            └─ emit STEP_COMPLETE  (or ROLLBACK)        │
│                                                       │
│  _emit_audit_event(event_type, data) ◄──── dispatch   │
│    ↓                                                  │
│  AuditLogger.log_event(event_type, data)               │
│    ↓                                                  │
│  [stdout] [file] [OTEL] [custom sink]                  │
└──────────────────────────────────────────────────────┘
```

### Architecture

**New module:** `src/relay/audit.py`

```python
"""Structured audit event logging for Relay.

Owns: audit event definitions, AuditLogger, AuditSink Protocol.
Does NOT: emit spans, manage pipeline state, or observe pipeline internals.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger("relay.audit")


class AuditSink(Protocol):
    """Protocol for audit event sinks."""
    def emit(self, event: "AuditEvent") -> None: ...


@dataclass(frozen=True)
class AuditEvent:
    """An immutable audit event record."""
    event_type: str
    pipeline_id: str
    step: int
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = field(default_factory=dict)
```

**Where audit events originate:** NOT in individual layers. The `CoreRelayPipeline` has a `_emit_audit_event()` method that is called at these lifecycle points:

| Lifecycle Point | Event Type | Data |
|-----------------|-----------|------|
| After `_check_budget()` passes | `budget.check` | `{manifest, token_budget_used, projected}` |
| After envelope creation | `envelope.created` | `{step, pipeline_id, manifest_hash}` |
| After handoff validation | `validator.result` | `{passed, contradiction_details, diff_summary}` |
| Before snapshot save | `snapshot.saving` | `{step, snapshot_id}` |
| After snapshot save | `snapshot.saved` | `{step, snapshot_id}` |
| After commit | `step.complete` | `{step, elapsed_ms}` |
| On rollback | `rollback.triggered` | `{from_step, to_step, reason}` |
| On adapter run start | `adapter.start` | `{adapter_name, agent_id}` |
| On adapter run complete | `adapter.complete` | `{adapter_name, agent_id, latency_ms, token_count}` |
| On pipeline creation | `pipeline.created` | `{pipeline_id, token_budget}` |
| On pipeline close | `pipeline.closed` | `{pipeline_id}` |

### Implementation Details

1. `AuditLogger` is constructed by `CoreRelayPipeline.__post_init__()` with a default `LoggingSink` (writes structured JSON to `relay.audit` logger)
2. The sink is pluggable via the `AuditSink` Protocol — users pass a custom sink to `CoreRelayPipeline.create(audit_sink=...)`
3. Events are fire-and-forget: sinks MUST NOT raise (caught by `try/except` and logged to `relay`)
4. The `relay.audit` logger uses standard Python logging — users wire it to any destination via `logging.config.dictConfig()`
5. Events use ISO 8601 timestamps, consistent with existing `ContextEnvelope.timestamp` format

### Why This Over Weaving Into Layers

| Approach | Verdict | Rationale |
|----------|---------|-----------|
| **Each layer emits its own audit events** | ❌ REJECTED | Violates layering: snapshot.py would import audit.py, but audit.py might need snapshot types. Tight coupling. |
| **Each layer takes an AuditLogger parameter** | ❌ REJECTED | Leaky abstraction. Makes every constructor signature more complex. Not all uses of a layer need audit. |
| **`CoreRelayPipeline` emits events from lifecycle methods** | ✅ SELECTED | Pipeline already orchestrates all layers. It knows when things happen. No coupling between layers and audit. |
| **Event hooks / callbacks registered by external code** | ⚠️ PARTIAL | The `AuditSink` Protocol provides this escape hatch. Default is LoggingSink. |

### Build Order Dependencies

1. Create `src/relay/audit.py` (new module, depends on `relay.types` only)
2. Add `AuditLogger` as field on `CoreRelayPipeline`
3. Inject `_emit_audit_event()` calls at lifecycle points in `core_pipeline.py`
4. Add `audit_sink` parameter to `CoreRelayPipeline.create()` factory
5. Tests: new `tests/unit/test_audit.py`

---

## 4. OpenTelemetry Integration

### Recommended Pattern: Lazy-Imported Tracer with NoOp Fallback

**CRITICAL CONSTRAINT:** OpenTelemetry MUST be optional. The `relay.opentelemetry` module must be importable without OTEL installed — it returns a NoOp tracer.

### Architecture

```
relay.opentelemetry                         # lazy-imported subpackage
├── __init__.py                             # exports: RelayTracer, get_tracer()
│   └── _LAZY_TRACER = "relay.opentelemetry.tracer"
│   └── __getattr__ lazy import
└── tracer.py                               # actual OTEL integration
```

### New Module Structure (subpackage)

**`src/relay/opentelemetry/__init__.py`** — follows exact same lazy-import pattern as `runners/__init__.py`:

```python
"""OpenTelemetry integration for Relay pipelines.

Owns: trace creation, span lifecycle, OTEL integration API.
Does NOT: define audit events, manage pipeline state, or import opentelemetry eagerly.

Import-safe: opentelemetry-api is lazy-imported. If not installed, get_tracer()
returns a NoOpRelayTracer that does nothing.
"""

_LAZY_TRACER = "relay.opentelemetry.tracer"

def __getattr__(name: str) -> object:
    if name == "RelayTracer":
        import importlib
        module = importlib.import_module(_LAZY_TRACER)
        tracer: object = getattr(module, "RelayTracer")
        setattr(sys.modules[__name__], "RelayTracer", tracer)
        return tracer
    raise AttributeError(...)
```

**`src/relay/opentelemetry/tracer.py`** — the actual OTEL integration:

```python
class RelayTracer:
    """Wrapper around OpenTelemetry tracer with NoOp fallback.
    
    Usage: relay_tracer = get_tracer(); span = relay_tracer.start_span(...)
    When opentelemetry-api is not installed, all methods are NoOp.
    """
    
    def __init__(self, service_name: str = "relay") -> None:
        self._tracer = self._try_get_tracer()  # NoOpTracer if not installed
    
    def start_span(self, name: str, ...) -> Span | None:
        return self._tracer.start_as_current_span(name, ...)
```

### Span Structure

**Per-step span hierarchy:**

```
pipeline.run                              # root span (if enabled)
├── step.1                                # each execute_step_with_manifest call
│   ├── budget.check                      # _check_budget sub-span
│   ├── envelope.create                   # create_next_envelope sub-span
│   ├── handoff.validate                  # HandoffValidator.validate_handoff sub-span
│   └── snapshot.save                     # SnapshotStore.save_snapshot sub-span
├── step.2
│   └── ...
├── step.3.parallel                       # execute_parallel_step
│   ├── fork.0                            # per-fork span
│   │   ├── adapter.run                   # framework adapter call
│   │   └── fork.validate                 # per-fork validation
│   ├── fork.1
│   │   └── ...
│   └── join                              # apply_join_strategy span
└── rollback (if triggered)               # single rollback span
```

**Span attributes:**

| Attribute | Example | Where Set |
|-----------|---------|-----------|
| `relay.pipeline_id` | `"abc123"` | Root span |
| `relay.step` | `3` | Per-step span |
| `relay.adapter` | `"langchain"` | Adapter spans |
| `relay.manifest.agent_id` | `"summariser"` | Per-step span |
| `relay.fork_id` | `"uuid"` | Fork spans |
| `relay.join_strategy` | `"UNION"` | Fork-join span |
| `relay.rolled_back` | `true` | Rollback span |
| `relay.token_budget_used` | `1840` | Per-step span |

### Integration into CoreRelayPipeline

```python
@dataclass
class CoreRelayPipeline:
    # Existing fields...
    _tracer: RelayTracer = field(init=False, repr=False)
    
    def __post_init__(self) -> None:
        # ...existing init...
        self._tracer = get_tracer()  # NoOpRelayTracer by default
    
    def execute_step_with_manifest(self, ...) -> Result[ContextEnvelope]:
        with self._tracer.start_span("pipeline.step") as span:
            span.set_attribute("relay.step", ...)
            # ...existing logic...
```

### Configuration

```python
# User code:
from relay.opentelemetry import configure_tracing
configure_tracing(endpoint="http://localhost:4317", service_name="my-app")

# Or environment variables (OTEL convention):
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# OTEL_SERVICE_NAME=my-app
```

### Build Order Dependencies

1. `opentelemetry-api` added as optional dependency (`[otel]` extra in `pyproject.toml`)
2. Create `src/relay/opentelemetry/` subpackage with lazy import pattern
3. Add `_tracer` to `CoreRelayPipeline.__post_init__()`
4. Weave `start_span()` calls at lifecycle boundaries in `core_pipeline.py`
5. Tests: `tests/unit/test_opentelemetry/` (with and without OTEL installed)
6. Integration test with `InMemorySpanExporter` verifying span structure

### What About OTEL Logging Integration?

The `relay.audit` logger (from Section 3) can be wired to OTLP via the standard `opentelemetry-instrumentation-logging` package or via the `OTLPLoggingHandler`. This is **user configuration**, not Relay's responsibility. Relay only provides:
1. Structured JSON output from `relay.audit`
2. OTEL spans from `relay.opentelemetry`
3. A bridging `OTelAuditSink` that converts audit events to span events/logs

---

## 5. CLI Inspector

### Recommended Pattern: Direct SnapshotStore Consumption via CLI Module

The CLI does NOT need `CoreRelayPipeline`. It operates directly on the snapshot store and envelope data, using public APIs only.

### Architecture

```
src/relay/cli/
├── __init__.py              # CLI entry points (click or argparse)
│   └── main()               # dispatch to subcommands
├── commands/
│   ├── list.py              # relay list <pipeline_id>
│   ├── show.py              # relay show <snapshot_id>
│   └── diff.py              # relay diff <pipeline_id> <from_step> <to_step>
```

**Entry point** registered in `pyproject.toml`:

```toml
[project.scripts]
relay = "relay.cli:main"
```

### Minimal Viable CLI (v0.5)

| Command | Implementation | Notes |
|---------|---------------|-------|
| `relay list <pipeline_id>` | `SnapshotStore.list_snapshots()` | Default storage path from env var `RELAY_STORAGE_PATH` or `./relay_data/snapshots` |
| `relay show <snapshot_id>` | `SnapshotStore.load_snapshot()` | Pretty-print envelope JSON |
| `relay diff <pipeline_id> <step_a> <step_b>` | Load both snapshots, compute `dict diff` | Requires adding `SnapshotStore.load_snapshot_by_step()` or using the index |
| `relay status <pipeline_id>` | `SnapshotStore.get_latest_snapshot()` | Show pipeline state summary |

**Deferred to future:**
| `relay rollback <pipeline_id> --to <step>` | Needs `CoreRelayPipeline` | Writes state — dangerous from CLI. Deferred until v0.5+. |

### Design Decisions

1. **CLI is a `pip install relay[cli]`** extra, with `click` or `argparse` (stdlib to avoid deps)
2. **Storage path** defaults to `RELAY_STORAGE_PATH` env var, then `./relay_data/snapshots`
3. **The CLI imports `SnapshotStore` directly** — no pipeline object needed
4. **`snapshot_id` format** is `pipeline_id@step_uuid` — the CLI accepts either full IDs or `pipeline_id:step` shorthand
5. **`diff` output** shows added/removed/changed keys in the payload, similar to `git diff --stat`

### How `relay diff` Works (New API on SnapshotStore)

```python
# Added to SnapshotStore (or as a standalone function):
def diff_snapshots(
    store: SnapshotStore,
    snapshot_a_id: str,
    snapshot_b_id: str,
) -> Result[dict[str, Any]]:
    """Compute structural diff between two snapshots.
    
    Returns a dict with 'added', 'removed', 'changed' keys.
    """
```

### Build Order Dependencies

1. Add `SnapshotStore.diff_snapshots()` or a standalone `diff_snapshots()` function
2. Create `src/relay/cli/` subpackage
3. Register CLI entry point in `pyproject.toml`
4. Tests: `tests/unit/test_cli/test_commands.py` (unit, not shell)

---

## 6. Pytest Plugin

### Recommended Pattern: Installable Plugin via pytest11 Entry Point

The plugin lives **inside** the Relay package (not a separate package) and registers via the `pytest11` entry point.

### Architecture

```
src/relay/
├── testing.py               # public testing utilities (assertion helpers)
└── pytest_plugin.py         # pytest-specific: fixtures registered via entry point
```

**Registration in `pyproject.toml`:**

```toml
[project.entry-points.pytest11]
relay = "relay.pytest_plugin"
```

### Fixtures Provided

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `relay_pipeline` | function | Creates an isolated in-memory `CoreRelayPipeline` (autouse: no) |
| `in_memory_snapshot_store` | function | Provides an `InMemorySnapshotStore` for direct assertions |

### Assertion Helpers (`relay.testing`)

```python
from relay.testing import assert_clean_handoff, assert_rolled_back, snapshot_at

def test_my_pipeline(relay_pipeline: CoreRelayPipeline) -> None:
    result = relay_pipeline.execute_step({"message": "hello"})
    assert_clean_handoff(result)
    
    snap = snapshot_at(relay_pipeline, step=1)
    assert snap.payload["message"] == "hello"
```

### Implementation Details

1. **`relay_pipeline` fixture** creates `CoreRelayPipeline.create()` with an `InMemorySnapshotStore`
2. **`InMemorySnapshotStore`** is a new class (in `src/relay/snapshot.py` or `src/relay/testing.py`) that implements the same public API as `SnapshotStore` but stores envelopes in a `dict[int, ContextEnvelope]`
3. **`assert_clean_handoff(result)`** = `assert isinstance(result, Success)`
4. **`assert_rolled_back(result)`** = `assert isinstance(result, RollbackSuccess)`
5. **`snapshot_at(pipeline, step)`** = reads from `InMemorySnapshotStore` at that step

### Why Not conftest Auto-Loading?

| Approach | Verdict | Rationale |
|----------|---------|-----------|
| **conftest.py in package root** | ❌ REJECTED | Would require users to copy a conftest.py. Binds to file hierarchy. |
| **autouse fixture in installed plugin** | ⚠️ PARTIAL | `relay_pipeline` is NOT autouse — too aggressive. But could have an autouse `_relay_cleanup` that resets state. |
| **Explicit fixture import via entry point** | ✅ SELECTED | Users `pip install relay[pytest]`, pytest auto-discovers via `pytest11` entry point. Fixtures are available by name in any test file. |

### Build Order Dependencies

1. Requires `InMemorySnapshotStore` (ties to v0.6 pluggable backend work — see Section 7)
2. Create `src/relay/testing.py` with assertion helpers
3. Create `src/relay/pytest_plugin.py` with fixture definitions
4. Register `pytest11` entry point in `pyproject.toml`
5. Add `[test]` extra in `pyproject.toml` (depends on `pytest`)
6. Tests: test the plugin's fixtures (`tests/unit/test_pytest_plugin.py`)

---

## 7. Pluggable Snapshot Backends

### Recommended Pattern: SnapshotStore Becomes a Protocol

The existing `SnapshotStore` (concrete class) becomes `LocalFileSnapshotStore`, and a new `SnapshotStore` Protocol defines the interface. This is **backward-compatible**: the `SnapshotStore` name in `__init__.py` exports is maintained.

### Protocol Definition

**Existing class renamed:**

```python
# src/relay/snapshot.py

@runtime_checkable
class SnapshotStore(Protocol):
    """Protocol for snapshot persistence backends.
    
    All methods are synchronous. Async backends should use
    asyncio.to_thread() or synchronous client libraries.
    """
    
    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]: ...
    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]: ...
    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]: ...
    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]: ...


class LocalFileSnapshotStore:
    """Default file-based snapshot store (renamed from SnapshotStore)."""
    # ... existing implementation ...
```

### Async vs Sync Decision

**Verdict: Keep sync-only.**

Rationale:
- Current `SnapshotStore.save_snapshot()` is called under `PipelineState.transaction()` (sync lock). Making it async would require releasing and re-acquiring the lock, which complicates correctness.
- Remote backends (Redis, Postgres, S3) have synchronous Python clients. `redis-py` is sync by default. `boto3` (S3) is sync. `psycopg2`/`psycopg3` are sync.
- If async is needed later, add a `AsyncSnapshotStore` Protocol and an adapter layer in `CoreRelayPipeline` that checks which interface is used.

```python
# Future async extension (not in v0.5/v0.6):
@runtime_checkable
class AsyncSnapshotStore(Protocol):
    async def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]: ...
    async def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]: ...
    async def list_snapshots(self, pipeline_id: str) -> Result[list[str]]: ...
    async def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]: ...
```

### Backend Implementations (v0.6)

| Backend | File | Dependency | Extra |
|---------|------|-----------|-------|
| `LocalFileSnapshotStore` | `snapshot.py` (exists) | stdlib only | `[core]` (default) |
| `InMemorySnapshotStore` | `snapshot.py` (new) | stdlib only | `[core]` (testing) |
| `RedisSnapshotStore` | `backends/redis_store.py` | `redis` | `[redis]` |
| `PostgresSnapshotStore` | `backends/postgres_store.py` | `psycopg` | `[postgres]` |
| `S3SnapshotStore` | `backends/s3_store.py` | `boto3` | `[s3]` |

### InMemorySnapshotStore (needed for pytest plugin in v0.5)

```python
class InMemorySnapshotStore:
    """Snapshot store that keeps envelopes in memory.
    
    Owns: in-memory envelope storage.
    Does NOT: persist to disk, validate snapshot IDs.
    """
    
    def __init__(self) -> None:
        self._snapshots: dict[str, ContextEnvelope] = {}
        self._pipeline_snapshots: dict[str, list[str]] = {}
    
    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        snapshot_id = f"{envelope.pipeline_id}@{envelope.step}_{uuid.uuid4().hex[:12]}"
        self._snapshots[snapshot_id] = envelope
        pipeline_id = envelope.pipeline_id
        if pipeline_id not in self._pipeline_snapshots:
            self._pipeline_snapshots[pipeline_id] = []
        self._pipeline_snapshots[pipeline_id].append(snapshot_id)
        return Success(snapshot_id)
    
    # ...load_snapshot, list_snapshots, get_latest_snapshot...
```

### Integration into CoreRelayPipeline

```python
@dataclass
class CoreRelayPipeline:
    storage_path: str = "./relay_data/snapshots"
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    
    def __post_init__(self) -> None:
        # SnapshotStore Protocol + concrete default
        if self.storage_path == ":memory:":
            self._snapshot_store = InMemorySnapshotStore()
        else:
            self._snapshot_store = LocalFileSnapshotStore(storage_path=self.storage_path)
```

Users can also inject a custom backend:

```python
# Future API in v0.6:
CoreRelayPipeline.create(
    signing_secret="...",
    snapshot_store=RedisSnapshotStore(host="..."),
)
```

### Build Order Dependencies

1. **v0.5 (pytest plugin needs this first):**
   - Add `SnapshotStore` Protocol to `snapshot.py`
   - Rename existing class to `LocalFileSnapshotStore`
   - Create `InMemorySnapshotStore`
   - Update `__init__.py` exports to include both `SnapshotStore` (Protocol) and `LocalFileSnapshotStore`

2. **v0.6 (additional backends):**
   - Create `src/relay/snapshot/backends/` subpackage
   - Add `RedisSnapshotStore`, `PostgresSnapshotStore`, `S3SnapshotStore`
   - Each backend is lazy-imported via the pattern in `runners/__init__.py`

---

## 8. Performance Gates

### Recommended Pattern: pytest-benchmark + CI Baseline

| Tool | Purpose | When |
|------|---------|------|
| `pytest-benchmark` | Microbenchmarks per component | Every CI run |
| `relay bench` CLI | End-to-end pipeline benchmarks | Pre-release validation |
| CI baseline comparison | Fail CI if regression > 15% | Every CI run |

### Microbenchmark Targets (pytest-benchmark)

```python
# tests/benchmarks/test_snapshot_benchmarks.py

def test_snapshot_serialization(benchmark) -> None:
    store = LocalFileSnapshotStore(tmp_path)
    envelope = make_test_envelope(large_payload=True)
    result = benchmark(store.save_snapshot, envelope)
    assert isinstance(result, Success)

def test_signature_computation(benchmark) -> None:
    envelope = make_test_envelope()
    benchmark(compute_signature, envelope, "secret-key-32-chars-long!!")
```

### Pipeline Benchmark Targets

The design doc specifies:
- **10-step sequential, 8K token budget:** < 50ms per step (excl. LLM call)
- **5-fork parallel merge + validate:** < 100ms (excl. LLM call)

These should be implemented as:

```bash
# CI gate command
relay bench --steps 10 --budget 8000 --runs 100
relay bench --parallel 5 --strategy union --runs 100
```

The `relay bench` CLI measures only Relay overhead (no actual LLM calls). It uses `FixedAgentRunner` (from test doubles) to simulate agent output.

### CI Integration

```yaml
# .github/workflows/benchmarks.yml (new)
- name: Run benchmarks
  run: pytest tests/benchmarks/ --benchmark-only --benchmark-json output.json

- name: Compare with baseline
  run: python scripts/check_benchmark_regression.py output.json
```

The comparison script loads a stored baseline and fails if any benchmark exceeds the threshold.

### Build Order Dependencies

1. Add `pytest-benchmark` as dev dependency
2. Create `tests/benchmarks/` directory
3. Add `relay bench` CLI command
4. Create CI benchmark workflow (separate from main CI — runs less frequently)

---

## 9. Complete File Map for v0.5 and v0.6

### New Files (v0.5 — Observability)

```
src/relay/audit.py                    # NEW: AuditEvent, AuditLogger, AuditSink Protocol
src/relay/testing.py                  # NEW: assert_clean_handoff, assert_rolled_back, snapshot_at
src/relay/pytest_plugin.py            # NEW: relay_pipeline fixture, pytest11 entry point
src/relay/opentelemetry/              # NEW: subpackage
  ├── __init__.py                     # lazy import (same pattern as runners/)
  └── tracer.py                       # RelayTracer with NoOp fallback
src/relay/cli/                        # NEW: subpackage
  ├── __init__.py                     # main() entry point
  └── commands/
      ├── list.py
      ├── show.py
      └── diff.py
tests/unit/test_audit.py             # NEW
tests/unit/test_testing.py           # NEW
tests/unit/test_pytest_plugin.py     # NEW
tests/unit/test_opentelemetry/       # NEW
tests/unit/test_cli/                 # NEW
tests/benchmarks/                    # NEW
```

### New Files (v0.6 — Pluggable Backends)

```
src/relay/snapshot.py                 # MODIFIED: SnapshotStore becomes Protocol, LocalFileSnapshotStore, InMemorySnapshotStore
src/relay/snapshot/backends/         # NEW: subpackage
  ├── __init__.py
  ├── redis_store.py                  # NEW
  ├── postgres_store.py               # NEW
  └── s3_store.py                     # NEW
tests/unit/test_snapshot_backends/   # NEW
```

### Modified Files

```
src/relay/core_pipeline.py           # MODIFIED: audit emission, tracer, pluggable snapshot_store
src/relay/__init__.py                # MODIFIED: new exports (AuditLogger, testing, etc.)
src/relay/types.py                   # MODIFIED: new ErrorCode entries for audit/CLI errors
pyproject.toml                       # MODIFIED: extras [otel], [cli], [test], [redis], [postgres], [s3]; pytest11 entry point
```

---

## 10. Dependency Graph Between Features

```
                    v0.5                     v0.5/v0.6 boundary
              ┌──────────────────┐    ┌─────────────────────────┐
              │  Structured Audit │    │  SnapshotStore Protocol  │
              │  (audit.py)       │    │  ←─ extraction from     │
              │  └─depends on:    │    │     SnapshotStore class  │
              │    relay.types    │    │  └─depends on:          │
              │    only           │    │    relay.envelope       │
              └────────┬─────────┘    └───────────┬─────────────┘
                       │                          │
                       │                          │
              ┌────────▼──────────────────────────▼─────────┐
              │         CoreRelayPipeline modifications      │
              │  - _emit_audit_event() calls                 │
              │  - _tracer start_span() calls               │
              │  - SnapshotStore Protocol injection          │
              └────────────────────┬────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
     ┌────────▼────────┐  ┌───────▼────────┐  ┌───────▼─────────┐
     │ CLI Inspector   │  │ Pytest Plugin  │  │ OTEL            │
     │ (cli/)          │  │ (pytest_plugin)│  │ (opentelemetry/)│
     │ └─depends on:   │  │ └─depends on:  │  │ └─depends on:   │
     │   SnapshotStore │  │  SnapshotStore │  │   opentelemetry-│
     │   (Protocol)    │  │  (Protocol)    │  │   api (optional)│
     │   click/argparse│  │  InMemoryStore │  │                 │
     └─────────────────┘  └────────────────┘  └─────────────────┘

                   v0.6 adds:
     ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
     │ RedisSnapshotStore│  │ PostgresStore    │  │ S3SnapshotStore  │
     │ └─depends on:     │  │ └─depends on:    │  │ └─depends on:    │
     │   SnapshotStore   │  │   SnapshotStore   │  │   SnapshotStore   │
     │   Protocol        │  │   Protocol        │  │   Protocol        │
     │   redis (opt.)    │  │   psycopg (opt.)  │  │   boto3 (opt.)    │
     └──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Build Order Recommendation

1. **SnapshotStore Protocol extraction** (v0.5 first, needed by everything else)
   - Create Protocol, rename existing to `LocalFileSnapshotStore`, add `InMemorySnapshotStore`
   - Update `CoreRelayPipeline` to accept `SnapshotStore`-compatible instances

2. **Pytest plugin** (v0.5 second, provides testing infrastructure)
   - Build on `InMemorySnapshotStore`
   - `relay.testing` assertion helpers

3. **Structured Audit** (v0.5 third)
   - `audit.py` depends only on `types.py`
   - `CoreRelayPipeline` calls `_emit_audit_event()` at lifecycle points

4. **OTEL integration** (v0.5 fourth)
   - `opentelemetry/` subpackage with lazy import
   - Tracer wired into `CoreRelayPipeline`

5. **CLI Inspector** (v0.5 fifth)
   - Depends on `SnapshotStore` Protocol (already done in step 1)
   - `relay list`, `relay show`, `relay diff`

6. **Performance gates** (v0.5 — parallel with items 3-5)
   - Independent of other features
   - Can be done anytime after base is stable

7. **Pluggable backends** (v0.6 — after v0.5 is stable)
   - Redis, Postgres, S3 implementations
   - Each is independent of the others
   - All depend on `SnapshotStore` Protocol

---

## 11. Specific Answers to Research Questions

### Q1: Structured Audit Logging — New layer, woven through, or callback?

**Answer: Callback/hook pattern dispatched by `CoreRelayPipeline`.**

The pipeline's lifecycle methods are the natural audit points. A dedicated `AuditLogger` component (in new `audit.py`) receives events from the pipeline. Individual layers NEVER emit audit events directly — this avoids coupling layers to audit infrastructure. The `AuditSink` Protocol allows plugging custom destinations (stdout, file, OTLP, Datadog, etc.).

### Q2: OpenTelemetry — Where should spans be created? Lazy-imported?

**Answer: Lazy-imported `RelayTracer` with NoOp fallback. Spans at method boundary level.**

`opentelemetry-api` is the optional dependency (NOT `opentelemetry-sdk` — users install that separately). The `relay.opentelemetry` subpackage uses the same lazy import pattern as `runners/__init__.py`. Spans wrap:
- `execute_step_with_manifest()` — per-step
- `execute_step_with_runner()` — adapter execution (child of step span)
- `execute_parallel_step()` — parallel span with per-fork children
- `_finalize_step()` — validation + snapshot sub-spans
- `rollback()` — single span
- Root span wraps the entire pipeline if user wraps calls in `tracer.start_as_current_span()`

### Q3: CLI Inspector — Direct SnapshotStore API or public API?

**Answer: Direct `SnapshotStore` API. CLI is a separate code path.**

The CLI imports and uses `SnapshotStore` (the Protocol) directly. It does NOT need `CoreRelayPipeline` — that would be overkill. `relay list`, `relay show`, `relay diff` are all read-only and safe. `relay rollback` is deferred (writes state, dangerous from CLI). The CLI adds a `diff_snapshots()` function to compute payload diffs.

### Q4: Pytest Plugin — conftest auto-loading or explicit imports?

**Answer: pytest11 entry point (explicitly available, not auto-applied to everything).**

The plugin registers via `[project.entry-points.pytest11]` in `pyproject.toml`. Fixtures are available by name (`relay_pipeline`, etc.) in any test file. No conftest.py needed. The `relay_pipeline` fixture is NOT autouse — users opt in by naming the fixture parameter. Assertion helpers live in `relay.testing` module for explicit imports.

**The in-memory pipeline** for tests uses `InMemorySnapshotStore` (needed by v0.5, delivered alongside the `SnapshotStore` Protocol extraction).

### Q5: Pluggable Backends — Protocol? Async vs Sync?

**Answer: `SnapshotStore` becomes `@runtime_checkable` Protocol. Sync-only. `LocalFileSnapshotStore` is the default.**

The Protocol is `sync` because:
- Snapshot I/O happens under `PipelineState.transaction()` (sync lock)
- Remote backends have synchronous Python clients (redis-py, boto3, psycopg2/3)
- Making snapshot methods async would require non-trivial lock re-architecture

If async demand arises in the future, an `AsyncSnapshotStore` Protocol can be added alongside and `CoreRelayPipeline` can detect which interface is used.

### Q6: Performance Gates — pytest-benchmark, custom scripts, CI gates?

**Answer: Combination: pytest-benchmark for microbenchmarks, `relay bench` CLI for pipeline benchmarks, CI baseline comparison.**

`pytest-benchmark` is the lightest-weight approach for per-component benchmarks (serialization, signing, validation). The `relay bench` CLI command benchmarks full pipeline scenarios. CI compares against a stored baseline and fails if regression exceeds 15%. Benchmark runs are a separate CI workflow (not every push — perhaps daily or pre-release).

---

## 12. Potential Pitfalls

| Pitfall | Mitigation |
|---------|-----------|
| **Audit events revealed the layering** | AuditLogger is a pipeline-owned component, not a layer. Events are emitted by the orchestrator, not individual layers. |
| **OTEL becomes a hard dependency** | The lazy import pattern (same as `runners/`) ensures `import relay` never requires OTEL. Only `import relay.opentelemetry` triggers the import, and it has a NoOp fallback. |
| **SnapshotStore Protocol extraction breaks backwards compatibility** | The `SnapshotStore` name in `__init__.py` exports the Protocol. `LocalFileSnapshotStore` is the concrete default. Existing code using `SnapshotStore` still works. |
| **CLI bypasses envelope validation** | The CLI loads snapshots via `SnapshotStore.load_snapshot()` which already validates JSON structure and envelope integrity (step matching, field validation). It does NOT modify state. |
| **pytest plugin adds global state** | Each `relay_pipeline` fixture creates a fresh `InMemorySnapshotStore`. No module-level state in the plugin. |
| **Async backends force sync callers into threads** | Sync-only Protocol avoids this. If async backends are needed later, the `AsyncSnapshotStore` Protocol and adapter logic in `CoreRelayPipeline` handles this transparently. |

---

*Architecture research: 2026-05-17. Confidence: HIGH (source analysis of existing codebase + established OTel/pytest/Protocol patterns).*
