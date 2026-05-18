# Relay

## What This Is

Relay is a Python library for reliable context passing between AI agents. It provides a middleware pipeline that cryptographically signs context envelopes, enforces token budgets, validates handoffs, manages snapshots, and coordinates parallel agent execution across LangChain, CrewAI, AutoGen, and local model backends. All with zero runtime dependencies beyond Python stdlib.

## Core Value

Reliable, verifiable context passing between AI agents with cryptographic integrity guarantees, zero data loss, and explicit rollback recovery — establishing the norm for agent-to-agent communication.

## Requirements

### Validated

- `ENV-01` — HMAC-SHA256 envelope signing and verification — existing
- `ENV-02` — Immutable context envelope lifecycle (create, sign, validate, persist) — existing
- `ENV-03` — Monotonic step counter with pipeline_id tracking — existing
- `ENV-04` — Thread-safe pipeline state with non-reentrant lock — existing
- `ENV-05` — JSON snapshot persistence with index tracking — existing
- `BUD-01` — Hard token budget cap enforcement (heuristic + tiktoken) — existing
- `BUD-02` — Per-agent max_tokens via AgentManifest — existing
- `SLI-01` — Agent manifest read/write permission model — existing
- `SLI-02` — Recency, structural, and relevance slice packer strategies — existing
- `RUN-01` — Adapter framework: LangChain, CrewAI, AutoGen, RawSDK, LocalModel — existing
- `VAL-01` — Handoff validation: diff computation, contradiction detection — existing
- `VAL-02` — Entity extraction-based hallucination detection — existing
- `VAL-03` — Manifest boundary enforcement — existing
- `ROL-01` — Snapshot-based rollback with RollbackSuccess result — existing
- `PAR-01` — Parallel fork-join execution (UNION, VOTE, FIRST_WINS) — existing
- `REG-01` — Adapter registry for named agent runner lookup — existing
- `SEC-01` — Pipeline ID validation (path traversal prevention) — existing
- `SEC-02` — Max snapshot bytes enforcement (100MB) — existing
- `SEC-03` — HMAC comparison via compare_digest (timing attack prevention) — existing
- `SEC-04` — Signing secret minimum length validation (≥32 chars) — existing
- `CQ-01` — Strict mypy typing with zero suppressions (mypy --strict) — existing
- `CQ-02` — Pre-commit quality gates (mypy + unit tests + test naming) — existing
- `CQ-03` — Result-based error handling (no exceptions for operational errors) — existing
- `CQ-04` — Frozen dataclasses for all domain value types — existing
- `CQ-05` — Protocol-based dependency inversion for all pluggable components — existing
- `CQ-06` — Module docstrings with Owns/Does NOT format — existing
- `TST-01` — Comprehensive unit test suite with test doubles — existing
- `TST-02` — Integration tests with real wiring — existing
- `TST-03` — Concurrent access tests via threading.Thread — existing
- `TST-04` — Heuristic ground-truth benchmark tests — existing

### Active

- [ ] `REL-01` — Fix CRITICAL: replay attack protection (nonce + sequence_number)
- [ ] `REL-02` — Fix CRITICAL: signature verification on snapshot load
- [ ] `REL-03` — Fix CRITICAL: redact signing secret from repr output
- [ ] `REL-04` — Fix HIGH: budget enforcement measures output, not input
- [ ] `REL-05` — Fix HIGH: CoreRelayPipeline.__post_init__ raises ValueError instead of Failure
- [ ] `REL-06` — Fix HIGH: SSRF via unvalidated LocalModelAdapter base_url
- [ ] `REL-07` — Fix HIGH: no secret rotation mechanism (key_id, key history)
- [ ] `REL-08` — Fix MEDIUM: orphaned snapshot files on contradiction rollback
- [ ] `REL-09` — Fix MEDIUM: text key collision in agent_output_to_payload
- [ ] `REL-10` — Fix MEDIUM: apply_join_strategy raises ValueError instead of Failure
- [ ] `REL-11` — Fix MEDIUM: no timeout on CrewAIAdapter thread
- [ ] `REL-12` — Fix MEDIUM: symlink following in save_snapshot (TOCTOU)
- [ ] `REL-13` — Fix MEDIUM: TOCTOU race in _add_to_index
- [ ] `REL-14` — Fix MEDIUM: no snapshot cleanup mechanism
- [ ] `REL-15` — Add failure-code-exhaustive tests for all Result-returning functions
- [ ] `REL-16` — Add missing _assert_lock_held() to state-mutating internal methods
- [ ] `REL-17` — Add concurrent throughput testing
- [ ] `REL-18` — DOC: production deployment guide with tiktoken recommendation
- [ ] `REL-19` — v1.0 production release

### Out of Scope

- Web framework / HTTP server — this is a library, not a service
- Database persistence — filesystem-based snapshots are the storage model
- Containerization / orchestration — deployment-specific, user's choice
- CLI management tooling — defer to post-v1.0
- Real-time streaming — not in scope for context-passing middleware

## Context

Built from scratch as a pure Python library. The codebase is well-structured with strict layering (5 layers) and comprehensive testing. Recent work has addressed several security and correctness issues (budget projection, secret handling, signature verification, timestamp freshness).

The codebase mapper identified 3 CRITICAL and 4 HIGH severity issues that must be resolved before v1.0 production release. Budget enforcement and security hardening are the primary blockers.

## Constraints

- **Language**: Python 3.12+ only — no other language runtimes
- **Dependencies**: Zero runtime dependencies beyond Python stdlib — all frameworks are optional, lazy-imported
- **Error handling**: Result[T] pattern required — no exceptions for operational errors
- **Immutability**: All domain types frozen dataclasses — no mutation
- **Typing**: mypy --strict with zero suppressions — no # type: ignore, no bare Any
- **Layering**: Strict one-way dependency chain — lower layers never import upper
- **Threading**: Non-reentrant lock — no nested transaction() calls
- **Signing secret**: Must be ≥32 characters — validated at construction

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Result[T] over exceptions | Operational errors are data, not control flow — forces callers to handle every failure path | ✓ Good |
| Pure stdlib core (no runtime deps) | Library must not force dependency burden on users — frameworks are optional | ✓ Good |
| HMAC-SHA256 over JWT | No external crypto libs needed, simpler attack surface | ✓ Good |
| Filesystem snapshots over DB | Zero-infrastructure persistence — user provides storage path, done | ✓ Good |
| Non-reentrant lock | Catch nested transaction() bugs early rather than allowing silent reentrancy | ✓ Good |

---
*Last updated: 2026-05-17 after initialization*
