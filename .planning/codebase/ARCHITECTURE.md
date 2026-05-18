---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "arch"
---

# ARCHITECTURE.md — System Architecture

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## System Overview

Relay is a **context-driven middleware library** for orchestrating multi-agent LLM pipelines with signed, reversible handoffs. It provides budget enforcement, snapshot-based rollback, audit logging, and pluggable agent adapters.

## Architectural Pattern: Layered Pipeline with Result-Based Error Handling

```
┌─────────────────────────────────────────────────────┐
│                 CoreRelayPipeline                    │
│  (orchestrator: lifecycle, coordination, async fork) │
├──────────┬──────────┬───────────┬───────────────────┤
│ Context  │ Snapshot │ Validator │ Audit             │
│ Broker   │ Store    │           │ Sink              │
├──────────┴──────────┴───────────┴───────────────────┤
│              Budget │ Slicer │ Runners              │
├─────────────────────┴────────┴──────────────────────┤
│              Parallel (Fork/Join)                   │
└─────────────────────────────────────────────────────┘
```

## Layer Dependency Order (lower never imports upper)

```
types.py
  ↓
envelope.py
  ↓
snapshot_protocol.py → snapshot.py / snapshot_in_memory.py
  ↓
validator.py
  ↓
context_broker.py
  ↓
budget/ (enforcer.py, token_counter.py)
slicer/ (manifest.py, packers.py, providers.py)
  ↓
audit/ (events.py, sink.py, redactor.py)
  ↓
pipeline_state.py
  ↓
pipeline_rollback.py
parallel/ (fork_runner.py, join.py, types.py)
  ↓
core_pipeline.py (top-level orchestrator)
  ↓
runners/ (protocol.py, registry.py, adapters)
```

## Key Abstractions

### 1. Result Type (`src/relay/types.py`)

All public APIs return `Result[T]` — never raise exceptions for operational errors:

```python
type Result[T] = Success[T] | RollbackSuccess[T] | Failure
```

- **`Success[T]`** — operation succeeded, carries value
- **`Failure`** — operation failed, carries reason + `ErrorCode`
- **`RollbackSuccess[T]`** — rollback succeeded, carries restored value + reason

Key semantics:
- `unwrap()` raises on `Failure` and `RollbackSuccess`
- `unwrap_or()` returns default on both `Failure` and `RollbackSuccess`
- `map_result()` transforms `Success` and `RollbackSuccess`, leaves `Failure`

### 2. ContextEnvelope (`src/relay/envelope.py`)

Immutable, signed data structure passed between pipeline steps:

```python
@dataclass(frozen=True)
class ContextEnvelope:
    relay_version: str
    pipeline_id: str
    step: int
    timestamp: datetime
    token_budget_used: int
    token_budget_total: int
    payload: JSONDict
    manifest_hash: str
    signature: str  # HMAC-SHA256
    fork_id: str | None
    join_strategy: str | None
    fork_count: int | None
    forks_succeeded: int | None
    key_id: str
    nonce: str
    sequence_number: int
```

Signing uses canonical serialization with `|`-delimited fields and `hmac.compare_digest` for constant-time comparison.

### 3. AgentManifest (`src/relay/slicer/manifest.py`)

Defines agent read/write permissions:
- `reads: set[str]` — sections the agent can read
- `writes: set[str]` — sections the agent can write
- `max_tokens: int | None` — per-agent token budget
- `agent_id: str` — unique identifier

### 4. ErrorCode Enum (`src/relay/types.py`)

30+ typed error codes for exhaustive pattern matching:
- Pipeline: `INVALID_PIPELINE_ID`, `PIPELINE_MISMATCH`, `INVALID_STEP`
- Budget: `TOKEN_BUDGET_EXCEEDED`, `BUDGET_EXCEEDED`
- Snapshot: `SNAPSHOT_NOT_FOUND`, `SNAPSHOT_SAVE_FAILED`, `CORRUPTED_INDEX`
- Validation: `MANIFEST_BOUNDARY_VIOLATION`
- Registry/Adapter: `ADAPTER_NOT_FOUND`, `NO_REGISTRY`, `ADAPTER_EXECUTION_FAILED`
- Fork/Join: `ALL_FORKS_FAILED`, `INVALID_JOIN_STRATEGY`, `MERGE_CONFLICT`
- Security: `INVALID_SECRET`, `STALE_SIGNATURE`

## Data Flow

### Sequential Pipeline

```
1. CoreRelayPipeline.create() → Result[CoreRelayPipeline]
2. execute_step(agent_output) or execute_step_with_manifest(output, manifest)
   a. Acquire pipeline lock (transaction)
   b. Check budget (HardCapEnforcer)
   c. Create envelope (ContextBroker)
   d. Apply manifest hash + re-sign
   e. Save snapshot (SnapshotStore)
   f. Validate handoff (HandoffValidator)
   g. Advance state or rollback
   h. Release lock
3. Repeat step 2 for each agent execution
4. rollback() → restore from snapshot
```

### Parallel Pipeline (Fork/Join)

```
1. execute_parallel_step(fork_specs, join_strategy)
   a. Validate inputs (non-empty specs, registry set)
   b. Acquire lock: build slices, check per-fork budgets
   c. Release lock
   d. Execute forks concurrently (asyncio.gather)
   e. Join results via strategy (FIRST_WINS / UNION / VOTE)
   f. Commit merged payload via execute_step_with_manifest
   g. Attach fork metadata to envelope, re-sign, re-save
```

### Join Strategies

| Strategy | Behavior |
|----------|----------|
| `FIRST_WINS` | First successful fork wins, others cancelled |
| `UNION` | Merge all successful fork payloads |
| `VOTE` | Majority vote on conflicting values |

## Thread Safety Model

- `PipelineState` uses a **non-reentrant `threading.Lock`** via `transaction()` context manager
- Lock is held during: budget check → envelope creation → snapshot save → validation → state mutation
- Lock is **released** before `adapter.run()` (to avoid holding during I/O)
- Budget check is **advisory under concurrent load** — another thread may advance between check and execution
- `RollbackSuccess` is the safety net for post-hoc validation failures
- `assert_lock_held()` raises `RuntimeError` if lock not held (programmer-error hard crash)

## Key Design Decisions

1. **Zero runtime dependencies** — core library works without any LLM framework installed
2. **Lazy imports** — framework adapters don't load until explicitly used
3. **Immutable domain values** — all dataclasses are `frozen=True`, use `replace()` or `with_*` methods
4. **Result over exceptions** — no exceptions for operational errors, only for programmer errors (lock violations, invariant checks)
5. **HMAC signing** — every envelope is cryptographically signed for integrity verification
6. **Snapshot-based rollback** — state is persisted at every step, enabling full rollback
7. **Fire-and-forget audit** — audit sink errors are logged, never propagated (D-06)
8. **Factory pattern** — `CoreRelayPipeline.create()` validates secrets; direct construction bypasses validation
