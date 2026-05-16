# Design: Phase 2 — Source Code Bug Fixes & Refactoring

**Date:** 2026-05-16
**Status:** Draft

## 1. Overview
This phase addresses specific source code bugs and technical debt identified in the v0.4 audit. The goal is to improve correctness, immutability, and code hygiene.

## 2. Component Designs

### 2.1 Deterministic Sorting in `RecencySlicePacker`
**Problem:** The current `_recency_sort_key` returns `(1, key)` for sections without a numeric suffix. If multiple sections fall into this category, their relative order is dependent on Python's stable sort of the original keys, which might not be consistent if the input dictionary order varies (though Python 3.7+ dicts are ordered).
**Solution:** Modify `_recency_sort_key` to always use the key as a tie-breaker.

```python
def _recency_sort_key(k: str) -> tuple[int, int, str]:
    if "_" in k and k.split("_")[-1].isdigit():
        return (0, int(k.split("_")[-1]), k)
    return (1, 0, k)
```

### 2.2 Frozen `LocalModelAdapter`
**Problem:** `LocalModelAdapter` should be immutable to prevent configuration drift.
**Solution:** 
1. Add `frozen=True` to the `dataclass` decorator.
2. Update `__post_init__` to use `object.__setattr__` for the `base_url` stripping.

```python
@dataclass(frozen=True)
class LocalModelAdapter:
    base_url: str
    model: str
    adapter_name: str = "local_model"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
```

### 2.3 Source Code Hygiene (Dead Imports)
**Problem:** `Any` and `cast` are imported but unused in several files.
**Solution:** Remove unused imports from:
- `src/relay/runners/raw_sdk.py`
- `src/relay/slicer/providers.py`
- `src/relay/core_pipeline.py` (Verify `Any` usage first; it seems to be used in some type hints but I will check if it can be replaced by `object`).

## 3. Verification Plan
1. **Unit Tests**: Run existing unit tests for `RecencySlicePacker` and `LocalModelAdapter`.
2. **Immutability Test**: Add a test case to verify `LocalModelAdapter` is actually frozen.
3. **Mypy**: Run `mypy src/relay --strict` to ensure no new typing regressions.
