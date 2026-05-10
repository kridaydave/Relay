# Relay Codebase Audit Report
**Date:** 7 May 2026
**Reviewer:** Gemini CLI (Gemini 3-1 pro preview)
**Version:** Relay v0.2
**Status:** Fixed  ✅
This report presents a ruthless evaluation of the Relay codebase against the [Unbreakable Coding Rules (v0.2)](../Relay%20Coding%20Rules.txt).

---

## 🏆 What is Good?

- **R2 (No shared mutable state):** Excellent job using `frozen=True` dataclasses and `threading.Lock` in `PipelineState`. State transitions are handled cleanly via explicit copy-and-update patterns.
- **R3 (Type everything):** Annotations are strict and consistent across all layers. Every public function and internal helper is fully typed, which provides a strong foundation for safety.
- **R12 (Commits are atomic):** A cursory review of recent history (per Design Doc) shows a commitment to atomic changes and clear intent.

---

## 🚨 What is Bad? (Rule Violations)

### 1. R4 (Errors are values, not surprises) — CRITICAL VIOLATIONS
This is the most pervasive issue in the codebase. Expected domain failures are currently being handled with exceptions, which contradicts the "Result-not-exception" mandate.
- **`src/relay/types.py`**: Defines `BudgetExceededError`, `HandoffValidationError`, and `ManifestHashMismatchError` as `Exception` classes.
- **`src/relay/validator.py`**: `validate_manifest_boundaries()` explicitly `raises HandoffValidationError` for an expected agent boundary violation.
- **`src/relay/budget/enforcer.py`**: `HardCapEnforcer.check()` raises `BudgetExceededError` and `ValueError`. These are expected budget states, not programmer errors.
- **`src/relay/slicer/packers.py`**: `StructuralSlicePacker` explicitly `raises KeyError` if a declared section is missing. This should be a `Failure`.
- **`src/relay/snapshot.py`**: `_load_index` uses a bare `except Exception: return None`. This swallows programmer errors while returning a confusing `None` value.
- **`src/relay/core_pipeline.py`**: `_apply_manifest_validation` does a bare `except Exception as e:` to force a rollback, catching and swallowing real programmer errors instead of just domain errors.

### 2. R1 & R19 (Responsibility & Docstring Accuracy)
- **Responsibility Mismatch**: `src/relay/context_broker.py` claims to own "cryptographic signing" in its docstring, but the actual implementation of `_sign_envelope` and `_compute_signature` is located in `src/relay/envelope.py`.
- **Lying Docstrings**: `src/relay/snapshot.py` claims it "Does NOT: validate data", yet `_dict_to_envelope` performs extensive structural and type validation on the JSON payload.

### 3. R17 (Approximations must be labelled and benchmarked)
- **`src/relay/envelope.py`**: `_estimate_tokens` correctly labels itself as an approximation but fails to reference the mandatory benchmark test (e.g., `test_envelope.py::test_token_estimate`).
- **`src/relay/slicer/packers.py`**: `RecencySlicePacker` and `RelevanceSlicePacker` use token estimation logic with **zero** documentation, labeling, or benchmark references.

### 4. R16 (Validate at the boundary, trust internally)
- **`src/relay/envelope.py`**: `create_initial_envelope` and `create_next_envelope` take a `secret` argument. Despite a docstring warning against placeholder secrets, the code does not validate the secret's strength or presence, allowing weak or empty keys to produce invalid signatures.

### 5. R14 (Documentation is code)
- **`src/relay/slicer/packers.py`**: Completely missing the mandatory 3-line module docstring and proper class docstrings.

---

## 🛠️ What can we do to fix the bad?

1. **Refactor Exceptions to Result Types (R4)**: 
   - Convert `BudgetExceededError` and `HandoffValidationError` into standard dataclasses or simple error codes.
   - Update `HardCapEnforcer`, `HandoffValidator`, and `SlicePacker` to return `Result` types instead of raising exceptions.
   - Fix `unwrap()` in `types.py` to correctly handle `RollbackSuccess`.

2. **Realignment of Responsibilities (R1)**:
   - Move all signing and envelope creation logic from `envelope.py` into `context_broker.py`. 
   - Update docstrings to reflect the actual ownership: `envelope.py` owns the data model, `context_broker.py` owns the lifecycle and signing.

3. **Label and Benchmark Heuristics (R17)**:
   - Centralize `estimate_tokens` into a utility function with a proper R17-compliant docstring that points to a specific test case in `tests/unit/test_envelope.py`.

4. **Implement Boundary Validation (R16)**:
   - Add a check in `ContextBroker` to ensure the `signing_secret` meets a minimum length (e.g., 32 characters) before allowing any envelopes to be signed.

5. **Complete Missing Documentation (R14)**:
   - Add the missing 3-line module docstrings to all files in the `slicer` and `budget` subdirectories.

---

## 🚀 What can we do to improve the good?

1. **Stricter Payloads**: Change the `payload` type in `ContextEnvelope` from `dict[str, Any]` to `Mapping[str, Any]` (from `collections.abc`) to prevent accidental in-place mutation, even though the dataclass is frozen.
2. **Recursive Validation**: Enhance `validator.py` to perform recursive deep-diffing instead of just top-level key comparison to catch hallucinations buried in nested JSON objects.
