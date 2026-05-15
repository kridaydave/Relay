# Relay Post-Ship Audit — 15 May 2026 (Pass 2)
**Date:** 15 May 2026
**Auditor:** Boston (J.Dev)
**Scope:** Full codebase — all 24 source modules, all 29 test modules
**Checked against:** `docs/Relay Coding Rules.md`, `AGENTS.md`
**Branch:** main
**Passes:** 1 (exhaustive read)
**Status:** Fixed --Matt (J.Dev)

---

## Summary

Audit of all previous fixes (from 6–15 May 2026 audits, status "Fixed by Matt J.Dev"). All 17 bugs and 12 rule violations from prior reports have been correctly resolved in the current code — confirmed by inspection. This pass finds 7 new issues not present in any prior audit. 1 is an architectural layer violation, 2 are docstring format gaps, 1 is a dead dependency, 1 is a config redundancy, and 2 are test quality items.

---

## PREVIOUS FIXES — VERIFIED

All items from Audit-15-May-2026.md (Eric), Audit-10-May-2026-3.md, Audit-10-May-2026-2.md, Audit-10-May-2026.md, Audit-7-May-2026.md, Audit-6-May-2026.md, and Ruthless-Code-Review.md were checked against the current code. All confirmed resolved. Notable:

| Prior issue | Status |
|---|---|
| BUG-01 — `get_latest_snapshot` wrong error code | ✅ Fixed — propagates `CORRUPTED_INDEX`, `INVALID_INDEX`, `INDEX_READ_FAILED` |
| BUG-02 — manifest violations wrong error code | ✅ Fixed — returns original `Failure`, doesn't call rollback |
| BUG-03 — `InvalidSnapshotIdError` escapes | ✅ Fixed — caught and converted to `Failure` |
| BUG-04 — ghost index entries | ✅ Fixed — file-first ordering |
| BUG-05 — state mutated before validation | ✅ Fixed — validation before `archive_and_set` |
| RULE-01 — `Failure.code: ErrorCode \| str` | ✅ Fixed — `code: ErrorCode` only |
| RULE-02 — `compute_signature` duplicate | ✅ Fixed — single function |
| RULE-03 — `snapshot_ids` lock guard | ✅ Fixed — `_assert_lock_held()` + returns copy |
| RULE-04 — `SlicePacker` ABC → Protocol | ✅ Fixed — now `Protocol` in `providers.py` |
| DEAD-01 — `import json` in `protocol.py` | ✅ Removed |
| DEAD-02 — `_apply_manifest_if_present` | ✅ Removed |
| MED-01 — `SnapshotManager` | ✅ Deleted |
| MED-02 — rollback duplication | ✅ Fixed — unified `_do_rollback` |
| MED-03 — `removed_count` mutation | ✅ Fixed — uses `effective_removed` |
| MED-04 — `close()` docstring | ✅ Fixed |
| TEST-02 — corrupted index test | ✅ Added |
| `RELAY_VERSION` | ✅ Bumped to `"0.3.3"` |
| `_dict_to_envelope` manifest_hash | ✅ Uses `_require_str` |
| `except BaseException` | ✅ Fixed to `except Exception` |
| `_slice_payload` returns `Result[str]` | ✅ Fixed — no longer swallows `Failure` |
| `manifest_hash=""` defaults | ✅ Removed |

---

## NEW FINDINGS

---

### FINDING-01 — `slicer/packers.py` imports from `relay.envelope` (Rule 1.2)

**File:** `src/relay/slicer/packers.py:12`
**Severity:** Medium
**Rule:** 1.2 — Layered imports: lower layers never import upper layers

```python
from relay.envelope import estimate_tokens
```

The import hierarchy states:
```
slicer/ ← imports types only
```

But `slicer/packers.py` imports `estimate_tokens` from `relay.envelope`. This is an upward dependency: `slicer/` is a lower layer consuming `estimate_tokens` from a higher layer (`envelope.py`). If `envelope.py` ever needed to import anything from `slicer/`, this would create a circular import.

`estimate_tokens` is also imported in exactly the same way from `core_pipeline.py:14` — but `core_pipeline.py` is the top-level orchestrator, so that's fine.

**Fix:** Move `estimate_tokens` into `types.py` (which has no internal imports and is the base layer), or duplicate the simple heuristic (`len(json_str) // 3`) in `slicer/packers.py` directly.

---

### FINDING-02 — `budget/__init__.py` and `slicer/__init__.py` lack `Owns:` / `Does NOT:` docstring (Rule 8.3)

**Files:** `src/relay/budget/__init__.py:1-13`, `src/relay/slicer/__init__.py:1-11`
**Severity:** Low
**Rule:** 8.3 — Module docstrings use the three-line format

Both files use a non-standard docstring format:

```
"""Provides ... / Exports: ... / Note: ..."""
```

Every other module in the codebase uses:
```
"""Summary sentence.

Owns: ...
Does NOT: ...
"""
```

The Rule 1.1 / 8.3 requirement applies to *every* module. These two `__init__.py` files are the only remaining exceptions (the `enforcer.py` one was fixed per earlier audits).

**Fix:** Rewrite both docstrings to the standard three-line format.

---

### FINDING-03 — String error codes in `test_context_broker.py` and `test_budget.py` (Rule 3.3)

**Files:** `tests/unit/test_context_broker.py:59,72`, `tests/unit/test_budget.py:22,35`
**Severity:** Low
**Rule:** 3.3 — Error codes are a public API; use the `ErrorCode` enum

The 15 May audit (TEST-01) listed 8 test locations using string literals for `Failure.code`. Those were fixed. But two more locations were missed:

| File | Line | String used | Should be |
|---|---|---|---|
| `test_context_broker.py` | 59 | `"INVALID_PIPELINE_ID"` | `ErrorCode.INVALID_PIPELINE_ID` |
| `test_context_broker.py` | 72 | `"INVALID_PAYLOAD"` | `ErrorCode.INVALID_PAYLOAD` |
| `test_budget.py` | 22 | `"BUDGET_EXCEEDED"` | `ErrorCode.BUDGET_EXCEEDED` |
| `test_budget.py` | 35 | `"INVALID_TOKEN_COUNT"` | `ErrorCode.INVALID_TOKEN_COUNT` |

**Fix:** Import `ErrorCode` in both test files and replace string literals with `ErrorCode.*` members.

---

### FINDING-04 — Unused `pydantic` dependency in `pyproject.toml`

**File:** `pyproject.toml:28`
**Severity:** Low

```toml
dependencies = [
    "pytest",
    "mypy",
    "pydantic",
]
```

`pydantic` is never imported or referenced anywhere in the codebase. It adds ~3MB to every install with zero benefit. Additionally, `pytest` and `mypy` are test/development tools — they belong in `[project.optional-dependencies] dev` or a separate group, not in the core `dependencies` list that end-users install.

**Fix:** Remove `pydantic` from `dependencies`. Move `pytest` and `mypy` to a `dev` optional-dependencies group.

---

### FINDING-05 — Unused `mypy` config section

**File:** `mypy.ini:21-23`
**Severity:** Low

```ini
[mypy-src.relay.*]
ignore_errors = False
```

This section produces `note: unused section(s): [mypy-src.relay.*]` at every mypy run. The section syntax is wrong — mypy interprets `[mypy-MODULEPATTERN]` as globbing, but the `-src.relay.*` format doesn't match any module path. The correct syntax would be `[mypy-src.relay.*]` → but even then, `ignore_errors = False` is the default and adds nothing.

**Fix:** Delete lines 21-23 from `mypy.ini`.

---

### FINDING-06 — `InvalidSnapshotIdError` exported in `__all__` but used only internally

**File:** `src/relay/snapshot.py:24,28-31`
**Severity:** Low

```python
__all__ = [
    "SnapshotStore",
    "InvalidSnapshotIdError",   # ← exported
]

class InvalidSnapshotIdError(Exception):
    """Raised when snapshot ID format is invalid."""
```

`InvalidSnapshotIdError` is a custom exception used only as internal control flow inside `_extract_step_from_snapshot_id`, which is called from `_add_to_index` where the exception is caught and converted to `Failure(CORRUPTED_INDEX)`. Callers should never see this exception.

Exporting it in `__all__` implies it's part of the public API — callers might attempt to catch it, but it will never propagate to them. If `Failure.code` handling is the intended contract (Rule 3.3), exporting the exception creates confusion.

**Fix:** Remove `InvalidSnapshotIdError` from `__all__`. Consider whether the exception class itself is needed — it could be replaced with `ValueError` (which already signals programmer error per Rule 3.1).

---

### FINDING-07 — `HeuristicCounter` has no protocol satisfaction test (Rule 7.6)

**File:** `tests/unit/test_budget.py:46-49`
**Severity:** Low
**Rule:** 7.6 — Test doubles must satisfy the Protocol

The existing test checks `isinstance(FixedCounter(42), TokenCounter)` — which is correct. But `HeuristicCounter` (in `token_counter.py:26`) is used as the fallback value for `TiktokenCounter` when `tiktoken` is not installed. If `TokenCounter` protocol adds a method, `HeuristicCounter` will fail silently at import time (via `TiktokenCounter = HeuristicCounter`).

**Fix:** Add:
```python
def test_heuristic_counter_satisfies_token_counter_protocol(self):
    from relay.budget.token_counter import HeuristicCounter
    assert isinstance(HeuristicCounter(), TokenCounter)
```

---

## SUMMARY TABLE

| Finding | Location | Severity | Rule |
|---|---|---|---|
| FINDING-01 — Upward import from slicer→envelope | `slicer/packers.py:12` | Medium | 1.2 |
| FINDING-02 — Missing Owns/Does NOT in package docstrings | `budget/__init__.py`, `slicer/__init__.py` | Low | 8.3 |
| FINDING-03 — String error codes in 2 test files | `test_context_broker.py`, `test_budget.py` | Low | 3.3 |
| FINDING-04 — Unused `pydantic` dependency | `pyproject.toml:28` | Low | — |
| FINDING-05 — Unused mypy config section | `mypy.ini:21-23` | Low | — |
| FINDING-06 — Internal exception exported in `__all__` | `snapshot.py:24` | Low | — |
| FINDING-07 — Missing protocol satisfaction test | `test_budget.py` | Low | 7.6 |

---

## PRIORITY ORDER

| Priority | Item | Reason |
|---|---|---|
| 1 | FINDING-01 — slicer imports envelope | Architectural; creates latent circular dependency risk |
| 2 | FINDING-02 — missing Owns/Does NOT | Every-module rule; 2 remaining outliers |
| 3 | FINDING-03 — string error codes in 2 test files | Same pattern as the fixed TEST-01 from 15 May |
| 4 | FINDING-04 — unused pydantic | Dead weight; +3MB to install |
| 5 | FINDING-05 — unused mypy section | Config noise; 1-line fix |
| 6 | FINDING-06 — InvalidSnapshotIdError export | Minor API surface concern |
| 7 | FINDING-07 — HeuristicCounter protocol test | Nice-to-have; prevents silent protocol drift |
