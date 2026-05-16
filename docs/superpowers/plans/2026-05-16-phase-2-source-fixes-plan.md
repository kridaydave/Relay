# Phase 2 — Source Code Bug Fixes & Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve source code bugs, harden adapter immutability, and clean up technical debt.

**Architecture:** Systematic resolution of audit-identified issues in slicers, runners, and core pipeline. Focus on determinism and immutability.

**Tech Stack:** Python 3.12, mypy, pytest.

---

### Task 1: Deterministic Sorting in RecencySlicePacker

**Files:**
- Modify: `src/relay/slicer/packers.py`
- Test: `tests/unit/test_slicer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_recency_packer_sorting_is_deterministic_without_suffixes():
    from relay.slicer.packers import RecencySlicePacker
    from relay.slicer.manifest import AgentManifest
    from relay.types import Success
    
    packer = RecencySlicePacker()
    # Sections without suffixes should sort by key name as tie-breaker
    payload = {"b": "val_b", "a": "val_a", "c": "val_c"}
    manifest = AgentManifest(agent_id="test", reads=set(payload.keys()))
    
    result = packer.pack(payload, manifest)
    assert isinstance(result, Success)
    # With tie-breaker 'c' > 'b' > 'a' (reverse=True)
    assert list(result.value.keys()) == ["c", "b", "a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_slicer.py -v`
Expected: FAIL (or potentially PASS by luck, but we want to guarantee it)

- [ ] **Step 3: Update RecencySlicePacker sorting logic**

```python
def _recency_sort_key(k: str) -> tuple[int, int, str]:
    if "_" in k and k.split("_")[-1].isdigit():
        return (0, int(k.split("_")[-1]), k)
    return (1, 0, k)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_slicer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/relay/slicer/packers.py tests/unit/test_slicer.py
git commit -m "fix(slicer): ensure RecencySlicePacker sorting is deterministic"
```

---

### Task 2: Harden LocalModelAdapter (Frozen)

**Files:**
- Modify: `src/relay/runners/local_model.py`
- Test: `tests/unit/test_runners/test_local_model.py`

- [ ] **Step 1: Write the failing test for frozen state**

```python
import pytest
from dataclasses import FrozenInstanceError
from relay.runners.local_model import LocalModelAdapter

def test_local_model_adapter_is_frozen():
    adapter = LocalModelAdapter(base_url="http://localhost", model="gpt-3.5-turbo")
    with pytest.raises(FrozenInstanceError):
        adapter.base_url = "http://other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runners/test_local_model.py -v`
Expected: FAIL (AttributeError or Success if not frozen)

- [ ] **Step 3: Make LocalModelAdapter frozen and use object.__setattr__**

```python
@dataclass(frozen=True)
class LocalModelAdapter:
    # ...
    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runners/test_local_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/relay/runners/local_model.py tests/unit/test_runners/test_local_model.py
git commit -m "refactor(runners): make LocalModelAdapter frozen and handle base_url stripping safely"
```

---

### Task 3: Dead Import Cleanup

**Files:**
- Modify: `src/relay/runners/raw_sdk.py`
- Modify: `src/relay/slicer/providers.py`
- Modify: `src/relay/core_pipeline.py`

- [ ] **Step 1: Clean up raw_sdk.py**
Remove unused `Any` from imports.

- [ ] **Step 2: Clean up providers.py**
Remove unused `Any` from imports.

- [ ] **Step 3: Clean up core_pipeline.py**
Verify `Any` usage. If `Any` is only used for `*args: Any` or similar, consider keeping or replacing with `object`. If entirely unused, remove.

- [ ] **Step 4: Verify with mypy**
Run: `python -m mypy src/relay --strict`
Expected: SUCCESS

- [ ] **Step 5: Commit**

```bash
git add src/relay/runners/raw_sdk.py src/relay/slicer/providers.py src/relay/core_pipeline.py
git commit -m "chore: remove dead imports from source files"
```
