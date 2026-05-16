# Ruthless Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 748 mypy errors in tests, address source code bugs/shadowing, unify token heuristics, rename 200+ tests to sentence format, and update stale documentation.

**Architecture:** Systematic resolution following the 5-phase audit response strategy. We prioritize infrastructure and source correctness before tackling the large-scale test hygiene and documentation updates.

**Tech Stack:** Python 3.12, mypy, pytest, Relay Framework.

---

### Task 1: Config & Infrastructure hardening

**Files:**
- Modify: `mypy.ini`
- Create: `src/relay/py.typed`

- [ ] **Step 1: Create py.typed marker**
Create an empty file `src/relay/py.typed` to signal that the package is typed.
Run: `echo. > src/relay/py.typed`

- [ ] **Step 2: Harden mypy.ini**
Ensure `disallow_any_expr = True` is set (it seems it might be already, but confirm and lock it in). Add `warn_unused_ignores = True` if missing.
Remove unused sections: `[mypy-crewai.*]`, `[mypy-autogen.*]`, `[mypy-httpx.*]` (as they are reported as unused and dependencies are not present or ignored differently).

- [ ] **Step 3: Run mypy on src to verify clean state**
Run: `python -m mypy src/relay --strict`
Expected: Success (0 errors)

- [ ] **Step 4: Commit**
```bash
git add src/relay/py.typed mypy.ini
git commit -m "chore: harden mypy config and add py.typed marker"
```

---

### Task 2: Source Code Bug Fixes & Refactoring

**Files:**
- Modify: `src/relay/slicer/packers.py`
- Modify: `src/relay/runners/local_model.py`
- Modify: `src/relay/runners/raw_sdk.py`
- Modify: `src/relay/slicer/providers.py`
- Modify: `src/relay/core_pipeline.py`

- [ ] **Step 1: Fix RecencySlicePacker non-deterministic sort**
Modify `src/relay/slicer/packers.py` to handle `_`-containing keys without trailing digits deterministically by using the full key as a tie-breaker.

```python
def _recency_sort_key(k: str) -> tuple[int, int, str]:
    if "_" in k and k.split("_")[-1].isdigit():
        return (0, int(k.split("_")[-1]), k)
    return (1, 0, k)
```

- [ ] **Step 2: Remove object.__setattr__ hack in LocalModelAdapter**
Make `LocalModelAdapter` non-frozen and handle `base_url` stripping in `__post_init__` directly.

- [ ] **Step 3: Remove dead imports**
Clean up `Any` and `cast` from `raw_sdk.py`, `providers.py`, and `core_pipeline.py`.

- [ ] **Step 4: Verify Source with mypy**
Run: `python -m mypy src/relay --strict`
Expected: Success

- [ ] **Step 5: Commit**
```bash
git add src/relay/slicer/packers.py src/relay/runners/local_model.py src/relay/runners/raw_sdk.py src/relay/slicer/providers.py src/relay/core_pipeline.py
git commit -m "fix(source): resolve deterministic sort bug and clean up dead imports"
```

---

### Task 3: Test Type Safety (Large Scale)

**Files:**
- Modify: All files in `tests/`

- [ ] **Step 1: Add return type annotations to all test methods**
Iterate through all test files and add `-> None` to methods missing them. This is the bulk of the 748 errors.

- [ ] **Step 2: Remove stale type: ignore comments**
Remove `# type: ignore[override]` from `tests/unit/test_runners/test_registry.py:44`.
Remove `# type: ignore[misc]` from `tests/unit/test_runners/test_local_model.py:24`.

- [ ] **Step 3: Fix missing Any imports in tests**
Add `from typing import Any` where `dict[str, Any]` is used but `Any` is not imported.

- [ ] **Step 4: Verify Tests with mypy**
Run: `python -m mypy tests --strict`
Expected: Significant reduction in errors (aim for 0).

- [ ] **Step 5: Commit**
```bash
git add tests/
git commit -m "test: resolve 700+ mypy errors in test suite"
```

---

### Task 4: Test Naming & Missing Coverage

**Files:**
- Modify: `tests/` (multiple files)
- Create: `tests/unit/test_failure_paths.py` (or add to existing files)

- [ ] **Step 1: Rename tests to sentence format**
Rename `test_success_contains_value` -> `test_success_contains_value_when_constructed_with_value`.
Target ~200+ tests violating Rule 7.1.

- [ ] **Step 2: Implement 9 missing Failure-path tests**
Add tests for:
- `validate_pipeline_id` (INVALID_PIPELINE_ID)
- `list_snapshots` (CORRUPTED_INDEX, INVALID_INDEX)
- `save_snapshot` via `_add_to_index` (3 codes)
- `_do_rollback` (INVALID_STATE)
- `_finalize_step` (SNAPSHOT_SAVE_FAILED)
- `_check_budget` (packer Failure)
- `execute_parallel_step` (INVALID_STATE/budget fail/ALL_FORKS_FAILED)

- [ ] **Step 3: Refactor private state access in tests**
Refactor `tests/unit/test_pipeline.py` and others to avoid accessing `_state`, `_snapshot_store`, etc. directly.

- [ ] **Step 4: Run all tests**
Run: `pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 5: Commit**
```bash
git add tests/
git commit -m "test: rename tests to sentence format and add missing failure path coverage"
```

---

### Task 5: Documentation Refresh

**Files:**
- Create: `CHANGELOG.md`
- Modify: `docs/version-0.4/v0.4-plan.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Create CHANGELOG.md**
Add entries for v0.3 and v0.4.

- [ ] **Step 2: Update v0.4 plan**
Fix error code contradictions. Remove `pipeline_snapshot.py` references. Update private name conventions.

- [ ] **Step 3: Update AGENTS.md**
List all test doubles. Correct `pipeline_*.py` references.

- [ ] **Step 4: Check off deliverables in v0.4 plan**
Mark completed items as checked.

- [ ] **Step 5: Commit**
```bash
git add CHANGELOG.md docs/version-0.4/v0.4-plan.md AGENTS.md
git commit -m "docs: resolve documentation debt from v0.4 audit"
```
