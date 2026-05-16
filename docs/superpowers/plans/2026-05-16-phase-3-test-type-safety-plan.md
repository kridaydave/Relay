# Phase 3 — Test Type Safety (Large Scale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Parallel Execution:** Tasks 1, 2, 3, and 4 are independent and should be executed by separate parallel subagents. Task 5 is the final synchronization gate.

**Goal:** Resolve all 751 mypy errors in the test suite and enforce strict type safety per Rule 2.1.

**Architecture:** Systematic resolution by domain. Standardizes on `JSONDict` for payloads and `-> None` for test methods.

**Tech Stack:** Python 3.12, mypy, pytest.

---

### Task 1: Domain 1 — Unit Tests (Core & State)

**Files:**
- `tests/unit/test_types.py`
- `tests/unit/test_envelope.py`
- `tests/unit/test_pipeline_state.py`
- `tests/unit/test_pipeline_rollback.py`
- `tests/unit/test_snapshot.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods in these files.

- [ ] **Step 2: Standardize payloads with JSONDict**
Import `JSONDict` from `relay.types`. Replace `dict`, `dict[str, Any]`, and untyped `{}` with `JSONDict`.
Example: `payload: JSONDict = {"key": "value"}`.

- [ ] **Step 3: Fix union-attr and misc errors**
Add `isinstance` checks for `Result` objects or use `cast` sparingly.

- [ ] **Step 4: Verify with mypy and pytest**
Run: `python -m mypy <files> --strict`
Run: `python -m pytest <files>`

- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_types.py tests/unit/test_envelope.py tests/unit/test_pipeline_state.py tests/unit/test_pipeline_rollback.py tests/unit/test_snapshot.py
git commit -m "test: resolve mypy errors in Core & State unit tests"
```

---

### Task 2: Domain 2 — Unit Tests (Execution & Budget)

**Files:**
- `tests/unit/test_pipeline.py`
- `tests/unit/test_context_broker.py`
- `tests/unit/test_budget.py`
- `tests/unit/test_validator.py`
- `tests/unit/test_slicer.py`

- [ ] **Step 1: Add return type annotations**
Add `-> None` to all methods.

- [ ] **Step 2: Standardize payloads with JSONDict**
Use `JSONDict` for all mock data. Fix `dict` variance issues by using `Mapping` or `JSONDict`.

- [ ] **Step 3: Fix complex mocking issues**
In `test_pipeline.py`, ensure `@patch` and fixtures are correctly typed. Fix accesses to private `_state` and `_snapshot_store` by adding `# type: ignore[attr-defined]` ONLY where internal inspection is strictly required for the test, or better, refactor to public APIs if possible.

- [ ] **Step 4: Verify with mypy and pytest**
Run: `python -m mypy <files> --strict`
Run: `python -m pytest <files>`

- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_pipeline.py tests/unit/test_context_broker.py tests/unit/test_budget.py tests/unit/test_validator.py tests/unit/test_slicer.py
git commit -m "test: resolve mypy errors in Execution & Budget unit tests"
```

---

### Task 3: Domain 3 — Runner Tests

**Files:**
- `tests/unit/test_runners/conftest.py`
- `tests/unit/test_runners/test_autogen.py`
- `tests/unit/test_runners/test_crewai.py`
- `tests/unit/test_runners/test_langchain.py`
- `tests/unit/test_runners/test_local_model.py`
- `tests/unit/test_runners/test_protocol.py`
- `tests/unit/test_runners/test_raw_sdk.py`
- `tests/unit/test_runners/test_registry.py`

- [ ] **Step 1: Fix conftest.py first**
Ensure common fixtures are strictly typed. Add `from typing import Any` if needed for fixture signatures.

- [ ] **Step 2: Add return type annotations**
Add `-> None` to all test methods.

- [ ] **Step 3: Standardize payloads with JSONDict**
Use `JSONDict` pervasively for runner input/output mocks.

- [ ] **Step 4: Verify with mypy and pytest**
Run: `python -m mypy tests/unit/test_runners/ --strict`
Run: `python -m pytest tests/unit/test_runners/`

- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_runners/
git commit -m "test: resolve mypy errors in runner unit tests"
```

---

### Task 4: Domain 4 — Integration & Parallel Tests

**Files:**
- `tests/unit/test_parallel/conftest.py`
- `tests/unit/test_parallel/test_fork_runner.py`
- `tests/unit/test_parallel/test_join.py`
- `tests/unit/test_parallel/test_types.py`
- `tests/integration/test_parallel_pipeline.py`
- `tests/integration/test_pipeline_integration.py`
- `tests/integration/test_runners_integration.py`

- [ ] **Step 1: Fix conftest.py and types**
Add return type annotations and fix `Any` usage in fixtures.

- [ ] **Step 2: Resolve parallel execution typing**
Parallel tests often involve `asyncio.Future` and `Coroutine` types. Ensure these are correctly annotated.

- [ ] **Step 3: Standardize integration payloads**
Ensure integration test payloads use `JSONDict`.

- [ ] **Step 4: Verify with mypy and pytest**
Run: `python -m mypy <files> --strict`
Run: `python -m pytest <files>`

- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_parallel/ tests/integration/
git commit -m "test: resolve mypy errors in integration and parallel tests"
```

---

### Task 5: Global Verification

- [ ] **Step 1: Final mypy check**
Run: `python -m mypy tests --strict`
Expected: **Success: no issues found**

- [ ] **Step 2: Final pytest check**
Run: `python -m pytest tests/`
Expected: All tests PASS.

- [ ] **Step 3: Final Commit**
```bash
git commit --allow-empty -m "test: achieve 0 mypy errors in full test suite"
```
