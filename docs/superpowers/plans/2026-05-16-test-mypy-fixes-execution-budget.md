# Test Mypy Fixes: Execution & Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all mypy errors in Execution & Budget unit tests while standardizing on `JSONDict`.

**Architecture:** 
- Add explicit `-> None` return types to all test methods.
- Replace `dict[str, Any]` or `dict[str, str]` with `JSONDict` where appropriate.
- Fix complex mocking issues in `test_pipeline.py` by using proper typing for patched objects.
- Use `type: ignore[attr-defined]` sparingly for private attribute access in tests.

**Tech Stack:** Python, pytest, mypy, unittest.mock

---

### Task 1: Fix `tests/unit/test_budget.py`

**Files:**
- Modify: `tests/unit/test_budget.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all `test_*` functions and any helper functions.

- [ ] **Step 2: Verify with mypy**
Run: `python -m mypy tests/unit/test_budget.py --strict`
Expected: Success

- [ ] **Step 3: Commit**
```bash
git add tests/unit/test_budget.py
git commit -m "test: add return type annotations to test_budget.py"
```

### Task 2: Fix `tests/unit/test_slicer.py`

**Files:**
- Modify: `tests/unit/test_slicer.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods.

- [ ] **Step 2: Standardize with JSONDict**
Import `JSONDict` from `relay.types`.
Replace incompatible dict types with `JSONDict`.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_slicer.py --strict`
Expected: Success

- [ ] **Step 4: Commit**
```bash
git add tests/unit/test_slicer.py
git commit -m "test: fix mypy errors in test_slicer.py"
```

### Task 3: Fix `tests/unit/test_validator.py`

**Files:**
- Modify: `tests/unit/test_validator.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods.

- [ ] **Step 2: Fix Any and type-arg errors**
Import `Any`, `Mapping` from `typing`.
Import `JSONDict` from `relay.types`.
Annotate dicts that mypy complains about.
Use `JSONDict` for payloads.

- [ ] **Step 3: Fix Union attribute access**
Ensure `unwrap` or explicit checks are used before accessing `.value` on `Result`.

- [ ] **Step 4: Verify with mypy**
Run: `python -m mypy tests/unit/test_validator.py --strict`
Expected: Success

- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_validator.py
git commit -m "test: fix mypy errors in test_validator.py"
```

### Task 4: Fix `tests/unit/test_context_broker.py`

**Files:**
- Modify: `tests/unit/test_context_broker.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods.

- [ ] **Step 2: Fix @patch typing**
Ensure patched arguments in test methods are typed (e.g., `mock_something: MagicMock`).

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_context_broker.py --strict`
Expected: Success

- [ ] **Step 4: Commit**
```bash
git add tests/unit/test_context_broker.py
git commit -m "test: fix mypy errors in test_context_broker.py"
```

### Task 5: Fix `tests/unit/test_pipeline.py`

**Files:**
- Modify: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods.

- [ ] **Step 2: Fix complex mocking and Any leaks**
Type all `MagicMock` arguments.
Use `JSONDict` for all payload mocks.
Add `# type: ignore[attr-defined]` for `_state` and `_snapshot_store` access.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_pipeline.py --strict`
Expected: Success

- [ ] **Step 4: Commit**
```bash
git add tests/unit/test_pipeline.py
git commit -m "test: fix mypy errors in test_pipeline.py"
```

### Task 6: Final Verification

- [ ] **Step 1: Run all tests**
Run: `python -m pytest tests/unit/test_pipeline.py tests/unit/test_context_broker.py tests/unit/test_budget.py tests/unit/test_validator.py tests/unit/test_slicer.py`
Expected: All PASS

- [ ] **Step 2: Run mypy on all files**
Run: `python -m mypy tests/unit/test_pipeline.py tests/unit/test_context_broker.py tests/unit/test_budget.py tests/unit/test_validator.py tests/unit/test_slicer.py --strict`
Expected: Success
