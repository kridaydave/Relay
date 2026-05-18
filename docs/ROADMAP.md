# Roadmap: Relay → v1.0

**9 phases** | 44 requirements mapped | All v1 requirements covered ✓

## Phase 1: SnapshotStore Protocol Extraction
**Goal:** Convert `SnapshotStore` to a Protocol, enabling test doubles and pluggable backends.
**Mode:** mvp
**Requirements:** STO-01, STO-02, STO-03, STO-04
**Progress:** 3/3 plans complete (✅ 01-01, ✅ 01-02, ✅ 01-03)
**Success Criteria:**
1. `SnapshotStore` exists as `@runtime_checkable` Protocol in its own file
2. Existing `SnapshotStore` renamed to `LocalFileSnapshotStore` with all tests passing
3. `InMemorySnapshotStore` exists and satisfies the Protocol
4. `CoreRelayPipeline` accepts any Protocol-compatible store
5. All existing unit and integration tests pass

## Phase 2: Structured Audit Logging
**Goal:** Emit structured, redacted audit events from pipeline lifecycle with pluggable sinks.
**Mode:** mvp
**Requirements:** AUD-01, AUD-02, AUD-03, AUD-04, SEC-12
**Progress:** 4/4 plans complete (✅ 02-01, ✅ 02-02, ✅ 02-03, ✅ 02-04)
**Plans:** 4 plans
```
Plans:
- [x] 02-01-PLAN.md — Core audit module + pipeline lifecycle events (AUD-01, AUD-03)
- [x] 02-02-PLAN.md — Step, budget, snapshot, validation, rollback events (AUD-01, AUD-02, AUD-04)
- [x] 02-03-PLAN.md — Parallel execution events (AUD-01)
- [x] 02-04-PLAN.md — SEC-12 max_age_seconds + signature events (SEC-12, AUD-01)
```
**Success Criteria:**
1. Audit events emitted at 10+ lifecycle points (create, commit, rollback, fork, join, budget fail, validation fail)
2. Payload values redacted by default — only metadata (step, outcome, latency, pipeline_id) in log
3. `AuditSink` Protocol with default JSON-formatted stdlib logging sink
4. Per-step timing captured and included in audit events
5. `verify_signature` enforces `max_age_seconds` (default 86400)

## Phase 3: Pytest Plugin
**Goal:** Ship `relay_pipeline` fixture and assertion helpers for testing multi-agent pipelines.
**Mode:** mvp
**Requirements:** TST-01, TST-02, TST-03, TST-04, TST-05
**Success Criteria:**
1. `relay_pipeline` fixture provides fresh in-memory pipeline per test (function-scoped)
2. `assert_clean_handoff()` validates step passed validation
3. `assert_rolled_back()` validates rollback was triggered
4. `snapshot_at()` returns snapshot at given step for custom assertions
5. Plugin registered via `pytest11` entry point with all imports deferred — zero import-time overhead

## Phase 4: OpenTelemetry Integration
**Goal:** Optional OTEL tracing per pipeline step with NoOp fallback.
**Mode:** mvp
**Requirements:** OTL-01, OTL-02, OTL-03, OTL-04
**Success Criteria:**
1. `RelayTracer` is lazy-imported via `__getattr__` (same pattern as `runners/__init__.py`)
2. One span per pipeline step with attributes: `pipeline_id`, `step`, `outcome`, `latency_ms`
3. Adapter calls wrapped in outer spans covering `to_thread()` duration
4. Default 10% sampling — zero overhead when tracer not configured
5. No `opentelemetry-sdk` dependency — API only, users bring SDK

## Phase 5: CLI Inspector
**Goal:** Read-only CLI for inspecting snapshots, viewing diffs, and debugging pipelines.
**Mode:** mvp
**Requirements:** CLI-01, CLI-02, CLI-03, CLI-04, CLI-05, SEC-06
**Success Criteria:**
1. `relay list <pipeline_id>` lists all snapshots with step, timestamp, token usage
2. `relay show <pipeline_id> <step>` displays snapshot details
3. `relay diff <pipeline_id> --from <step> --to <step>` shows normalized diff
4. CLI uses `relay.cli.api` stable module (no direct imports of internal API)
5. `argparse` used for CLI framework (stdlib, zero dependencies)
6. Envelope signature verified on snapshot load before display

## Phase 6: Performance Gates
**Goal:** Benchmark pipeline performance and detect regressions in CI.
**Mode:** mvp
**Requirements:** PRF-01, PRF-02, PRF-03, PRF-04
**Success Criteria:**
1. 10-step sequential pipeline <50ms per step (excl. LLM call) verified by benchmark
2. 5-fork parallel pipeline merge + validate <100ms verified by benchmark
3. `pytest-benchmark` microbenchmarks per component in CI
4. CI gate fails on >15% regression from baseline

## Phase 7: Pluggable Snapshot Backends
**Goal:** Redis, Postgres, and S3 snapshot stores via optional extras.
**Mode:** mvp
**Requirements:** STO-05, STO-06, STO-07, STO-08, STO-09, STO-10
**Success Criteria:**
1. `RedisSnapshotStore` via `redis-py` (`[redis]` extra) with connection pooling
2. `PostgresSnapshotStore` via `psycopg` (`[postgres]` extra) with auto-managed schema
3. `S3SnapshotStore` via `boto3` (`[s3]` extra) with gzipped JSON objects
4. Consistency level per backend (atomic for Postgres, WAL pattern for S3)
5. Connection pool registry deduplicated by connection string
6. Snapshot retention: `KeepLastN` and `KeepByAge` policies, `purge_before()` API

## Phase 8: Security Hardening
**Goal:** Resolve all CRIT and HIGH security issues blocking v1.0.
**Mode:** mvp
**Requirements:** SEC-05, SEC-08, SEC-09, SEC-10, SEC-11, SEC-13
**Success Criteria:**
1. Replay attack protection: `nonce` and `sequence_number` on `ContextEnvelope`, verified on every handoff
2. Budget enforcement: `_check_budget` projects output size from `manifest.writes`, not input slice
3. `CoreRelayPipeline.__post_init__` returns `Failure` instead of raising `ValueError`
4. Key rotation: `key_id` field on envelope, `SigningKey` dataclass, `ContextBroker.rotate_key()`
5. SSRF prevention: `LocalModelAdapter.base_url` validated (scheme, hostname, private IP rejection)
6. `create_next_envelope` moved to internal or budget pre-validation added

## Phase 9: v1.0 Release
**Goal:** Stable API, full documentation, and production release.
**Mode:** mvp
**Requirements:** API-01, API-02, API-03, API-04, SEC-07
**Success Criteria:**
1. Public API surface defined in `relay/__init__.py` with stable export contract
2. SemVer policy documented with 2-minor-release deprecation window
3. `test_public_api_matches_all` automated test enforces API contract
4. Production deployment guide published with `tiktoken` and optional extras documentation
5. Signing secret redacted from `repr()` output
6. All docs reviewed and current

---

*Created: 2026-05-17*
