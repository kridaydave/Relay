# Phase 1: SnapshotStore Protocol Extraction — Execution Research

**Researched:** 2026-05-17
**Domain:** Protocol extraction, type-safe refactoring, dependency injection
**Confidence:** HIGH

## Summary

Phase 1 refactors SnapshotStore into a @runtime_checkable Protocol with two concrete implementations (LocalFileSnapshotStore, InMemorySnapshotStore) and wires optional injection into CoreRelayPipeline. The codebase is in excellent shape: mypy --strict passes cleanly on all 28 source files, and all 92 unit tests pass. The existing Protocol patterns (AgentRunner, TokenCounter, Closeable) provide clear blueprints. However, the three plans have a **genuine ordering gap**: Plan 01-01-C updates `core_pipeline.py` to import the Protocol, but `__post_init__` still calls `SnapshotStore(storage_path=...)` which will fail because a Protocol cannot be instantiated. The test patch target `relay.core_pipeline.SnapshotStore` also becomes a dead patch after the refactor. Both issues are fixable — the research identifies exactly what to adjust.

---

## Current State

| Check | Result |
|-------|--------|
| **mypy --strict src/relay** | ✅ No issues in 28 source files |
| **mypy tests (permissive)** | ✅ `[mypy-tests.*]` exempts tests from `disallow_any_expr` and `disallow_any_decorated` |
| **pytest snapshot** | ✅ 48/48 passed |
| **pytest pipeline** | ✅ 34/34 passed |
| **pytest rollback** | ✅ 4/4 passed |
| **Total** | ✅ **92/92 passed in 2.19s** |

**Platform:** Python 3.14.2, pytest 9.0.3, Windows x64
**Config:** `mypy.ini` with `strict = True`, `pyproject.toml` for setuptools and pytest

### mypy.ini Key Settings
```
strict = True
warn_return_any = True
disallow_untyped_defs = True
disallow_any_expr = True
disallow_any_decorated = True
follow_imports = normal
ignore_missing_imports = False
```
Tests excluded from `disallow_any_expr` and `disallow_any_decorated`. `token_counter.py` and `runners/local_model.py` also have partial exemptions.

---

## Code Patterns Verified

### Existing Protocol Patterns (Verified by reading actual code)

| File | Protocol | `@runtime_checkable` | Extends | Methods |
|------|----------|---------------------|---------|---------|
| `runners/protocol.py:70` | `AgentRunner` | ✅ Yes | `Protocol` | `async run(slice, manifest) -> AgentOutput` |
| `budget/token_counter.py:13` | `TokenCounter` | ✅ Yes | `Protocol` | `count(text) -> int`, `close() -> None` |
| `types.py:19` | `Closeable` | No (no decorator) | `Protocol` | `close() -> None` |

**Key observation:** `Closeable` in `types.py` is NOT decorated with `@runtime_checkable`. It's a plain `Protocol`. This means `isinstance(obj, Closeable)` will NOT work automatically — structural subtypes need `@runtime_checkable` on the protocol. The `SnapshotStore` Protocol (which extends both `Closeable` and `Protocol`) only gets `isinstance` checkability from its own `@runtime_checkable` decorator, not from `Closeable`.

**Proven:** `isinstance(InMemorySnapshotStore(), Closeable)` will work because `SnapshotStore` is `@runtime_checkable` — when `isinstance` checks `SnapshotStore(Closeable, Protocol)`, it checks whether the instance satisfies the full protocol, which includes the `close()` method. The `Closeable` base doesn't need its own decorator for this to work.

### Missing Protocol Pattern: Module docstrings

Module docstrings follow a strict three-line format (summary, `Owns:`, `Does NOT:`). Every protocol file needs this.

### Optional Injection Pattern (core_pipeline.py)

`token_counter`, `slice_packer`, `registry` all use the pattern:
```python
field_name: Type | None = None
```
Then in `__post_init__`:
```python
if self.field_name is not None:
    self._private_field = self.field_name
else:
    self._private_field = DefaultType(...)
```

### Test Double Pattern (conftest.py)

`FixedCounter` and `FixedEmbeddingProvider` are `@dataclass` with minimal logic, no Protocol/abstract inheritance. `InMemorySnapshotStore` should follow this same structural subtyping pattern.

---

## Discrepancies Found

### 🔴 DISCREPANCY 1: Plan 01-01-C breaks `core_pipeline.py` (HIGH severity)

**What the plan says (Plan 01-01-C):**
> - Change `from relay.snapshot import SnapshotStore` → `from relay.snapshot_protocol import SnapshotStore`

**What happens after:** `__post_init__` line 112 still reads:
```python
self._snapshot_store = SnapshotStore(storage_path=self.storage_path)
```
But `SnapshotStore` is now the Protocol — it cannot be instantiated. This will fail at: (a) runtime with `TypeError: Protocol can't be instantiated directly`, (b) mypy with `Cannot instantiate protocol class`.

**Fix required in Plan 01-01-C:** Also import `LocalFileSnapshotStore` from `relay.snapshot` and update `__post_init__`:
```python
from relay.snapshot import LocalFileSnapshotStore
from relay.snapshot_protocol import SnapshotStore

# In __post_init__:
self._snapshot_store: SnapshotStore = LocalFileSnapshotStore(storage_path=self.storage_path)
```

**Mitigation in Plans:** The current ordering means `core_pipeline.py` will be broken between Plan 01-01 and Plan 01-03. The verification step in Plan 01-01 would fail. Add `LocalFileSnapshotStore` import + update `__post_init__` within Plan 01-01-C.

### 🟡 DISCREPANCY 2: Test patch target becomes stale (MEDIUM severity)

**What the plan says (Plan 01-01-D):**
> `patch("relay.core_pipeline.SnapshotStore")` — this patch path stays the same

**Reality:** After Plan 01-03-A updates `__post_init__` to construct `LocalFileSnapshotStore(...)` instead of `SnapshotStore(...)`, the patch target `relay.core_pipeline.SnapshotStore` intercepts nothing. The test at `test_pipeline.py:351` would no longer mock the store construction.

**Fix required:** Change the patch target to `relay.core_pipeline.LocalFileSnapshotStore`. This change belongs in Plan 01-03-B (when wiring tests are added), or in Plan 01-01-D if the `__post_init__` is also fixed in Plan 01-01.

**Dependency:** This fix depends on DISCREPANCY 1 being resolved first.

### 🟢 DISCREPANCY 3: Plan 01-02 `InMemorySnapshotStore` uses private import (LOW severity)

**What the plan says (Plan 01-02):**
> Import `_extract_step_from_snapshot_id` from `relay.snapshot` for index sorting.

**Reality:** The function is prefixed with `_` (private). While this works within a package (cross-module private access is Python convention, not enforcement), it's a subtle code smell. The plan should either:
- Factor `_extract_step_from_snapshot_id` out of `snapshot.py` into a shared utils module (too heavy for this phase)
- Duplicate the logic in `InMemorySnapshotStore` (trivial — 6 lines)
- Keep the import as-is (acceptable but note the convention)

**Recommendation:** Keep the import — it's well-established within-package convention and avoids code duplication. The `_` prefix is a soft convention, not a hard boundary.

### 🟢 DISCREPANCY 4: Plan 01-02 error code gap (LOW severity)

**What the plan says:** `InMemorySnapshotStore.save_snapshot` returns `Failure(INVALID_PIPELINE_ID)` on invalid pipeline_id.

**What `LocalFileSnapshotStore` actually does:** Same — validates `envelope.pipeline_id` against `PIPELINE_ID_PATTERN` and returns `Failure(code=ErrorCode.INVALID_PIPELINE_ID)`.

**Observation:** The plan's acceptance criteria mention `INVALID_SNAPSHOT_ID` for `load_snapshot` and `SNAPSHOT_NOT_FOUND` for missing IDs. This matches `LocalFileSnapshotStore`. ✅

---

## Risks & Unknowns

### Risk 1: Patch target lifetime management

The `test_pipeline.py` patch `relay.core_pipeline.SnapshotStore` (line 351) has a tricky lifecycle:
1. Before Plan 01-01: patches the concrete class constructor
2. After Plan 01-01-C (with fix): `__post_init__` uses `LocalFileSnapshotStore(...)`, so the patch still targets the wrong thing
3. After Plan 01-03-A: `__post_init__` conditionally creates `LocalFileSnapshotStore(...)` — patch still wrong
4. After Plan 01-03-B: patch should now target `relay.core_pipeline.LocalFileSnapshotStore`

**Mitigation:** Handle this in Plan 01-03-B when writing pipeline wiring tests. Or fix earlier in Plan 01-01-D if we also fix `__post_init__` there.

### Risk 2: `@runtime_checkable` with generic protocols

mypy with `strict = True` + `warn_return_any = True` can be finicky about `isinstance` checks against `@runtime_checkable` protocols that use `Generic[T]`. The plan specifies `SnapshotStore` is NOT generic — it uses concrete types in method signatures. This avoids the issue. ✅

### Risk 3: No `AsyncMock` compatibility concern

The `SnapshotStore` Protocol has no async methods. `LocalFileSnapshotStore` and `InMemorySnapshotStore` are both sync. No risk here. ✅

### Risk 4: Circular import possibility

**Import chain after refactor:**
- `snapshot_protocol.py` → `relay.envelope` → `relay.budget.token_counter` → (stdlib)
- `snapshot_protocol.py` → `relay.types` → (stdlib)
- `snapshot.py` (LocalFileSnapshotStore) → `relay.envelope`, `relay.types`
- `core_pipeline.py` → `relay.snapshot_protocol` (SnapshotStore) + `relay.snapshot` (LocalFileSnapshotStore)
- `pipeline_rollback.py` → `relay.snapshot_protocol`
- `__init__.py` → `relay.snapshot_protocol` + `relay.snapshot` + `relay.snapshot_in_memory`

No circular import risk identified. The Protocol module (`snapshot_protocol.py`) imports only from `relay.envelope` and `relay.types`, which do not import from `relay.snapshot` or `relay.snapshot_protocol`. ✅

### Risk 5: mypy strictness with `@runtime_checkable` + inheritance

Using `class SnapshotStore(Closeable, Protocol)` with `@runtime_checkable`:
- `Closeable` is not `@runtime_checkable` itself — this is fine because `SnapshotStore` carries the decorator
- `isinstance(x, SnapshotStore)` checks for all methods from both `Closeable` and `SnapshotStore`
- mypy's `disallow_any_expr` may flag `isinstance(x, SnapshotStore)` as an error since `SnapshotStore` uses generic-free signatures (all concrete types) → should be clean

Confirmed by inspecting `TokenCounter` pattern: `TokenCounter(Protocol)` with `@runtime_checkable` — no isinstance issues in existing codebase. ✅

---

## Key Findings by Plan

### Plan 01-01: Extract Protocol + Rename (Requirements STO-01, STO-02)

**Files modified:** 7 source + 3 test files
**Risk level:** LOW with fix to Discrepancy 1

**File-level change map:**

| File | Change | Status |
|------|--------|--------|
| `src/relay/snapshot_protocol.py` | NEW — Protocol file | ✅ Clean |
| `src/relay/snapshot.py` | Rename class, add `close()`, update `__all__` | ✅ Clean |
| `src/relay/core_pipeline.py` | Import `SnapshotStore` from `snapshot_protocol` + **need `LocalFileSnapshotStore` import** | 🛑 Discrepancy 1 |
| `src/relay/pipeline_rollback.py` | Import `SnapshotStore` from `snapshot_protocol` | ✅ Clean |
| `src/relay/__init__.py` | Import Protocol + `LocalFileSnapshotStore` | ✅ Clean |
| `tests/unit/test_snapshot.py` | Use `LocalFileSnapshotStore` | ✅ Clean |
| `tests/unit/test_pipeline.py` | Patch target issue | 🟡 Discrepancy 2 |
| `tests/unit/test_pipeline_rollback.py` | Import `SnapshotStore` from `snapshot_protocol` | ✅ Clean — inline imports, verified content |

**Snapshot ID format** (verified from actual code):
```
{pipeline_id}@{step}_{uuid4 hex[:12]}
Example: pipeline-123@1_a1b2c3d4e5f6
Regex: ^[a-zA-Z0-9_-]{1,128}@\d+_[a-f0-9]{12}$
```

### Plan 01-02: Create InMemorySnapshotStore (Requirement STO-03)

**Files modified:** 1 new + 1 existing
**Risk level:** LOW

**Key considerations:**
- `InMemorySnapshotStore` is NOT decorated with `@runtime_checkable` or `@dataclass` — pure structural subtyping
- Must implement all 5 Protocol methods with matching signatures
- Must generate snapshot IDs in the same format as `LocalFileSnapshotStore`
- Error codes must match: `INVALID_PIPELINE_ID`, `INVALID_SNAPSHOT_ID`, `SNAPSHOT_NOT_FOUND`, `PIPELINE_NOT_FOUND`, `NO_SNAPSHOTS`
- `close()` clears all internal state (dict clear, not None assignment)
- The plan mentions `_validate_pipeline_id` helper — simpler to inline the check like `LocalFileSnapshotStore` does

### Plan 01-03: Wire Injection (Requirement STO-04)

**Files modified:** 1 source + 1 test
**Risk level:** LOW

**Key considerations:**
- `storage_path` field becomes advisory when `snapshot_store` is provided — document this
- `close()` must call `self._snapshot_store.close()` unconditionally (not just when injected)
- The `create()` factory needs the new parameter — match existing pattern with `token_counter`, `slice_packer`, `registry`
- New tests needed for: default construction, custom injection, factory forwarding, close delegation

---

## Execution Order Confirmation

The order **01-01 → 01-02 → 01-03** is architecturally correct but needs adjustment within Plan 01-01:

### Corrected execution flow

```
01-01-A: Create snapshot_protocol.py (Protocol file)
01-01-B: Rename SnapshotStore → LocalFileSnapshotStore + add close()
01-01-C: Update consumer imports:
         - core_pipeline: import SnapshotStore (Protocol) + LocalFileSnapshotStore (concrete)
                         → UPDATE __post_init__ to use LocalFileSnapshotStore 
                         → [CRITICAL FIX: otherwise core_pipeline is broken]
         - pipeline_rollback: import SnapshotStore from snapshot_protocol
         - __init__.py: import both
01-01-D: Update tests (patch target unchanged for now — still broken until 01-03)
01-01-E: Add Protocol acceptance test
-------------------------------
01-02-A: Create InMemorySnapshotStore
01-02-B: Export from __init__.py
01-02-C: Write InMemorySnapshotStore tests
-------------------------------
01-03-A: Add snapshot_store field + update __post_init__ + update close() + update create()
01-03-B: Write pipeline wiring tests
         → [FIX DISCREPANCY 2: update patch target to LocalFileSnapshotStore]
```

**Verification gating:** After Plan 01-01-C (with fix), `mypy --strict src/relay` and `pytest tests/unit/test_pipeline.py` should both pass. After Plan 01-02, all 92 existing + new InMemorySnapshotStore tests must pass. After Plan 01-03, all existing + 4+ new wiring tests must pass.

---

## Existing Test Patch Details (test_pipeline.py:351)

```python
with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
     patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next, \
     patch("relay.core_pipeline.SnapshotStore") as mock_store_cls:
```

After Plan 01-03-A, `__post_init__` constructs `LocalFileSnapshotStore(storage_path=...)`, not `SnapshotStore(...)`. The patch target must change to `relay.core_pipeline.LocalFileSnapshotStore`. Additionally, since `LocalFileSnapshotStore` now needs arguments, `mock_store_cls.return_value = mock_store` still works (it intercepts the constructor call).

---

## Import Reference (Current + After Refactor)

### Current import map

| File | Import |
|------|--------|
| `core_pipeline.py:29` | `from relay.snapshot import SnapshotStore` |
| `pipeline_rollback.py:8` | `from relay.snapshot import SnapshotStore` |
| `__init__.py:15` | `from relay.snapshot import SnapshotStore` |
| `test_snapshot.py:13` | `from relay.snapshot import SNAPSHOT_ID_PATTERN, SnapshotStore, InvalidSnapshotIdError, _extract_step_from_snapshot_id` |
| `test_pipeline.py:351` | `patch("relay.core_pipeline.SnapshotStore")` |
| `test_pipeline_rollback.py:42,55,68,81` | `from relay.snapshot import SnapshotStore` (inline inside test methods) |

### Target import map (after Phase 1)

| File | Import |
|------|--------|
| `core_pipeline.py` | `from relay.snapshot_protocol import SnapshotStore` / `from relay.snapshot import LocalFileSnapshotStore` |
| `pipeline_rollback.py` | `from relay.snapshot_protocol import SnapshotStore` |
| `__init__.py` | `from relay.snapshot_protocol import SnapshotStore` / `from relay.snapshot import LocalFileSnapshotStore` / `from relay.snapshot_in_memory import InMemorySnapshotStore` |
| `test_snapshot.py` | `from relay.snapshot import LocalFileSnapshotStore, SNAPSHOT_ID_PATTERN, ...` / `from relay.snapshot_protocol import SnapshotStore` |
| `test_pipeline.py` | `patch("relay.core_pipeline.LocalFileSnapshotStore")` (after Plan 01-03) |
| `test_pipeline_rollback.py` | `from relay.snapshot_protocol import SnapshotStore` |
| `test_snapshot_in_memory.py` (NEW) | `from relay.snapshot_protocol import SnapshotStore` / `from relay.snapshot_in_memory import InMemorySnapshotStore` / `from relay.types import Closeable` |

---

## Pre-Flight Checklist for Execution

- [ ] **Plan 01-01-C fix**: Import `LocalFileSnapshotStore` and update `__post_init__` BEFORE importing Protocol
- [ ] **Plan 01-01-D aware**: Test patch `relay.core_pipeline.SnapshotStore` will survive Plan 01-01 but break in Plan 01-03
- [ ] **Plan 01-03-B fix**: Patch target changes to `relay.core_pipeline.LocalFileSnapshotStore`
- [ ] **Verify mypy after each plan**: `python -m mypy --strict src/relay` must pass after each plan
- [ ] **Full test suite after each plan**: `pytest tests/unit/ -v` must pass after each plan
- [ ] **Closeable**: No `@runtime_checkable` decorator on `Closeable` in `types.py` — this is intentional and correct (SnapshotStore's decorator handles the isinstance check)
- [ ] **`__init__.py` export order**: Keep `SnapshotStore` (Protocol) as the primary export name; add `LocalFileSnapshotStore` and `InMemorySnapshotStore` alongside

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `mypy --strict` will accept `isinstance(x, SnapshotStore)` where SnapshotStore extends `Closeable(Protocol)` without `@runtime_checkable` | Risks | Protocol check may fail on some mypy versions — verify immediately after Plan 01-01 |
| A2 | `cast(SnapshotStore, mock_store)` works for MagicMock when SnapshotStore is a Protocol | Discrepancies | Structural subtyping with MagicMock is well-defined; `cast` is a no-op at runtime anyway |
| A3 | No other code in the repo references `relay.snapshot.SnapshotStore` beyond the files listed | Import Reference | Grep for `from relay.snapshot import SnapshotStore` and `relay.snapshot.SnapshotStore` to confirm |

---

## Open Questions

1. **Can Plan 01-01 verification pass without fixing Discrepancy 1?**
   - **No.** Plan 01-01-C breaks `core_pipeline.py` because `SnapshotStore` becomes a Protocol. The mypy check fails on `SnapshotStore(storage_path=...)`. Fix is required within Plan 01-01-C.

2. **Should the `test_pipeline.py` patch fix happen in Plan 01-01-D or Plan 01-03-B?**
   - **Plan 01-01-D** (if `__post_init__` is also fixed in Plan 01-01-C to use `LocalFileSnapshotStore`)
   - **Plan 01-03-B** (if `__post_init__` fix is deferred to Plan 01-03-A)
   - **Recommendation:** Fix in Plan 01-01-D alongside the `__post_init__` fix — keeps each plan self-verifying.

---

**Ready for planning.** Plan 01-01 needs a minor adjustment (import `LocalFileSnapshotStore` in `core_pipeline.py` + update `__post_init__`). After that fix, all three plans execute cleanly in order.
