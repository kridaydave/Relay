# Relay v0.2 — Implementation Plan

> **Theme:** Make the core loop airtight before expanding surface area.
>
> **Principles:** Determinism over cleverness · Rollback beats repair · Pluggable interfaces for external dependencies

---

## Table of Contents

1. [Overview](#overview)
2. [Module & Class Design](#module--class-design)
3. [Data Model Updates](#data-model-updates)
4. [Step-by-Step Execution Plan](#step-by-step-execution-plan)
5. [Testing Strategy](#testing-strategy)

---

## Overview

v0.2 introduces two new top-level modules — `relay.budget` and `relay.slicer` — and makes targeted modifications to four existing files. No existing public API is removed. The `ContextEnvelope` schema gains one field (`manifest_hash`), and the signature computation is updated to include it.

### New modules

| Module | Purpose |
|---|---|
| `relay.budget` | Hard token cap enforcement before every agent call |
| `relay.slicer` | Pluggable context slicing strategies + agent manifest boundaries |

### Modified files

| File | Change summary |
|---|---|
| `relay/envelope.py` | Add `manifest_hash: str` field |
| `relay/context_broker.py` | Include `manifest_hash` in `_compute_signature` input |
| `relay/validator.py` | Add `validate_manifest_boundaries()` |
| `relay/core_pipeline.py` | Inject budget enforcer and slicer hooks |
| `relay/types.py` | Add `BudgetExceededError`, `HandoffValidationError`, `ManifestHashMismatchError` |

---

## Module & Class Design

### `relay/budget/` — new module

**`relay/budget/token_counter.py`**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

class TiktokenCounter:
    def __init__(self, encoding: str = "cl100k_base"):
        import tiktoken  # lazy import — tiktoken is an optional dep
        self._enc = tiktoken.get_encoding(encoding)

    def count(self, text: str) -> int:
        return len(self._enc.encode(text))
```

`tiktoken` is a lazy import. It is listed as an optional extra (`pip install relay[tiktoken]`), not a hard dependency. Users who bring their own `TokenCounter` implementation never pay for it.

**`relay/budget/enforcer.py`**

```python
@dataclass(frozen=True)
class HardCapEnforcer:
    pipeline_id: str
    counter: TokenCounter

    def check(self, envelope: ContextEnvelope, projected_slice: str) -> None:
        projected_cost = self.counter.count(projected_slice)
        if projected_cost < 0:
            raise ValueError(f"TokenCounter returned negative value: {projected_cost}")
        if envelope.token_budget_used + projected_cost > envelope.token_budget_total:
            raise BudgetExceededError(
                used=envelope.token_budget_used,
                projected=projected_cost,
                limit=envelope.token_budget_total,
                step=envelope.step,
            )
```

`check()` is called **before** the agent call inside `core_pipeline.py`. `token_budget_used` is only updated in the new frozen envelope copy produced **after** successful validation — preserving the immutability invariant.

**`relay/budget/__init__.py`** exports: `HardCapEnforcer`, `TokenCounter`, `TiktokenCounter`.

---

### `relay/slicer/` — new module

**`relay/slicer/strategy.py`**

```python
from enum import Enum, auto

class SliceStrategy(Enum):
    RECENCY    = auto()
    RELEVANCE  = auto()
    STRUCTURAL = auto()
```

**`relay/slicer/manifest.py`**

```python
import hashlib, json
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentManifest:
    agent_id:   str
    reads:      frozenset[str]   # section keys the agent may read
    writes:     frozenset[str]   # section keys the agent may write
    max_tokens: int

    def compute_hash(self) -> str:
        canonical = json.dumps({
            "agent_id":   self.agent_id,
            "reads":      sorted(self.reads),
            "writes":     sorted(self.writes),
            "max_tokens": self.max_tokens,
        }, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
```

`frozenset` fields keep `AgentManifest` hashable and safe as a dict key. `sorted()` inside `compute_hash` ensures determinism across Python sessions — unordered set serialisation is a classic footgun.

**`relay/slicer/providers.py`**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...
```

No concrete implementation ships with Relay. The protocol is the entire contract ("bring your own embedding model").

**`relay/slicer/packers.py`** — three concrete `SlicePacker` implementations:

| Class | Strategy | External deps |
|---|---|---|
| `RecencySlicePacker` | Selects last N sections by `step` order until `max_tokens` consumed | None |
| `StructuralSlicePacker` | Selects only sections named in `AgentManifest.reads` | None |
| `RelevanceSlicePacker` | Ranks sections by cosine similarity to a query; requires injected `EmbeddingProvider` | BYOE |

Cosine similarity in `RelevanceSlicePacker` is implemented inline with no `numpy` dependency (`sum(a*b for a,b in zip(...))`) — appropriate at the scale Relay operates.

**`relay/slicer/__init__.py`** exports: `SliceStrategy`, `AgentManifest`, `EmbeddingProvider`, `RecencySlicePacker`, `RelevanceSlicePacker`, `StructuralSlicePacker`.

---

### Modifications to existing files

**`relay/types.py`** — additions only, no existing types change:

```python
@dataclass(frozen=True)
class BudgetExceededError(RelayError):
    used:      int
    projected: int
    limit:     int
    step:      int

@dataclass(frozen=True)
class HandoffValidationError(RelayError):
    agent_id:          str
    offending_section: str
    step:              int

@dataclass(frozen=True)
class ManifestHashMismatchError(RelayError):
    expected_hash: str
    actual_hash:   str
    step:          int
```

All three are frozen dataclasses inheriting from `RelayError(Exception)`. Structured exceptions over string messages — callers can inspect fields programmatically.

**`relay/validator.py`** — one new function added:

```python
def validate_manifest_boundaries(
    envelope: ContextEnvelope,
    manifest: AgentManifest,
    written_sections: set[str],
) -> None:
    for section in written_sections:
        if section not in manifest.writes:
            raise HandoffValidationError(
                agent_id=manifest.agent_id,
                offending_section=section,
                step=envelope.step,
            )
```

Kept isolated from the existing contradiction/tamper checks already in `validator.py`.

**`relay/core_pipeline.py`** — two injection points:

1. **Pre-call:** `enforcer.check(current_envelope, projected_slice)` before dispatching to the agent.
2. **Post-call:** `validator.validate_manifest_boundaries(new_envelope, manifest, agent_output_keys)` after the agent returns, before committing the new envelope. `token_budget_used` is updated only in the new envelope created at this point.

---

## Data Model Updates

### `relay/envelope.py` — field addition

```python
# Before (v0.1)
@dataclass(frozen=True)
class ContextEnvelope:
    relay_version:     str
    pipeline_id:       str
    step:              int
    timestamp:         datetime
    token_budget_used: int
    token_budget_total: int
    payload:           dict[str, Any]
    signature:         str

# After (v0.2)
@dataclass(frozen=True)
class ContextEnvelope:
    relay_version:      str
    pipeline_id:        str
    step:               int
    timestamp:          datetime
    token_budget_used:  int
    token_budget_total: int
    payload:            dict[str, Any]
    manifest_hash:      str        # ← new
    signature:          str
```

During PRs 1–3, `manifest_hash` carries a backward-compat default of `""` so all existing tests pass without modification. The default is **removed** in PR 5 before tagging v0.2 final.

### `relay/context_broker.py` — updated signature input

The canonical string fed to `_compute_signature` gains `manifest_hash` between `token_budget_total` and the serialised payload. Field order is load-bearing for the hash — document it explicitly in a comment.

```
{relay_version}|{pipeline_id}|{step}|{timestamp.isoformat()}|{token_budget_used}|{token_budget_total}|{manifest_hash}|{json.dumps(payload, sort_keys=True)}
```

---

## Step-by-Step Execution Plan

Five PRs. `main` stays green at every merge.

---

### PR 1 — Exception types + envelope schema

**Goal:** Lay the foundation every downstream PR depends on.

```
feat(types): add BudgetExceededError, HandoffValidationError, ManifestHashMismatchError
feat(envelope): add manifest_hash field with backward-compat default ("")
feat(broker): include manifest_hash in _compute_signature
test: update existing envelope and signature tests
```

**Why first:** All downstream code needs the new exception types and the updated envelope schema. Doing this in one PR means no other PR touches `envelope.py` again. The `""` default keeps the full existing test suite green with zero modifications.

---

### PR 2 — `relay.budget` module

**Goal:** Deliver hard cap enforcement as a self-contained, fully tested unit.

```
feat(budget): add TokenCounter Protocol and TiktokenCounter
feat(budget): add HardCapEnforcer
feat(budget): wire optional tiktoken extra in pyproject.toml
test(budget): unit tests for enforcer and counter
```

**Dependencies:** PR 1 (needs `BudgetExceededError`). No pipeline changes yet — `HardCapEnforcer` is fully testable in isolation with a `FixedCounter` test double.

---

### PR 3 — `relay.slicer` module

**Goal:** Deliver manifests and all three slice strategies as a self-contained, fully tested unit.

```
feat(slicer): add SliceStrategy enum
feat(slicer): add AgentManifest dataclass and compute_hash
feat(slicer): add EmbeddingProvider Protocol
feat(slicer): add RecencySlicePacker
feat(slicer): add StructuralSlicePacker
feat(slicer): add RelevanceSlicePacker (requires EmbeddingProvider injection)
test(slicer): unit tests for all three packers and manifest hashing
```

**Dependencies:** PR 1 only. `relay.slicer` has no dependency on `relay.budget`.

---

### PR 4 — Wire budget + slicer into the pipeline

**Goal:** Connect the two new modules into `core_pipeline.py` and `validator.py`.

```
feat(pipeline): add HardCapEnforcer injection point (pre-call)
feat(pipeline): add manifest boundary validation (post-call)
feat(pipeline): update token_budget_used only after successful validation
feat(validator): add validate_manifest_boundaries function
test(pipeline): integration tests for budget enforcement and boundary violations
```

**Dependencies:** PRs 2 and 3. This is the **only** PR that touches `core_pipeline.py`. Keeping pipeline changes in a single PR makes the integration surface auditable in one review.

---

### PR 5 — Finalise and harden

**Goal:** Remove migration scaffolding, ship the final v0.2 artefacts.

```
feat(envelope): remove manifest_hash backward-compat default (field now required)
docs: update README with v0.2 usage examples
test: add edge case tests (see Testing Strategy)
chore: update CHANGELOG, bump version to 0.2.0
```

**Dependencies:** PR 4. Removing the `""` default turns any lingering test that constructs a bare `ContextEnvelope` into a visible failure that must be fixed — making the migration complete and verifiable.

---

## Testing Strategy

All tests use `pytest`. Test doubles are defined in `conftest.py` — no mocking framework required.

### Shared test doubles (`conftest.py`)

```python
from dataclasses import dataclass

@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""
    value: int
    def count(self, text: str) -> int:
        return self.value

@dataclass
class FixedEmbeddingProvider:
    """EmbeddingProvider that always returns a fixed vector."""
    vector: list[float]
    def embed(self, text: str) -> list[float]:
        return self.vector
```

The `runtime_checkable` Protocol declarations on `TokenCounter` and `EmbeddingProvider` let you assert `isinstance(FixedCounter(5), TokenCounter)` as a sanity check in tests, confirming the protocol is satisfied without any mock library.

---

### Budget enforcement edge cases

**Exact boundary passes.** `token_budget_used + projected == token_budget_total` must pass (condition is strictly greater-than).

```python
def test_hard_cap_exact_boundary_passes():
    envelope = make_envelope(token_budget_used=90, token_budget_total=100)
    enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
    enforcer.check(envelope, "any text")  # must not raise

def test_hard_cap_one_over_raises():
    envelope = make_envelope(token_budget_used=91, token_budget_total=100)
    enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
    with pytest.raises(BudgetExceededError) as exc_info:
        enforcer.check(envelope, "any text")
    assert exc_info.value.step == envelope.step
    assert exc_info.value.used == 91
    assert exc_info.value.limit == 100
```

**Budget does not update on a failed step.** Build a mini pipeline integration test where an agent call raises mid-execution. Assert the envelope at the rollback snapshot has the same `token_budget_used` as before the failed call.

**Zero-token slice passes.** `count()` returns `0`. Enforcer passes regardless of budget state — an empty slice is always legal.

**Negative count raises `ValueError`.** A malformed custom counter returning a negative value must be caught and raised as `ValueError` immediately, before the budget comparison is attempted.

---

### Manifest boundary edge cases

**Write to permitted section — passes.** Agent writes to a section in its `manifest.writes`. Validator is silent.

**Write to forbidden section — raises.** Agent writes to a section not in `manifest.writes`. Assert both `offending_section` and `step` on the raised `HandoffValidationError`, not just the exception type.

**Empty writes set.** An agent with `writes=frozenset()` raises `HandoffValidationError` on any write. This is a valid configuration for a read-only observer agent.

**Writes is a superset of actual output.** Agent is permitted to write sections A, B, C but only writes A. Must pass — the manifest declares capability, not obligation.

**`manifest_hash` mismatch on receive.** Construct an envelope whose `manifest_hash` doesn't match the locally computed hash of the manifest the agent was initialized with. Assert `ManifestHashMismatchError`.

**Signature invalidation when `manifest_hash` changes.** Take a valid envelope, construct a new one with only `manifest_hash` changed but `signature` left identical. Assert the signature check in `context_broker.py` fails. This is the core tamper-detection guarantee for manifests.

---

### Slicer edge cases

**`RecencySlicePacker` — single section exceeds `max_tokens`.** The packer returns an empty slice, not a truncated one, and logs a warning. Never silently truncate context — that violates Relay's determinism principle.

**`StructuralSlicePacker` — `reads` names a section absent from the payload.** Must raise `KeyError` with the missing section name, not silently skip it. Missing declared reads are always a configuration error.

**`RelevanceSlicePacker` — injected provider raises on `embed()`.** The exception propagates unchanged. Relay does not catch or wrap external provider errors.

**`AgentManifest.compute_hash()` is deterministic.** Call it twice on the same object, and again after reconstructing the object from the same arguments. All three results must be identical. Also construct the manifest with sets in different insertion orders — hash must still match.

```python
def test_manifest_hash_deterministic():
    m1 = AgentManifest("a1", frozenset({"x", "y"}), frozenset({"z"}), 1000)
    m2 = AgentManifest("a1", frozenset({"y", "x"}), frozenset({"z"}), 1000)
    assert m1.compute_hash() == m2.compute_hash()
    assert m1.compute_hash() == m1.compute_hash()
```

---

## Directory Structure After v0.2

```
src/relay/
├── __init__.py
├── context_broker.py      # modified: manifest_hash in signature
├── core_pipeline.py       # modified: budget + slicer injection points
├── envelope.py            # modified: + manifest_hash field
├── snapshot.py            # no changes
├── types.py               # modified: + 3 new exception types
├── validator.py           # modified: + validate_manifest_boundaries()
├── budget/
│   ├── __init__.py
│   ├── enforcer.py        # HardCapEnforcer
│   └── token_counter.py   # TokenCounter Protocol + TiktokenCounter
└── slicer/
    ├── __init__.py
    ├── manifest.py        # AgentManifest
    ├── packers.py         # Recency, Structural, Relevance packers
    ├── providers.py       # EmbeddingProvider Protocol
    └── strategy.py        # SliceStrategy enum
```

---

*Relay v0.2 — Implementation Plan · Generated for internal use*