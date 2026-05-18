---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "concerns"
---

# CONCERNS.md — Technical Debt & Issues

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## Code Health

**No TODO/FIXME/XXX/HACK/BUG markers found** in source code. The codebase is well-maintained with no deferred work flagged in comments.

## Architecture Concerns

### 1. Budget Enforcement is Advisory Under Concurrent Load

`core_pipeline.py:642-646` documents this explicitly:
> "The budget check at step 3 is advisory under concurrent load. The lock is released before adapter.run() (to avoid holding it during I/O), so another thread may advance the envelope between the check and execution."

**Impact**: Token budget can be exceeded in concurrent scenarios. The `RollbackSuccess` safety net handles post-hoc detection, but the overrun already occurred.

**Mitigation**: Rollback is the safety net. Per-agent `max_tokens` provides an additional guard.

### 2. Heuristic Token Counting

`src/relay/envelope.py:312-330` uses `len(json_str) // 3` for token estimation:
- This is a coarse approximation (0.33 tokens/char)
- Real BPE tokenizers vary from 0.25-0.40 tokens/char
- Suitable for budget estimation but NOT precise counting

**Impact**: Budget calculations may be off by up to ~25% compared to real tokenizers.

**Mitigation**: `tiktoken` optional dependency provides accurate counting when installed.

### 3. Non-Reentrant Lock

`PipelineState` uses a non-reentrant `threading.Lock`. Nested `transaction()` calls raise `RuntimeError` (hard crash).

**Impact**: Developer error causes immediate crash rather than graceful degradation. This is intentional (documented as "deliberate programmer-error hard crash").

**Mitigation**: Clear documentation, `assert_lock_held()` checks, and comprehensive tests.

### 4. Large Core Pipeline File

`src/relay/core_pipeline.py` is 967 lines — the largest single file in the codebase.

**Impact**: Harder to navigate, higher cognitive load for new contributors.

**Mitigation**: Well-structured with clear method separation. Private methods (`_handle_initial_step`, `_handle_subsequent_step`, `_check_budget`, etc.) decompose complexity.

## Security Observations

### Positive
- HMAC-SHA256 signing with `hmac.compare_digest` (constant-time comparison)
- Minimum 32-character secret validation
- Pipeline ID regex validation prevents path traversal
- Symlink defense in snapshot store (pre/post creation checks)
- Atomic file writes with `O_NOFOLLOW`
- `SigningKey` repr redaction hides secrets from logs
- No `TODO`/`FIXME` markers hiding deferred security work

### Watch Items
- `estimated_output_cost` defaults to 0 in `HardCapEnforcer.check()` — callers must provide realistic estimates for true hard cap enforcement
- Snapshot files are stored as plaintext JSON on disk — no encryption at rest
- Audit log is a local file (`relay_audit.log`) — no tamper protection

## Performance Considerations

### Snapshot I/O
- Every pipeline step writes a JSON file to disk
- Max snapshot size: 100 MB (enforced)
- No batching or async I/O for snapshot writes
- `InMemorySnapshotStore` available for testing but not production

### Entity Extraction
- `HandoffValidator._extract_entities()` traverses JSON iteratively with depth limit (50) and entity limit (10,000)
- Uses heuristic entity detection (key-based) — known false positives/negatives
- `MaxDepthExceededError` exception is the only exception used for operational flow control (arguably should return `Failure`)

## Test Coverage Gaps

Based on `scripts/check_failure_coverage.py` enforcement:
- All `ErrorCode` variants should have corresponding test coverage
- CI fails if any error code is untested

Potential gaps to verify:
- `FORK_EXECUTION_FAILED` — may lack dedicated test
- `INDEX_READ_FAILED` — OS error path in index loading
- `MISSING_SECTIONS` — defined but may not be actively used

## Dependency Concerns

### Zero Core Dependencies
- **Positive**: No supply chain risk from required dependencies
- **Watch**: Optional dependencies (tiktoken, langchain-core, crewai, pyautogen, httpx) are not pinned to exact versions — only minimum versions specified

### Python Version Support
- Supports Python 3.12+ (uses PEP 695 `type` syntax)
- CI tests 3.12 and 3.13
- `.mypy_cache` has entries for 3.10, 3.11, 3.12, 3.14 — suggests historical support or future planning

## Maintenance Concerns

### Planning Artifacts
- `.planning/` directory contains extensive GSD artifacts (phases, research, reviews)
- Some may be stale if not cleaned up between project iterations
- `tmp_pycache/` directory exists — should be in `.gitignore` or cleaned

### Build Artifacts
- `dist/` contains `relay_middleware-0.5.0.tar.gz` and `.whl` — current version is 0.5.1, suggesting stale build artifacts

### Documentation
- `docs/website/` contains a static website (HTML/CSS/JS) — separate from package docs
- `docs/Relay Coding Rules.md` and `docs/Relay Design Document.md` are authoritative but may drift from implementation
- `Internal-changelog.md` exists alongside `CHANGELOG.md` — potential for inconsistency

## Debt Summary

| Category | Severity | Items |
|----------|----------|-------|
| Architecture | Low | Advisory budget under concurrency, heuristic token counting |
| Security | Low | Plaintext snapshots, default output cost = 0 |
| Performance | Low | Synchronous snapshot I/O, large core_pipeline.py |
| Maintenance | Low | Stale build artifacts, tmp_pycache directory |
| Testing | Info | Verify all ErrorCode variants have test coverage |

**Overall assessment**: The codebase is in good health. No critical issues found. Concerns are primarily architectural trade-offs that are documented and mitigated.
