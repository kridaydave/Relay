# Requirements: Relay

**Defined:** 2026-05-17
**Core Value:** Reliable, verifiable context passing between AI agents with cryptographic integrity guarantees

## v1 Requirements

### SnapshotStore Protocol (Foundation)

- [x] **STO-01**: Extract `SnapshotStore` as `@runtime_checkable` Protocol from existing class
- [x] **STO-02**: Rename existing `SnapshotStore` → `LocalFileSnapshotStore`
- [ ] **STO-03**: Create `InMemorySnapshotStore` for testing
- [ ] **STO-04**: Update `CoreRelayPipeline` to accept Protocol-compatible store instances

### Structured Audit Logging

- [ ] **AUD-01**: Emit structured audit events at key pipeline lifecycle points
- [ ] **AUD-02**: Redact payload values from audit events by default (metadata only)
- [ ] **AUD-03**: Support pluggable `AuditSink` Protocol with default JSON-logger sink
- [ ] **AUD-04**: Per-step timing data captured automatically via audit events

### Pytest Plugin

- [ ] **TST-01**: `relay_pipeline` fixture with `InMemorySnapshotStore` (function-scoped)
- [ ] **TST-02**: `assert_clean_handoff()` assertion helper
- [ ] **TST-03**: `assert_rolled_back()` assertion helper
- [ ] **TST-04**: `snapshot_at()` snapshot retrieval helper
- [ ] **TST-05**: Register via `pytest11` entry point with deferred imports

### OpenTelemetry Integration

- [ ] **OTL-01**: Lazy-imported `RelayTracer` with NoOp fallback (no OTEL SDK dependency)
- [ ] **OTL-02**: Create span per pipeline step with key attributes
- [ ] **OTL-03**: Default 10% sampling, configurable via `configure_tracing()`
- [ ] **OTL-04**: Wrap adapter calls in outer spans covering `to_thread()` duration

### CLI Inspector

- [ ] **CLI-01**: `relay list` — list snapshots for a pipeline
- [ ] **CLI-02**: `relay show` — display snapshot details
- [ ] **CLI-03**: `relay diff` — diff two snapshots
- [ ] **CLI-04**: Define `relay.cli.api` stable module (no direct internal imports)
- [ ] **CLI-05**: Use `argparse` for CLI framework (stdlib, zero dependencies)

### Pluggable Snapshot Backends

- [ ] **STO-05**: `RedisSnapshotStore` via `redis-py` (`[redis]` extra)
- [ ] **STO-06**: `PostgresSnapshotStore` via `psycopg` (`[postgres]` extra)
- [ ] **STO-07**: `S3SnapshotStore` via `boto3` (`[s3]` extra)
- [ ] **STO-08**: Consistency model design per backend (atomic, WAL, best-effort)
- [ ] **STO-09**: Connection pool registry deduplicated by connection string
- [ ] **STO-10**: Snapshot retention policy (`KeepLastN`, `KeepByAge`), `purge_before()` API

### Security Hardening

- [ ] **SEC-05**: Add `nonce` and `sequence_number` to `ContextEnvelope` (replay attack prevention)
- [ ] **SEC-06**: Verify envelope signature on snapshot load (CRIT-02)
- [ ] **SEC-07**: Redact signing secret from `repr()` output (CRIT-03)
- [ ] **SEC-08**: Fix budget enforcement — project output size, not input size (HIGH-01)
- [ ] **SEC-09**: Fix `CoreRelayPipeline.__post_init__` — return `Failure` instead of raising (HIGH-03)
- [ ] **SEC-10**: Add `key_id` and key rotation mechanism (HIGH-04)
- [ ] **SEC-11**: Validate `LocalModelAdapter.base_url` (SSRF prevention)
- [ ] **SEC-12**: Enforce `max_age_seconds` on `verify_signature` calls (default 86400)
- [ ] **SEC-13**: Fix `create_next_envelope` bypass — move to internal or add pre-validation

### Performance Gates

- [ ] **PRF-01**: 10-step sequential pipeline <50ms per step (excl. LLM call)
- [ ] **PRF-02**: 5-fork parallel pipeline merge + validate <100ms (excl. LLM call)
- [ ] **PRF-03**: `pytest-benchmark` microbenchmarks per component
- [ ] **PRF-04**: CI baseline comparison failing on >15% regression

### API Stability

- [ ] **API-01**: Define public API surface in `relay/__init__.py` (stable export contract)
- [ ] **API-02**: SemVer with minimum 2-minor-release deprecation window
- [ ] **API-03**: Deprecation decorator and automated `test_public_api_matches_all` test
- [ ] **API-04**: Publish production deployment guide with `tiktoken` recommendation

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

- **CLI-06**: `relay rollback` command (requires CRIT-02 fix first)
- **CLI-07**: `relay export` — export snapshots for debugging
- **CLI-08**: `relay prune` — prune old snapshots
- **AUD-05**: Rate-limited audit log output
- **OTL-05**: OTEL metrics (counters, histograms) — defer until OTEL metrics signal stabilizes
- **SEC-14**: Snapshot encryption at rest
- **STO-11**: Async SnapshotStore Protocol subtype

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web dashboard / UI | Explicitly excluded per design doc — Relay is a library, not a service |
| Prompt management / template rendering | Not part of context-passing middleware |
| Built-in retry beyond rollback | Rollback is deterministic; repair is speculative per design principle |
| Any paid or hosted service | Relay is open-source library |
| Built-in OTEL exporter | Users bring their own SDK/collector |
| Async SnapshotStore Protocol | Premature — sync Protocol simpler, async subtype later |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| STO-01 | Phase 1 | Complete |
| STO-02 | Phase 1 | Complete |
| STO-03 | Phase 1 | Pending |
| STO-04 | Phase 1 | Pending |
| AUD-01 | Phase 2 | Pending |
| AUD-02 | Phase 2 | Pending |
| AUD-03 | Phase 2 | Pending |
| AUD-04 | Phase 2 | Pending |
| TST-01 | Phase 3 | Pending |
| TST-02 | Phase 3 | Pending |
| TST-03 | Phase 3 | Pending |
| TST-04 | Phase 3 | Pending |
| TST-05 | Phase 3 | Pending |
| OTL-01 | Phase 4 | Pending |
| OTL-02 | Phase 4 | Pending |
| OTL-03 | Phase 4 | Pending |
| OTL-04 | Phase 4 | Pending |
| CLI-01 | Phase 5 | Pending |
| CLI-02 | Phase 5 | Pending |
| CLI-03 | Phase 5 | Pending |
| CLI-04 | Phase 5 | Pending |
| CLI-05 | Phase 5 | Pending |
| PRF-01 | Phase 6 | Pending |
| PRF-02 | Phase 6 | Pending |
| PRF-03 | Phase 6 | Pending |
| PRF-04 | Phase 6 | Pending |
| STO-05 | Phase 7 | Pending |
| STO-06 | Phase 7 | Pending |
| STO-07 | Phase 7 | Pending |
| STO-08 | Phase 7 | Pending |
| STO-09 | Phase 7 | Pending |
| STO-10 | Phase 7 | Pending |
| SEC-05 | Phase 8 | Pending |
| SEC-06 | Phase 8 | Pending |
| SEC-07 | Phase 8 | Pending |
| SEC-08 | Phase 8 | Pending |
| SEC-09 | Phase 8 | Pending |
| SEC-10 | Phase 8 | Pending |
| SEC-11 | Phase 8 | Pending |
| SEC-12 | Phase 8 | Pending |
| SEC-13 | Phase 8 | Pending |
| API-01 | Phase 9 | Pending |
| API-02 | Phase 9 | Pending |
| API-03 | Phase 9 | Pending |
| API-04 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-17*
*Last updated: 2026-05-17 after initial definition*
