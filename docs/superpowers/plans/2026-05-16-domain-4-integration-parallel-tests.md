# Domain 4 — Integration & Parallel Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all mypy --strict errors in parallel unit tests and integration tests while maintaining behavioral correctness.

**Architecture:** 
- Fix type annotations in fixtures and tests.
- Resolve `Any` usage by specifying proper types (`JSONDict`, `Coroutine`, `ForkResult`, etc.).
- Fix duplicate definitions in `conftest.py`.
- Add missing return type annotations.

**Tech Stack:** Python, mypy, pytest, asyncio.

---

### Task 1: Fix `tests/unit/test_parallel/conftest.py`

**Files:**
- Modify: `tests/unit/test_parallel/conftest.py`

- [ ] **Step 1: Fix duplicate definitions and missing names**
`FixedForkRunner`, `make_passing_fork_result`, `make_failing_fork_result`, `make_pipeline_components`, `make_context_slice` are defined twice. Also `adapter_name` and `manifest` are missing in one location.

- [ ] **Step 2: Add return type annotations to all fixtures**
Ensure all `@pytest.fixture` functions have explicit return type annotations.

- [ ] **Step 3: Resolve `Any` usage**
Replace `Any` with specific types where possible.

- [ ] **Step 4: Verify with mypy**
Run: `python -m mypy tests/unit/test_parallel/conftest.py --strict`
Expected: 0 errors in this file.

- [ ] **Step 5: Commit**
`git add tests/unit/test_parallel/conftest.py`
`git commit -m "test: fix typing and duplicate definitions in parallel conftest"`

### Task 2: Fix `tests/unit/test_parallel/test_types.py`

**Files:**
- Modify: `tests/unit/test_parallel/test_types.py`

- [ ] **Step 1: Add missing return type annotations**
Add `-> None` to all test functions.

- [ ] **Step 2: Fix read-only property assignment**
`ForkSpec.adapter_name` is read-only. Use proper initialization or mock if needed.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_parallel/test_types.py --strict`
Expected: 0 errors in this file.

- [ ] **Step 4: Commit**
`git add tests/unit/test_parallel/test_types.py`
`git commit -m "test: fix typing in parallel types tests"`

### Task 3: Fix `tests/unit/test_parallel/test_join.py`

**Files:**
- Modify: `tests/unit/test_parallel/test_join.py`

- [ ] **Step 1: Resolve `Any` in `Coroutine` annotations**
`Coroutine[Any, Any, ForkResult]` should be more specific if possible, or at least properly handled to satisfy `Any` check.

- [ ] **Step 2: Verify with mypy**
Run: `python -m mypy tests/unit/test_parallel/test_join.py --strict`
Expected: 0 errors in this file.

- [ ] **Step 3: Commit**
`git add tests/unit/test_parallel/test_join.py`
`git commit -m "test: fix typing in join parallel tests"`

### Task 4: Fix `tests/unit/test_parallel/test_fork_runner.py`

**Files:**
- Modify: `tests/unit/test_parallel/test_fork_runner.py`

- [ ] **Step 1: Fix `pytest.mark.asyncio` and `Any` usage**
Decorated functions often have `Any` inferred. Add explicit types.

- [ ] **Step 2: Add missing return type annotations**
Add `-> None` to all test functions.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_parallel/test_fork_runner.py --strict`
Expected: 0 errors in this file.

- [ ] **Step 4: Commit**
`git add tests/unit/test_parallel/test_fork_runner.py`
`git commit -m "test: fix typing in fork runner tests"`

### Task 5: Fix Integration Tests

**Files:**
- Modify: `tests/integration/test_runners_integration.py`
- Modify: `tests/integration/test_parallel_pipeline.py`
- Modify: `tests/integration/test_pipeline_integration.py`

- [ ] **Step 1: Fix `tests/integration/test_runners_integration.py`**
Resolve `Any` in async tests and add return types.

- [ ] **Step 2: Fix `tests/integration/test_parallel_pipeline.py`**
Check and fix any remaining mypy errors.

- [ ] **Step 3: Fix `tests/integration/test_pipeline_integration.py`**
Check and fix any remaining mypy errors.

- [ ] **Step 4: Verify all with mypy**
Run: `python -m mypy tests/integration/ --strict`
Expected: 0 errors in integration tests.

- [ ] **Step 5: Commit**
`git add tests/integration/`
`git commit -m "test: fix typing in integration tests"`

### Task 6: Final Verification

- [ ] **Step 1: Run all tests**
Run: `pytest tests/unit/test_parallel/ tests/integration/`
Expected: All tests pass.

- [ ] **Step 2: Final mypy check**
Run: `python -m mypy tests/unit/test_parallel/ tests/integration/ --strict`
Expected: Success.
