# Fix Mypy Errors in tests/unit/test_pipeline.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 59 mypy --strict errors in `tests/unit/test_pipeline.py`.

**Architecture:** Systematic resolution of type errors by applying proper type hints, using `JSONDict` where appropriate, adding `cast` when necessary, and fixing redundant casts.

**Tech Stack:** Python, Mypy, Pytest

---

### Task 1: Fix fixture and mock type hints

**Files:**
- Modify: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Fix asyncio decorator errors**
Mypy complains about `Type of decorated function contains type "Any"`.
Change `@pytest.mark.asyncio` usages to ensure they don't introduce `Any`. Usually, this involves ensuring the function return type is `None`.

- [ ] **Step 2: Replace `list[Any]` in concurrent tests**
In `test_concurrent_step_execution_produces_consistent_results` and similar, replace `results: list[Any]` with `results: list[Success[ContextEnvelope] | Failure | RollbackSuccess]`.

- [ ] **Step 3: Fix `Success[Any]` errors**
Specify the type for `Success` where it's currently `Any`.

- [ ] **Step 4: Fix mock side effect and return value types**
Ensure `mock_initial.return_value` and `mock_next.side_effect` have explicit types if needed.

### Task 2: Fix incompatible assignments and redundant casts

**Files:**
- Modify: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Fix `submitted_payloads` type mismatch**
Line 163 and 220: `submitted_payloads: list[JSONDict] = [{"step": i, "data": f"data-{i}"} for i in range(3)]`. Ensure the list literal is correctly typed.

- [ ] **Step 2: Fix redundant casts**
Lines 382-384, 793: Remove `cast` calls that Mypy identifies as redundant.

- [ ] **Step 3: Fix incompatible types in assignment**
Lines 242 and 439: `expression has type "list[dict[str, object] | dict[str, int]]", variable has type "list[dict[str, object]]"`. Fix by using a more consistent type or casting the expression.

### Task 3: Final Verification

**Files:**
- Modify: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Run mypy and verify zero errors**
Run: `python -m mypy --strict tests/unit/test_pipeline.py`
Expected: Success with no errors.

- [ ] **Step 2: Run pytest to ensure no regressions**
Run: `pytest tests/unit/test_pipeline.py`
Expected: All tests pass.
