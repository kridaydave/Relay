# Project Research Summary

**Project:** Relay
**Domain:** LLM agent context-passing middleware — observability, tooling, and pluggable persistence
**Researched:** 2026-05-17
**Confidence:** HIGH (stack + architecture), MEDIUM (pitfalls validated from real incidents)

## Executive Summary

Relay is a Python library for managing context handoffs between LLM agents in multi-step pipelines. The v0.5 and v0.6 roadmap adds **structured observability** (audit events, OpenTelemetry tracing), **developer tooling** (CLI inspector, pytest plugin, performance gates), and **pluggable snapshot persistence** (Redis, Postgres, S3). All four researchers converge on the same architectural approach: these are **cross-cutting concerns woven through existing layers**, not new architectural layers. The existing 5-layer dependency ordering, `Result[T]` error handling, and sync lock architecture are preserved.

**The recommended build order is: SnapshotStore Protocol extraction → Structured Audit Logging → Pytest Plugin → OTEL Integration → CLI Inspector → Performance Gates (parallel) → Pluggable Backends (v0.6).** This ordering maximizes developer velocity by providing testing infrastructure early, and defers the riskiest features (remote backends with consistency guarantees) to v0.6.

**Key risks and mitigations:**
1. **Audit log leaks agent secrets** — redact payloads by default, log metadata only (PITFALL-1)
2. **OTEL span overhead busts <50ms per-step budget** — limit span granularity, default 10% sampling (PITFALL-3)
3. **OTEL context propagation broken across async/thread boundaries** — wrap adapter runs in outer spans, document limitations (PITFALL-4)
4. **Snapshot store async/sync mismatch** — unresolved tension between sync Protocol (ARCHITECTURE) and async recommendation (PITFALLS); needs resolution before v0.6
5. **CLI rollback is a security backdoor** — defer CLI rollback to v0.5+, fix CRIT-02 first (PITFALL-6)

---

## Key Findings

### Recommended Stack

**All stack recommendations carry HIGH confidence** — they are official packages, stdlib, or mature community standards.

| Category | Technology | Rationale |
|----------|-----------|-----------|
| Runtime | Python >=3.12 | Existing, `mypy --strict` enforced |
| Build | setuptools >=61.0 | Existing `[tool.setuptools.packages.find] where = ["src"]` |
| OTEL API | `opentelemetry-api` >=1.25 | **API only, not SDK** — avoids gRPC/protobuf transitive deps. Users bring their own SDK. |
| CLI framework | `argparse` (stdlib) | Only 3 subcommands — argparse trivially sufficient. Avoids `click` dependency. |
| Redis | `redis-py` >=5.0 | Sync client, standard Python Redis library |
| Postgres | `psycopg` >=3.1 | Modern sync/async driver, JSONB storage |
| S3 | `boto3` >=1.34 | Official AWS SDK |
| Benchmarking | `pytest-benchmark` >=4.0 | Integrates with existing pytest setup, lighter than `asv` |

**Key insight from STACK research:** The CLI framework decision allows either `argparse` (stdlib, zero-dependency) or `click` (richer subcommand support). The researcher **leaned toward argparse** for v0.5 given only 3 subcommands. This is a LOW-importance decision — either works.

### Expected Features

**Must have (table stakes):**
- **Structured JSON audit log** — pipe events to Datadog/Loki/Splunk without custom parsers (LOW complexity)
- **Per-step timing data** — captured automatically via audit events (LOW complexity)
- **Snapshot inspection + diff** — CLI `relay list`, `relay show`, `relay diff` (MEDIUM complexity)
- **Test fixture for pipeline** — `relay_pipeline` pytest fixture with in-memory storage (MEDIUM complexity)
- **Rollback verification** — `assert_rolled_back()` helper (LOW complexity)

**Should have (differentiators):**
- **OTEL trace per step** — correlate pipeline steps with LLM calls, DB queries in existing OTEL dashboards (MEDIUM complexity)
- **Sync-only snapshot Protocol** — simpler than async alternatives, consistent with existing sync lock architecture (LOW complexity)
- **In-memory snapshot store** — zero-config pytest integration, no temp directories (LOW complexity)
- **Pluggable storage without async** — Redis, Postgres, S3 with sync clients (MEDIUM complexity, v0.6)
- **No-op OTEL tracer when not installed** — zero overhead for non-OTEL users (LOW complexity)

**Anti-features (do NOT build):**
- Built-in OTEL exporter — users bring their own SDK/collector
- Web dashboard/UI — explicitly out of scope
- CLI rollback command (v0.5) — writes state from separate code path, dangerous
- Async SnapshotStore Protocol — premature, adds complexity without proven demand
- Metrics (counters, histograms) — OTEL metrics signal still stabilizing

### Architecture Approach

**The v0.5 and v0.6 features are cross-cutting concerns woven through existing layers, not new architectural layers.** Audit and OTEL are **observers** dispatched by `CoreRelayPipeline` via hooks/callbacks. Snapshot backends are a **within-layer Protocol extraction** from the existing `SnapshotStore` class. The pytest plugin is an **external consumer** (not a layer at all).

**Major components:**
1. **`AuditLogger` + `AuditSink` Protocol** (`src/relay/audit.py`) — receives lifecycle events from `CoreRelayPipeline._emit_audit_event()`; dispatches to pluggable sinks (default: structured JSON via standard `logging`)
2. **`RelayTracer`** (`src/relay/opentelemetry/`) — lazy-imported wrapper around OTEL with NoOp fallback; follows exact same pattern as `runners/__init__.py`
3. **`SnapshotStore` Protocol** → `LocalFileSnapshotStore` + `InMemorySnapshotStore` + remote backends — extracted from existing `SnapshotStore` class; sync-only interface
4. **CLI Inspector** (`src/relay/cli/`) — reads snapshots directly via `SnapshotStore` Protocol; `relay list`, `relay show`, `relay diff`; does NOT need `CoreRelayPipeline`
5. **Pytest plugin** (`src/relay/pytest_plugin.py`) — registers via `pytest11` entry point; `relay_pipeline` fixture uses `InMemorySnapshotStore`

**Key patterns to follow:**
- Lazy imports for all optional dependencies (exact same `__getattr__` pattern as `runners/__init__.py`)
- `@runtime_checkable` Protocols for dependency inversion (same as `TokenCounter`, `EmbeddingProvider`, `AgentRunner`)
- `Result[T]` return types everywhere, never exceptions for operational errors
- `@dataclass(frozen=True)` for all domain value types

### Critical Pitfalls

1. **PITFALL-1: Audit log dumps envelope payloads verbatim, leaking agent secrets** — Agent outputs may contain API keys, PII, credentials. **Prevention:** Redact payloads by default; log metadata only (step ID, outcome, latency). Add `redact_keys` parameter, `log_payloads: bool = False` flag that defaults off.

2. **PITFALL-3: OTEL span-per-step creates unacceptable overhead** — Each span costs ~30-45μs in Python. 150 spans × 45μs = 6.75ms — significant fraction of <50ms per-step budget. **Prevention:** Instrument at adapter and validation boundaries only, not internal helpers. Default 10% sampling. Guard with `is_enabled()`.

3. **PITFALL-4: OTEL context propagation breaks with async/threaded adapters** — `contextvars` don't propagate through `asyncio.to_thread()`. Adapter spans become orphaned. **Prevention:** Wrap adapter calls in outer spans covering full duration. Document that adapter-internal tracing needs its own instrumentation.

4. **PITFALL-5: CLI tightly coupled to internal API** — Direct imports of `SnapshotStore`, `ContextEnvelope`, `RollbackHandler` break on internal refactors. **Prevention:** Define `relay.cli.api` module with stable read-only operations. No direct imports from internal modules.

5. **PITFALL-9: Async/sync mismatch in pluggable backends** — **UNRESOLVED TENSION:** ARCHITECTURE recommends sync-only Protocol; PITFALLS warns sync Protocol with async backends causes `RuntimeError: Task got Future attached to a different loop`. **Prevention:** Resolve before v0.6. Options: (a) async Protocol from day one with `to_thread()` for sync operations, or (b) sync Protocol with sync-only backends and documented async limitation.

---

## Implications for Roadmap

The research strongly suggests a 7-phase structure with clear dependency ordering. The SnapshotStore Protocol extraction is the **critical path bottleneck** — everything downstream depends on it. Phases 2-6 are largely independent once Phase 1 is complete.

### Phase 1: SnapshotStore Protocol Extraction + InMemorySnapshotStore
**Rationale:** Everything downstream depends on this — pytest plugin needs `InMemorySnapshotStore`, CLI needs `SnapshotStore` Protocol, pluggable backends implement the Protocol. Must come first.
**Delivers:** `SnapshotStore` as `@runtime_checkable` Protocol, rename existing `SnapshotStore` → `LocalFileSnapshotStore`, new `InMemorySnapshotStore`, updated `CoreRelayPipeline` to accept Protocol-compatible instances.
**Addresses:** Foundation for snapshot inspection, pytest plugin, pluggable backends
**Uses:** stdlib only — no new dependencies
**Avoids:** PITFALL-10 (consistency planning needed now even though backends are v0.6 — the Protocol shape determines everything)

### Phase 2: Structured Audit Logging
**Rationale:** Second priority — highest user-facing value ("what is my pipeline doing?"). Depends on `relay.types` only, can proceed in parallel with Phase 1 if desired. Recommended sequential for safety.
**Delivers:** `src/relay/audit.py` — `AuditEvent`, `AuditLogger`, `AuditSink` Protocol, lifecycle hooks in `CoreRelayPipeline`
**Addresses:** Structured JSON audit log (table stake), per-step timing data (table stake)
**Uses:** stdlib `logging`, ISO 8601 timestamps
**Must avoid:**
- **PITFALL-1:** NEVER log payload values by default. Log metadata only. `redact_keys` parameter.
- **PITFALL-2:** Three-tier severity (AUDIT/INFO/TRACE). Default audit logger at WARNING. Rate limiting.
- **PITFALL-14:** Use `%s`-style lazy format strings, never f-strings in logging.

### Phase 3: Pytest Plugin
**Rationale:** Third priority — highest developer-facing value ("how do I test my pipeline?"). Depends on `InMemorySnapshotStore` (Phase 1) but NOT on audit/OTEL. Can be parallel with Phase 2.
**Delivers:** `src/relay/pytest_plugin.py` with `relay_pipeline` fixture, `src/relay/testing.py` with `assert_clean_handoff()`, `assert_rolled_back()`, `snapshot_at()`. Registered via `pytest11` entry point.
**Addresses:** Test fixture for pipeline (table stake), rollback verification (table stake)
**Uses:** `InMemorySnapshotStore` (from Phase 1)
**Must avoid:**
- **PITFALL-7:** Default `relay_pipeline` to `function` scope. Fresh state per test.
- **PITFALL-8:** Deferred imports in plugin — import Relay only inside fixture factory functions, not at module level.
- **PITFALL-18:** Zero I/O at import time. No `CoreRelayPipeline` construction at module level.

### Phase 4: OpenTelemetry Integration
**Rationale:** Fourth priority — differentiator. Depends on `CoreRelayPipeline` lifecycle hooks (partially established in Phase 2). Can proceed somewhat in parallel with Phase 3.
**Delivers:** `src/relay/opentelemetry/` subpackage with `RelayTracer` + NoOp fallback. Span hierarchy: `step.* → adapter.* → validate.* → snapshot.*`. Configured via environment variables or `configure_tracing()`.
**Addresses:** OTEL trace per step (differentiator)
**Uses:** `opentelemetry-api` (optional `[otel]` extra)
**Must avoid:**
- **PITFALL-3:** Limit span granularity. One span per pipeline step with key attributes, not per-internal-helper. Default sampling: recommend 10%.
- **PITFALL-4:** Wrap adapter calls in outer spans that cover `to_thread()` duration. Document context propagation limitations.
- **PITFALL-14:** Guard with `is_enabled()` checks. Zero overhead when tracer not configured.

### Phase 5: CLI Inspector
**Rationale:** Fifth priority — nice-to-have for v0.5, can slip to v0.5.x. Depends on `SnapshotStore` Protocol (Phase 1) but NOT on audit or OTEL.
**Delivers:** `src/relay/cli/` — `relay list`, `relay show`, `relay diff`. Read-only operations via `relay.cli.api` stable module.
**Addresses:** Snapshot inspection (table stake), snapshot diff (table stake)
**Uses:** `SnapshotStore` Protocol direct consumption; `argparse` (stdlib) for CLI framework
**Must avoid:**
- **PITFALL-5:** Define `relay.cli.api` with stable read-only operations. No direct imports from `relay.snapshot`, `relay.envelope`, `relay.pipeline_rollback`.
- **PITFALL-6:** Defer `relay rollback` to v0.5+. Fix CRIT-02 first. Require signing secret for rollback authorization.
- **PITFALL-19:** Versioned JSON output schema for machine-readable consumption.
- **PITFALL-22:** Normalize before diffing — ignore timestamps, sort keys, focus on manifest writes.

### Phase 6: Performance Gates (parallel)
**Rationale:** Independent of all other phases. Can be done anytime after base pipeline is stable. Recommended in parallel with Phases 3-5.
**Delivers:** `pytest-benchmark` microbenchmarks per component, `relay bench` CLI for end-to-end benchmarks, CI baseline comparison failing on >15% regression.
**Addresses:** Performance regression detection
**Uses:** `pytest-benchmark` >=4.0 (dev dependency)
**Design doc targets:** 10-step sequential <50ms/step, 5-fork parallel <100ms (both excluding LLM calls).

### Phase 7: Pluggable Backends (v0.6)
**Rationale:** Deferred to v0.6. All three backends (Redis, Postgres, S3) depend on `SnapshotStore` Protocol (Phase 1) and are independent of each other. Each can be built in any order.
**Delivers:** `RedisSnapshotStore`, `PostgresSnapshotStore`, `S3SnapshotStore` in `src/relay/snapshot/backends/`
**Addresses:** Pluggable storage (differentiator)
**Uses:** `redis-py` >=5.0 (`[redis]`), `psycopg` >=3.1 (`[postgres]`), `boto3` >=1.34 (`[s3]`)
**Must avoid — CRITICAL UNRESOLVED:**
- **PITFALL-9 (async/sync tension):** ARCHITECTURE recommends sync Protocol; PITFALLS warns "Make `SnapshotStore` an async Protocol from day one." **This MUST be resolved before Phase 7 work begins.**
- **PITFALL-10:** Define `ConsistencyLevel` enum for backends. Pipeline adapts behavior (atomic transactions for Postgres, WAL pattern for S3).
- **PITFALL-11:** Connection pool registry to deduplicate by connection string. `close()` lifecycle method.
- **PITFALL-20:** Versioned snapshots with migration functions for schema evolution.
- **PITFALL-21:** Retention policy (`KeepLastN`, `KeepByAge`), `purge_before()` API.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (OTEL):** RECOMMEND `/gsd-plan-phase --research-phase otel` — OTEL context propagation across thread boundaries (PITFALL-4) is subtle and needs specific testing with Relay's adapter architecture. Span overhead budgeting (PITFALL-3) needs microbenchmarks to validate <10ms overhead budget.
- **Phase 7 (Pluggable backends):** RECOMMEND `/gsd-plan-phase --research-phase backends` — async/sync Protocol decision (PITFALL-9), consistency model design (PITFALL-10), and connection pooling strategy (PITFALL-11) need dedicated research before implementation. Each backend has unique failure modes.

Phases with well-documented patterns (skip additional research-phase):
- **Phase 1 (SnapshotStore Protocol):** Standard Protocol extraction. The ARCHITECTURE research provides complete implementation guidance.
- **Phase 2 (Audit):** Standard callback/hook pattern. Research is comprehensive.
- **Phase 3 (Pytest Plugin):** Standard pytest plugin patterns. Research covers all edge cases.
- **Phase 5 (CLI):** Standard CLI patterns with `argparse`. Well-understood.
- **Phase 6 (Performance gates):** Standard `pytest-benchmark` usage. No research needed.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | All recommendations from official packages or stdlib. OTEL API-only avoids SDK complexity. |
| Features | **HIGH** | Derived from existing design doc and codebase analysis. MVP prioritization is clear. |
| Architecture | **HIGH** | Based on analysis of existing 5-layer architecture. Cross-cutting concern approach validated against alternative approaches. |
| Pitfalls | **MEDIUM** | 5 critical pitfalls verified from real-world incidents (Sentry, Supabase, IntelOwl, psycopg, s3fs, pytest). 19 moderate/minor pitfalls projected from Relay-specific risks. Async/sync tension (PITFALL-9) is the most consequential unresolved item. |

**Overall confidence: HIGH** for stack, features, and architecture. **MEDIUM** for pitfalls due to the unresolved async/sync Protocol tension and the fact that some pitfalls are projected rather than observed.

### Gaps to Address

1. **Async vs sync SnapshotStore Protocol (PITFALL-9):** ARCHITECTURE says sync (rationale: lock architecture, mature sync clients). PITFALLS says async (rationale: event loop contamination for Redis/Postgres/S3). **Resolution needed before v0.6.** Recommended approach: start sync (per ARCHITECTURE) since v0.6 is not imminent, but design the Protocol to allow an `AsyncSnapshotStore` subtype later. Flagged for `/gsd-plan-phase --research-phase backends`.

2. **CLI framework decision:** Both `argparse` and `click` work. The STACK researcher leans argparse for zero-dependency CLI. This needs confirmation during Phase 5 planning but is low-impact — either choice can be implemented in <50 lines.

3. **API stability boundary definition (PITFALL-13, PITFALL-16):** The exact list of public vs internal APIs needs formal definition before v1.0. Export surface currently undocumented. Start defining `__all__` and `STABLE_API` categorization in v0.5, enforced at v1.0.

4. **Snapshot retention policy (PITFALL-21):** No `delete_snapshot()` or `purge_before()` APIs exist (CONCERNS.md). Needs design for v0.6 backends. Low urgency for v0.5.

5. **Signing key rotation (PITFALL-12):** `ContextEnvelope` has no `key_id` field, making key rotation destructive. Identified in CONCERNS.md HIGH-04. Needs fixing before v1.0 security hardening.

---

## Sources

### Primary (HIGH confidence)
- Relay Design Document: `docs/Relay Design Document.md` — architecture constraints, phase roadmap
- Relay CONCERNS.md — CRIT-02, HIGH-04, W1, BUG-02
- Existing codebase: `src/relay/` — patterns proven in `runners/__init__.py`, `budget/`, `slicer/`
- OpenTelemetry Python docs: opentelemetry.io/docs/languages/python/instrumentation/
- `opentelemetry-api` PyPI package (v1.41.1, April 2026)
- pytest plugin docs: docs.pytest.org/en/stable/how-to/writing_plugins.html
- pytest-benchmark: pytest-benchmark.readthedocs.io

### Incidents & Community Evidence (HIGH confidence)
- open-telemetry/opentelemetry-python#3474 — CPU overhead from `always_on` sampler
- supabase/supabase-py#1025 — sensitive data in debug logs
- intelowlproject/IntelOwl#3465 — API key leakage in debug logs
- paperclipai/paperclip#4759 — plaintext passwords in log output
- getsentry/sentry-python#2417 — `repr()` leaks auth tokens in exception logs
- psycopg/psycopg#737 — async pool event loop mismatch hang
- fsspec/s3fs#842 — sync/async mixed event loop error on S3 filesystem
- redis/redis-vl-python#465 — sync pool for async Redis Sentinel connections
- nlp2sql#35 — asyncpg breaks from sync context
- pytest-dev/pytest#12722 — slow collection from expensive imports
- pytest-dev/pytest-asyncio#720 — iscoroutinefunction overhead in collection
- pytest-dev/pytest#13755 — session-scoped fixture re-initialization
- pytest-dev/pluggy#445 — lazy import optimization (0.69s → 0.004s)
- jpadilla/pyjwt#1085 — breaking change from key length enforcement
- icgood/pymap#159 — optional deps became mandatory via entry points
- PEP 810 — Python 3.15 lazy imports, 50-80% CLI startup improvement

### Secondary (MEDIUM confidence)
- OneUptime OTEL benchmarking — span creation costs by language
- `oj-persistence` — pluggable backends with capability system and pool registry
- AuditBuffet pattern catalog — secrets in logs compliance guidance
- PEP 761 — CPython PGP→Sigstore transition complexity
- scientific-python/lazy-loader — library for deferred subpackage imports

---

*Research completed: 2026-05-17*
*Ready for roadmap: yes*
