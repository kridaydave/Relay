# Relay v0.1 Implementation Plan

**Created:** May 4, 2026  
**Scope:** Context broker, Handoff validator, Snapshot store with rollback  
**Target:** Minimum viable, production-quality core

---

## Phase 0: Project Skeleton (Day 0)

Before writing any implementation code, establish the physical structure that enforces the coding rules.

```
relay/
├── src/relay/
│   ├── __init__.py
│   ├── envelope.py          # Core data models (first!)
│   ├── context_broker.py    # Layer 1
│   ├── validator.py         # Layer 4
│   ├── snapshot.py          # Layer 5
│   └── types.py             # Shared Result types, errors
├── tests/
│   ├── unit/
│   │   ├── test_envelope.py
│   │   ├── test_context_broker.py
│   │   ├── test_validator.py
│   │   └── test_snapshot.py
│   └── integration/
│       └── test_pipeline.py
├── pyproject.toml
├── mypy.ini
└── .gitignore
```

**Why this structure first:**
- `tests/` mirrors `src/` structure (R5)
- Single source of truth per file (R1)
- `types.py` centralized for Result types (R4) - avoids scattering error handling

**Tooling:**
- `pyproject.toml` with `pytest`, `mypy`, `pydantic`
- `mypy.ini` set to `--strict`
- No code ships until `mypy --strict` passes

---

## Phase 1: Core Data Models (Day 1)

**Design principle:** Humans write interfaces (R9). Define the shape of data before touching any logic.

### 1.1 Envelope (envelope.py)

```python
# Public interface - designed by humans, implemented by AI
@dataclass(frozen=True)
class ContextEnvelope:
    relay_version: str
    pipeline_id: str
    step: int
    timestamp: datetime
    token_budget_used: int
    token_budget_total: int
    payload: dict[str, Any]
    signature: str

# Human-designed contract
def create_envelope(
    pipeline_id: str,
    step: int,
    payload: dict[str, Any],
    token_budget_total: int = 8000
) -> ContextEnvelope: ...

def sign_envelope(envelope: ContextEnvelope, secret: str) -> ContextEnvelope: ...

def verify_signature(envelope: ContextEnvelope, secret: str) -> bool: ...
```

**Why frozen=True (R2):** Immutable after creation. If downstream needs to modify, they create a new envelope - no shared mutable state.

**Why datetime not ISO string (R3):** Type annotations must be precise. `datetime` is better than `str` for timestamp validation.

### 1.2 Result Types (types.py)

```python
# R4: Errors are values, not exceptions
@dataclass(frozen=True)
class Success[T]:
    value: T

@dataclass(frozen=True)
class Failure:
    reason: str
    code: str

Result = Success[T] | Failure
```

**Why this design:** Explicit return types force callers to handle failure cases. No bare `None` returns or exception swallowing.

### 1.3 Module Docstrings (R14)

Every module gets three-line docstring **before** implementation:
- What it does
- What it owns
- What it does NOT do

---

## Phase 2: Context Broker — Layer 1 (Day 2)

**Responsibility:** Normalizes, timestamps, and cryptographically signs context envelope before any agent touches it.

### 2.1 Public Interface

```python
# src/relay/context_broker.py
class ContextBroker:
    """Manages context envelope creation and signing.

    Owns: envelope lifecycle, cryptographic signing.
    Does NOT: validate agent output, persist snapshots, execute agents.
    """

    def create_initial_envelope(
        self,
        pipeline_id: str,
        initial_payload: dict[str, Any],
        token_budget_total: int = 8000
    ) -> Result[ContextEnvelope]: ...

    def create_next_envelope(
        self,
        previous_envelope: ContextEnvelope,
        agent_output: dict[str, Any]
    ) -> Result[ContextEnvelope]: ...
```

### 2.2 Implementation Details

- Uses `secrets` module for SHA256 signing
- Increments step counter automatically
- Calculates token budget from payload size (estimate via `json.dumps` length / 4)
- Timestamp uses UTC always

### 2.3 Tests Required (R5)

- `test_broker_creates_initial_envelope` — happy path
- `test_broker_increments_step_on_next_envelope` — step increment
- `test_broker_updates_token_budget` — budget tracking
- `test_broker_fails_on_invalid_previous_envelope` — failure path

**Test names must describe behaviour (R6):** `test_broker_rolls_back_on_contradiction` NOT `test_broker_4`

---

## Phase 3: Handoff Validator — Layer 4 (Day 3)

**Responsibility:** Runs between every handoff. Detects contradictions, diffs what changed, triggers rollback if needed.

### 3.1 Public Interface

```python
# src/relay/validator.py
class HandoffValidator:
    """Validates agent output and detects corruption.

    Owns: contradiction detection, diff computation, rollback triggering.
    Does NOT: sign envelopes, persist data, execute agents.
    """

    def validate_handoff(
        self,
        previous_envelope: ContextEnvelope,
        current_envelope: ContextEnvelope
    ) -> Result[ValidationResult]: ...

    def should_rollback(self, validation_result: ValidationResult) -> bool: ...

@dataclass(frozen=True)
class ValidationResult:
    has_contradiction: bool
    diff: dict[str, Any]
    contradiction_details: str | None
```

### 3.2 Core Checks

**Hallucination detection:**
- Compare key entity mentions between previous and current payload
- If agent claims to "confirm" something but payload lacks supporting evidence → flag

**Diff inspector:**
- Compute structural diff of payload keys
- Flag if critical keys disappear without explanation
- Track token budget overflow

### 3.3 Rollback Trigger (R4)

Instead of raising exceptions, validator returns `Result[ValidationResult]`. Caller decides:
- If `Failure` → trigger snapshot restore
- If `Success` with `has_contradiction=True` → trigger rollback

### 3.4 Tests Required

- `test_validator_passes_clean_handoff` — happy path
- `test_validator_detects_contradiction` — hallucination caught
- `test_validator_flags_missing_keys` — diff inspection
- `test_validator_triggers_rollback_on_contradiction` — rollback flag

---

## Phase 4: Snapshot Store — Layer 5 (Day 4)

**Responsibility:** Persists every clean checkpoint as immutable JSON. The rollback target.

### 4.1 Public Interface

```python
# src/relay/snapshot.py
class SnapshotStore:
    """Persists and retrieves envelope checkpoints.

    Owns: checkpoint lifecycle, rollback restore, storage cleanup.
    Does NOT: validate data, sign envelopes, execute agents.
    """

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]: ...
    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]: ...
    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]: ...
    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]: ...
```

### 4.2 Storage Design

- Location: `./relay_data/snapshots/{pipeline_id}/{step}_{timestamp}.json`
- Format: Immutable JSON — never overwrite, only append
- Index file: `{pipeline_id}/index.json` tracks all snapshot IDs for fast lookup

### 4.3 Transaction Safety

- Write to temp file first, then atomic rename (filesystem-level transaction)
- On rollback: read from disk, create NEW envelope (R2), do NOT mutate stored JSON

### 4.4 Tests Required

- `test_snapshot_saves_envelope` — happy path
- `test_snapshot_loads_latest` — retrieval
- `test_snapshot_creates_immutable_files` — no overwrites
- `test_snapshot_restores_clean_state` — rollback scenario (R10 edge case)

---

## Phase 5: Integration (Day 5)

**Wiring the three components together:**

```python
# src/relay/pipeline.py
class RelayPipeline:
    """Orchestrates the three core components.

    Owns: pipeline lifecycle, component coordination.
    Does NOT: define agent behavior, manage prompts.
    """

    def __init__(
        self,
        signing_secret: str,
        token_budget: int = 8000
    ): ...

    def execute_step(
        self,
        agent_output: dict[str, Any]
    ) -> Result[ContextEnvelope]: ...

    def rollback(self) -> Result[ContextEnvelope]: ...
```

**Flow:**
1. `ContextBroker` creates/signs envelope
2. `HandoffValidator` checks output
3. If clean → `SnapshotStore` persists checkpoint
4. If dirty → `SnapshotStore` restores last clean state

### Integration Tests (R7: opt-in)

```python
# tests/integration/test_pipeline.py
# Mark with @pytest.mark.integration - skip in unit test runs
def test_full_pipeline_happy_path(): ...
def test_pipeline_rollback_on_contradiction(): ...
```

---

## Phase 6: CI & Quality Gate (Day 6)

```yaml
# .github/workflows/ci.yml
runs-on: ubuntu-latest
steps:
  - run: mypy src/relay --strict
  - run: pytest tests/unit/ -v --cov=src/relay --cov-fail-under=80
  - run: pytest tests/integration/ -v -m integration  # opt-in
```

**Quality gates (R3, R5):**
- `mypy --strict` must pass — no excuses
- Coverage ≥ 80%
- Every public function has a test

---

## Implementation Order Summary

| Day | Component | Files | Public Functions |
|-----|-----------|-------|------------------|
| 0 | Skeleton | `pyproject.toml`, `mypy.ini` | — |
| 1 | Models | `envelope.py`, `types.py` | 3 |
| 2 | Context Broker | `context_broker.py` | 2 |
| 3 | Validator | `validator.py` | 3 |
| 4 | Snapshot | `snapshot.py` | 4 |
| 5 | Integration | `pipeline.py` | 2 |
| 6 | CI | `ci.yml` | — |

**Total public functions to test (R5):** ~14

---

## Key Design Decisions

1. **Frozen dataclasses everywhere (R2):** No mutable state means no hidden coupling. Each envelope is a new object.

2. **Result types over exceptions (R4):** Validator and Broker return `Result[T]`. Pipeline decides what to do with failures. No exception spaghetti.

3. **Models first, implementations second (R9):** All public interfaces designed before touching implementation. AI fills in the body.

4. **Tests mirror src/ structure (R5):** Easy to find对应的测试, impossible to forget one.

5. **Scope locked to v0.1 (Design Doc 1.7):** No token budget enforcement, no async, no multi-provider. Ship the three things and stop.

---

## Next Steps

1. **Confirm this plan** — does it match your understanding?
2. **Pick Phase 1** — I'll design the envelope interface, you review, then I implement
3. **Or suggest changes** — any component you want to prioritize differently?

Once approved, I'll start with **Phase 1: Core Data Models**, designing the human-written interfaces first (R9) before any AI touches implementation.