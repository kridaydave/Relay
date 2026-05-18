
---
phase: 02
slug: structured-audit-logging
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-17
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | pyproject.toml (contains pytest config) |
| **Quick run command** | `pytest tests/unit/test_audit*.py -v` |
| **Full suite command** | `pytest tests/unit -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_audit*.py -x` + `python -m mypy --strict src/relay`
- **After every plan wave:** Run `pytest tests/unit -v`
- **Before `/gsd-verify-work`:** Full suite must be green + mypy --strict zero suppressions
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | AUD-01 | — | N/A | unit | `pytest tests/unit/test_audit_events.py -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | AUD-04 | — | N/A | unit | `pytest tests/unit/test_audit_events.py -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | AUD-03 | — | N/A | unit | `pytest tests/unit/test_audit_sink.py -x` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | AUD-02 | — | N/A | unit | `pytest tests/unit/test_audit_redactor.py -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | SEC-12 | T-02-01 | max_age enforced on verify_signature | unit | `pytest tests/unit/test_envelope.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_audit_events.py` — covers AUD-01, AUD-04
- [ ] `tests/unit/test_audit_sink.py` — covers AUD-03, `FixedAuditSink` test double
- [ ] `tests/unit/test_audit_redactor.py` — covers AUD-02
- [ ] `tests/unit/test_types.py` — add `STALE_SIGNATURE` ErrorCode test
- [ ] `tests/conftest.py` — add `FixedAuditSink` test double

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| JSON log output format | AUD-03 | Format preference, not correctness | Verify JsonLogSink output is valid JSON with expected fields |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
