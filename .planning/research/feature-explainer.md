# Feature Landscape — v0.5 & v0.6 Relay

**Domain:** LLM agent context-passing middleware observability + persistence
**Researched:** 2026-05-17

## Table Stakes (for an observability story in 2026)

Features that any serious middleware library must have. Missing these = not production-ready.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Structured JSON audit log** | Users need to pipe events to Datadog/Loki/Splunk without writing custom parsers | LOW | Each event is a typed, structured record. Sink is pluggable. |
| **Per-step timing data** | Users need to know how long each pipeline step takes (excl. LLM call) | LOW | Captured as part of audit events. No separate instrumentation needed. |
| **Snapshot inspection** | Users need to verify what's persisted without writing code | LOW | CLI `relay show` and `relay list` commands. |
| **Snapshot diff** | Users need to see what changed between steps | MEDIUM | CLI `relay diff` command. Requires comparing two envelopes' payloads. |
| **Test fixture for pipeline** | Users need to write tests that exercise pipeline logic | MEDIUM | `relay_pipeline` pytest fixture with in-memory storage. |
| **Rollback verification** | Users need assertions that rollback was triggered | LOW | `assert_rolled_back()` helper. |

## Differentiators

Features that set Relay apart from alternatives (custom scripts, LangGraph, etc.).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **OTEL trace per step** | Users can correlate pipeline steps with LLM calls, DB queries, and other infrastructure in their existing OTEL dashboard | MEDIUM | Each step → trace span. Parallel forks → child spans. Adapters → child spans of fork spans. |
| **Sync-only snapshot Protocol** | Simpler than async alternatives. No lock re-architecture needed. | LOW | Async backend Protocol can be added later if demand materializes. |
| **In-memory snapshot store** | Zero-config pytest integration. No temp directories, no cleanup. | LOW | Used by the pytest plugin. Also useful for users who don't need persistence. |
| **Pluggable storage without async** | Redis, Postgres, and S3 backends all use sync clients. Consistent with Relay's existing sync-lock architecture. | MEDIUM | Each backend is 1-2 files with 3-4 methods. Tests need the actual service (Docker Compose for CI). |
| **No-op OTEL tracer when not installed** | Zero overhead for users who don't use OTEL. No configuration needed. | LOW | Same pattern as every OTEL library instrumentation. |
| **CLI reads same store as library** | No separate API or protocol. Point CLI at the storage path and it works. | LOW | Reuses SnapshotStore Protocol. |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Built-in OTEL exporter** | Relay is middleware, not an observability pipeline. Users already have OTEL collectors configured. | Bundle `opentelemetry-api` only. Users bring their own SDK/exporter/collector. |
| **Web dashboard/UI** | Completely out of scope. Relay's design doc says "A UI or dashboard" is explicitly out of scope for v1.0. | CLI + OTEL integration. Users can build dashboards on collected data. |
| **CLI rollback command** | Modifying snapshot state from a separate code path is dangerous. Could cause pipeline state corruption. | Users write recovery scripts. Or add `relay rollback` only as a `--force` flag in a later version. |
| **Async SnapshotStore Protocol** | Premature. Current lock architecture is sync. Async would require non-reentrant lock redesign or `asyncio.Lock`. | Add `AsyncSnapshotStore` Protocol only when a concrete async backend request arrives. |
| **Metrics (counters, histograms)** | OTEL metrics signal is still stabilizing. Audit events already capture event counts. Can be converted to metrics downstream. | Users configure OTEL SDK to derive metrics from spans/events. |
| **Automatic conftest.py discovery** | Forces coupling between file hierarchy and test configuration. Users who have complex conftest structures would conflict. | pytest11 entry point registration. Users opt-in via fixture parameter name. |

## Feature Dependencies

```
SnapshotStore Protocol extraction (v0.5 step 1)
  ├── InMemorySnapshotStore (needed for pytest plugin)
  │   └── Pytest plugin fixtures (relay_pipeline, assert_clean_handoff, etc.)
  │       └── Testing docs and examples
  ├── CLI inspector (relay list, show, diff)
  │   ├── SnapshotStore.diff_snapshots() (new method needed)
  │   └── relay-diff command
  └── Pluggable backends (v0.6)
      ├── RedisSnapshotStore
      ├── PostgresSnapshotStore
      └── S3SnapshotStore

Audit logging (v0.5 step 2, independent of SnapshotStore)
  ├── AuditLogger + AuditSink Protocol
  └── CoreRelayPipeline lifecycle hook integration

OTEL integration (v0.5 step 4, independent)
  ├── RelayTracer with NoOp fallback
  └── CoreRelayPipeline span injection

Performance gates (v0.5 parallel, independent)
  ├── pytest-benchmark microbenchmarks
  └── CI baseline comparison
```

## MVP Recommendation for v0.5

Prioritize:
1. **SnapshotStore Protocol + InMemorySnapshotStore** — unlocks everything else
2. **Structured audit logging** — highest user-facing value ("what is my pipeline doing?")
3. **pytest plugin** — highest developer-facing value ("how do I test my pipeline?")
4. **OTEL integration** — differentiator
5. **CLI inspector** — nice-to-have, can slip to v0.5.x

Defer:
- **Pluggable backends** (Redis, Postgres, S3): v0.6 feature
- **CLI rollback**: too risky for v0.5
- **Metrics export**: let OTEL ecosystem handle this

## Sources

- Relay Design Document: `docs/Relay Design Document.md` (Sections 9-10)
- Existing codebase analysis: `src/relay/` — patterns proven in `runners/__init__.py`, `budget/`, `slicer/`
- OTEL Python instrumentation patterns: opentelemetry.io/docs/languages/python/instrumentation/
- pytest plugin docs: docs.pytest.org/en/stable/how-to/writing_plugins.html
- pytest-benchmark: pytest-benchmark.readthedocs.io
