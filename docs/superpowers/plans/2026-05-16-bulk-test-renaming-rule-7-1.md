# Bulk Test Renaming Implementation Plan (Rule 7.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename 137 violating test names to follow Rule 7.1: "test names must be full sentences, not noun phrases" using the format `test_<behavior>_when_<condition>` or `test_<component>_<behavior>`.

**Architecture:** Use subagents to process test files in batches, renaming violating tests and verifying with `scripts/check_test_names.py`.

**Tech Stack:** Python, pytest, regex for renaming.

---

### Task 1: Rename Integration Tests

**Files:**
- Modify: `tests/integration/test_parallel_pipeline.py`
- Modify: `tests/integration/test_pipeline_integration.py`

- [ ] **Step 1: Rename violations in test_parallel_pipeline.py**
- [ ] **Step 2: Rename violations in test_pipeline_integration.py**
- [ ] **Step 3: Verify with script**
Run: `python scripts/check_test_names.py`
Expected: Violations in these files are gone.
- [ ] **Step 4: Commit**
```bash
git add tests/integration/*.py
git commit -m "test: rename integration tests to sentence format (Rule 7.1)"
```

### Task 2: Rename Core Unit Tests (Budget, Context Broker, Envelope)

**Files:**
- Modify: `tests/unit/test_budget.py`
- Modify: `tests/unit/test_context_broker.py`
- Modify: `tests/unit/test_envelope.py`

- [ ] **Step 1: Rename violations in test_budget.py**
- [ ] **Step 2: Rename violations in test_context_broker.py**
- [ ] **Step 3: Rename violations in test_envelope.py**
- [ ] **Step 4: Verify with script**
- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_budget.py tests/unit/test_context_broker.py tests/unit/test_envelope.py
git commit -m "test: rename core unit tests to sentence format (Rule 7.1)"
```

### Task 3: Rename Pipeline Unit Tests (Pipeline, Rollback, State)

**Files:**
- Modify: `tests/unit/test_pipeline.py`
- Modify: `tests/unit/test_pipeline_rollback.py`
- Modify: `tests/unit/test_pipeline_state.py`

- [ ] **Step 1: Rename violations in test_pipeline.py**
- [ ] **Step 2: Rename violations in test_pipeline_rollback.py**
- [ ] **Step 3: Rename violations in test_pipeline_state.py**
- [ ] **Step 4: Verify with script**
- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_pipeline.py tests/unit/test_pipeline_rollback.py tests/unit/test_pipeline_state.py
git commit -m "test: rename pipeline unit tests to sentence format (Rule 7.1)"
```

### Task 4: Rename Utility Unit Tests (Slicer, Snapshot, Types)

**Files:**
- Modify: `tests/unit/test_slicer.py`
- Modify: `tests/unit/test_snapshot.py`
- Modify: `tests/unit/test_types.py`

- [ ] **Step 1: Rename violations in test_slicer.py**
- [ ] **Step 2: Rename violations in test_snapshot.py**
- [ ] **Step 3: Rename violations in test_types.py**
- [ ] **Step 4: Verify with script**
- [ ] **Step 5: Commit**
```bash
git add tests/unit/test_slicer.py tests/unit/test_snapshot.py tests/unit/test_types.py
git commit -m "test: rename utility unit tests to sentence format (Rule 7.1)"
```

### Task 5: Rename Validator Unit Tests

**Files:**
- Modify: `tests/unit/test_validator.py`

- [ ] **Step 1: Rename violations in test_validator.py** (Note: 24 violations)
- [ ] **Step 2: Verify with script**
- [ ] **Step 3: Commit**
```bash
git add tests/unit/test_validator.py
git commit -m "test: rename validator unit tests to sentence format (Rule 7.1)"
```

### Task 6: Rename Domain-Specific Unit Tests (Parallel, Runners)

**Files:**
- Modify: `tests/unit/test_parallel/test_fork_runner.py`
- Modify: `tests/unit/test_parallel/test_types.py`
- Modify: `tests/unit/test_runners/test_crewai.py`
- Modify: `tests/unit/test_runners/test_local_model.py`
- Modify: `tests/unit/test_runners/test_protocol.py`
- Modify: `tests/unit/test_runners/test_registry.py`

- [ ] **Step 1: Rename violations in tests/unit/test_parallel/**
- [ ] **Step 2: Rename violations in tests/unit/test_runners/**
- [ ] **Step 3: Verify with script**
- [ ] **Step 4: Commit**
```bash
git add tests/unit/test_parallel/*.py tests/unit/test_runners/*.py
git commit -m "test: rename domain unit tests to sentence format (Rule 7.1)"
```

### Task 7: Final Global Validation

- [ ] **Step 1: Run global validation**
Run: `python scripts/check_test_names.py`
Expected: 0 violations found.
- [ ] **Step 2: Run all tests to ensure no breakage**
Run: `pytest`
Expected: All tests pass.
