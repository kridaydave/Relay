# Core & State Unit Tests Mypy Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve mypy errors in Core & State unit tests by adding type annotations and standardizing JSON payloads.

**Architecture:** Use `JSONDict` for payloads, add missing return type annotations, and handle `Result` object unions with `isinstance` or `cast`.

**Tech Stack:** Python, mypy, pytest, relay.types.JSONDict

---

### Task 1: Fix `tests/unit/test_types.py`

**Files:**
- Modify: `tests/unit/test_types.py`

- [ ] **Step 1: Add return type annotations and JSONDict**
Read the file to identify missing annotations and dictionary types.

- [ ] **Step 2: Apply changes**
Add `-> None` to all test methods. Import `JSONDict` from `relay.types` and use it for dictionary variables.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_types.py --strict`
Expected: PASS

---

### Task 2: Fix `tests/unit/test_envelope.py`

**Files:**
- Modify: `tests/unit/test_envelope.py`

- [ ] **Step 1: Add return type annotations and JSONDict**
Add `-> None` to all methods. Use `JSONDict` for payloads.

- [ ] **Step 2: Fix union-attr errors**
For `Result` objects, use `isinstance(result, Success)` or `cast(Success, result)` to access `.value`.

- [ ] **Step 3: Fix misc errors (Any types)**
Ensure variables are explicitly typed to avoid `Any` leakage.

- [ ] **Step 4: Verify with mypy**
Run: `python -m mypy tests/unit/test_envelope.py --strict`
Expected: PASS

---

### Task 3: Fix `tests/unit/test_pipeline_state.py`

**Files:**
- Modify: `tests/unit/test_pipeline_state.py`

- [ ] **Step 1: Add return type annotations and JSONDict**
Add `-> None` to all methods. Use `JSONDict` for payloads.

- [ ] **Step 2: Fix misc errors**
Address any `Any` type errors in fixtures or test logic.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_pipeline_state.py --strict`
Expected: PASS

---

### Task 4: Fix `tests/unit/test_pipeline_rollback.py`

**Files:**
- Modify: `tests/unit/test_pipeline_rollback.py`

- [ ] **Step 1: Add return type annotations and JSONDict**
Add `-> None` to all methods. Use `JSONDict` for payloads.

- [ ] **Step 2: Fix union-attr and Any errors**
Handle `Result` objects correctly.

- [ ] **Step 3: Verify with mypy**
Run: `python -m mypy tests/unit/test_pipeline_rollback.py --strict`
Expected: PASS

---

### Task 5: Fix `tests/unit/test_snapshot.py`

**Files:**
- Modify: `tests/unit/test_snapshot.py`

- [ ] **Step 1: Add return type annotations and JSONDict**
Add `-> None` to all methods. Use `JSONDict` for payloads.

- [ ] **Step 2: Verify with mypy**
Run: `python -m mypy tests/unit/test_snapshot.py --strict`
Expected: PASS

---

### Task 6: Final Verification & Commit

- [ ] **Step 1: Run all tests**
Run: `python -m pytest tests/unit/test_types.py tests/unit/test_envelope.py tests/unit/test_pipeline_state.py tests/unit/test_pipeline_rollback.py tests/unit/test_snapshot.py`
Expected: ALL PASS

- [ ] **Step 2: Final mypy check**
Run: `python -m mypy tests/unit/test_types.py tests/unit/test_envelope.py tests/unit/test_pipeline_state.py tests/unit/test_pipeline_rollback.py tests/unit/test_snapshot.py --strict`
Expected: NO ERRORS

- [ ] **Step 3: Commit changes**
```bash
git add tests/unit/test_types.py tests/unit/test_envelope.py tests/unit/test_pipeline_state.py tests/unit/test_pipeline_rollback.py tests/unit/test_snapshot.py
git commit -m "test: resolve mypy errors in Core & State unit tests"
```
