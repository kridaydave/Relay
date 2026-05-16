# Fix Runner Tests Type Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve 78 mypy errors in runner unit tests by adding return type annotations, standardizing on `JSONDict`, and fixing specific type mismatches.

**Architecture:** Surgical application of type hints to test files. Use `JSONDict` from `relay.types` for all dictionary-like payloads. Ensure all test methods return `None`.

**Tech Stack:** Python, mypy, pytest, Relay middleware.

---

### Task 1: Fix conftest.py

**Files:**
- Modify: `tests/unit/test_runners/conftest.py`

- [ ] **Step 1: Add imports and type annotations**

```python
from typing import Any
from relay.types import JSONDict
# ...
def make_test_slice(
    sections: JSONDict | None = None,
    token_count: int = 100,
    step: int = 1,
) -> ContextSlice:
    # ...

def make_test_manifest(
    # ...
) -> AgentManifest:
    # ...
```

- [ ] **Step 2: Commit**

```bash
git add tests/unit/test_runners/conftest.py
git commit -m "test: add type annotations to runner conftest"
```

### Task 2: Fix test_registry.py

**Files:**
- Modify: `tests/unit/test_runners/test_registry.py`

- [ ] **Step 1: Add return type annotations to all test methods**

```python
class TestAdapterRegistryRegister:
    def test_registers_and_retrieves_adapter(self) -> None:
        # ...
```

- [ ] **Step 2: Fix type ignore or casting for invalid runner**

```python
    def test_raises_on_non_runner_object(self) -> None:
        with pytest.raises(ValueError, match="AgentRunner protocol"):
            # cast to AgentRunner to satisfy mypy while testing runtime validation
            from typing import cast
            from relay.runners.protocol import AgentRunner
            AdapterRegistry().register("bad", cast(AgentRunner, object()))
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runners/test_registry.py
git commit -m "test: fix types in test_registry.py"
```

### Task 3: Fix test_protocol.py

**Files:**
- Modify: `tests/unit/test_runners/test_protocol.py`

- [ ] **Step 1: Add return type annotations to all test methods**
- [ ] **Step 2: Use JSONDict where appropriate**

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runners/test_protocol.py
git commit -m "test: fix types in test_protocol.py"
```

### Task 4: Fix test_langchain.py

**Files:**
- Modify: `tests/unit/test_runners/test_langchain.py`

- [ ] **Step 1: Add return type annotations to all test methods**
- [ ] **Step 2: Fix "Expression type contains Any" errors**

```python
    @pytest.mark.asyncio
    async def test_calls_ainvoke_when_available(self) -> None:
        # ...
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runners/test_langchain.py
git commit -m "test: fix types in test_langchain.py"
```

### Task 5: Fix test_crewai.py

**Files:**
- Modify: `tests/unit/test_runners/test_crewai.py`

- [ ] **Step 1: Add return type annotations to all test methods**
- [ ] **Step 2: Fix mock_import signature**

```python
        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            # ...
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runners/test_crewai.py
git commit -m "test: fix types in test_crewai.py"
```

### Task 6: Fix test_local_model.py

**Files:**
- Modify: `tests/unit/test_runners/test_local_model.py`

- [ ] **Step 1: Fix read-only property error**
- [ ] **Step 2: Add return type annotations**

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runners/test_local_model.py
git commit -m "test: fix types in test_local_model.py"
```

### Task 7: Fix remaining runner tests (test_autogen.py, test_raw_sdk.py)

**Files:**
- Modify: `tests/unit/test_runners/test_autogen.py`
- Modify: `tests/unit/test_runners/test_raw_sdk.py`

- [ ] **Step 1: Add return type annotations `-> None` to all test methods**

- [ ] **Step 2: Commit**

```bash
git add tests/unit/test_runners/test_autogen.py tests/unit/test_runners/test_raw_sdk.py
git commit -m "test: fix types in remaining runner tests"
```

### Task 8: Verification

- [ ] **Step 1: Run mypy**

Run: `python -m mypy tests/unit/test_runners/ --strict`
Expected: Success (no errors)

- [ ] **Step 2: Run pytest**

Run: `python -m pytest tests/unit/test_runners/`
Expected: Success (all tests pass)
