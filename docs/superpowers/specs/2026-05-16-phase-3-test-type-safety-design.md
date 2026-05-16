# Design: Phase 3 — Test Type Safety (Large Scale)

**Date:** 2026-05-16
**Status:** Draft

## 1. Overview
This phase resolves 751 mypy errors in the test suite by enforcing strict typing rules (Rule 2.1). The goal is to achieve 0 mypy errors in `tests/` without using `# type: ignore` or other suppressions.

## 2. Component Designs

### 2.1 Standardized Test Method Annotations
**Problem:** Most test methods lack return type annotations, triggering `no-untyped-def`.
**Solution:** Add `-> None` to all test methods across the suite.

### 2.2 Standardized Mock Payloads (`JSONDict`)
**Problem:** Pervasive use of `dict`, `dict[str, Any]`, or un-typed `{}` triggers `misc` errors (Any usage) and `type-arg` errors (missing generics).
**Solution:** 
1. Import `JSONDict` from `relay.types` in test files.
2. Use `JSONDict` for all payload variables and mock data.
3. Explicitly type empty dictionaries: `payload: JSONDict = {}`.

### 2.3 Type Narrowing & Safety
**Problem:** `Union` return types (e.g., `Result[T]`) require narrowing before accessing values.
**Solution:**
1. Use `isinstance(result, Success)` or similar guards.
2. Use `cast(Type, value)` from `typing` sparingly for complex mocks.
3. Replace `dict[str, Any]` with `dict[str, object]` (via `JSONDict`) and use `isinstance` when checking nested values.

## 3. Parallel Execution Decomposition
To handle the large volume of files efficiently, the work is split into 4 independent domains:

### Domain 1: Unit Tests (Core & State)
- `tests/unit/test_types.py`
- `tests/unit/test_envelope.py`
- `tests/unit/test_pipeline_state.py`
- `tests/unit/test_pipeline_rollback.py`
- `tests/unit/test_snapshot.py`

### Domain 2: Unit Tests (Execution & Budget)
- `tests/unit/test_pipeline.py`
- `tests/unit/test_context_broker.py`
- `tests/unit/test_budget.py`
- `tests/unit/test_validator.py`
- `tests/unit/test_slicer.py`

### Domain 3: Runner Tests
- `tests/unit/test_runners/*` (all files in this directory)

### Domain 4: Integration & Parallel Tests
- `tests/integration/*` (all files)
- `tests/unit/test_parallel/*` (all files)

## 4. Verification Plan
1. **Mypy**: Each agent must verify its assigned files with `python -m mypy <files> --strict`.
2. **Pytest**: Each agent must run the tests it modified to ensure no regressions: `python -m pytest <files>`.
3. **Full Pass**: Once all agents finish, run `python -m mypy tests --strict` and `python -m pytest tests/` for the final gate.
