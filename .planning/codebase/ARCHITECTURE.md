<!-- refreshed: 2026-05-17 -->
# Architecture

**Analysis Date:** 2026-05-17

## System Overview

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                          Relay Middleware                                   │
│              Context-driven data pipeline with budget enforcement           │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────┐     ┌──────────────────────────────┐          │
│  │   Layer 1: Context       │     │   Layer 2: Slice Packager    │          │
│  │   Broker                 │────▶│                              │          │
│  │  `context_broker.py`     │     │  `slicer/`                   │          │
│  │  `envelope.py`           │     │  - Manifest                  │          │
│  │  - Sign/verify envelopes │     │  - Recency/Structural/       │          │
│  │  - HMAC-SHA256 signing   │     │    Relevance packers         │          │
│  └──────────┬───────────────┘     └──────────────┬───────────────┘          │
│             │                                    │                          │
│             ▼                                   ▼                          │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │              Layer 3: Agent Runner (runners/)                    │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐ │         │
│  │  │ LangChain│ │  CrewAI  │ │ AutoGen  │ │RawSDK    │ │Local  │ │       │
│  │  │ Adapter  │ │ Adapter  │ │ Adapter  │ │Adapter   │ │Model  │ │       │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────┘ │       │
│  └────────────────────────────────┬─────────────────────────────────┘       │
│                                   │                                         │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │              Layer 4: Handoff Validator                          │       │
│  │  `validator.py`                                                 │       │
│  │  - Diff computation, contradiction detection, rollback trigger   │       │
│  └──────────────────────────┬───────────────────────────────────────┘       │
│              ┌──────────────┴──────────────┐                                 │
│              ▼                              ▼                                │
│  ┌──────────────────────┐    ┌──────────────────────────┐                   │
│  │ Layer 5: Snapshot    │    │ Rollback Handler          │                   │
│  │ Store                │    │ `pipeline_rollback.py`    │                   │
│  │ `snapshot.py`        │    │ - Restore from snapshot   │                   │
│  │ - JSON persistence   │    │ - Returns RollbackSuccess │                   │
│  └──────────┬───────────┘    └──────────────────────────┘                   │
│             │                                                               │
│             ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │  Core Orchestrator: `core_pipeline.py`                           │       │
│  │  - CoreRelayPipeline ties all 5 layers together                  │       │
│  │  - Sequential: execute_step / execute_step_with_manifest         │       │
│  │  - Adapter-routed: execute_step_with_runner                      │       │
│  │  - Parallel: execute_parallel_step (fork-join)                   │       │
│  │  - State management: PipelineState (thread-safe, non-reentrant)  │       │
│  │  - Budget enforcement: HardCapEnforcer (budget/enforcer.py)      │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CoreRelayPipeline | Pipeline lifecycle orchestrator; ties all components | `src/relay/core_pipeline.py` |
| ContextEnvelope | Immutable signed data container for pipeline steps | `src/relay/envelope.py` |
| ContextBroker | Envelope lifecycle, secret validation, coordinating creates | `src/relay/context_broker.py` |
| PipelineState | Thread-safe state manager (current/history envelopes, lock) | `src/relay/pipeline_state.py` |
| HardCapEnforcer | Token budget cap validation | `src/relay/budget/enforcer.py` |
| HandoffValidator | Contradiction detection, diff computation, rollback decision | `src/relay/validator.py` |
| SnapshotStore | Immutable JSON checkpoint persistence | `src/relay/snapshot.py` |
| RollbackHandler | Snapshot-based envelope restoration | `src/relay/pipeline_rollback.py` |
| AdapterRegistry | Named AgentRunner lookup | `src/relay/runners/registry.py` |
| AgentManifest | Agent read/write permission model | `src/relay/slicer/manifest.py` |
| SlicePacker | Payload sub-selection strategies | `src/relay/slicer/packers.py` |
| AgentRunner (Protocol) | Adapter interface for any agent framework | `src/relay/runners/protocol.py` |
| LangChainAdapter | Wraps LangChain Runnable as AgentRunner | `src/relay/runners/langchain.py` |
| CrewAIAdapter | Wraps CrewAI Agent as AgentRunner | `src/relay/runners/crewai.py` |
| AutoGenAdapter | Wraps AutoGen AssistantAgent as AgentRunner | `src/relay/runners/autogen.py` |
| RawSDKAdapter | Wraps plain callable as AgentRunner | `src/relay/runners/raw_sdk.py` |
| LocalModelAdapter | Targets any OpenAI-compatible REST endpoint | `src/relay/runners/local_model.py` |
| ForkSpec | Spec for one parallel fork (adapter + manifest) | `src/relay/parallel/types.py` |
| ForkResult | Result from one fork's execution and validation | `src/relay/parallel/types.py` |
| JoinStrategy | Enum: UNION, VOTE, FIRST_WINS | `src/relay/parallel/types.py` |
| run_single_fork | Execute one adapter fork, return ForkResult | `src/relay/parallel/fork_runner.py` |
| apply_join_strategy | Route to correct merge implementation | `src/relay/parallel/join.py` |
| TokenCounter (Protocol) | Token counting abstraction | `src/relay/budget/token_counter.py` |
| EmbeddingProvider (Protocol) | Text embedding for relevance slicing | `src/relay/slicer/providers.py` |
| Result[T] | Success[T] | RollbackSuccess[T] | Failure union | `src/relay/types.py` |
| ErrorCode | Enum of 29 error codes for exhaustive match | `src/relay/types.py` |

## Pattern Overview

**Overall:** Layered middleware with Result-based error handling, immutable envelopes, and thread-safe pipeline state.

**Key Characteristics:**
- **5-layer architecture** with strict dependency direction (lower layers never import upper)
- **Result[T] pattern** replaces exceptions for all operational errors — no try/except in pipeline logic
- **Immutable data flow** — `ContextEnvelope` is frozen, all mutations return new instances via `replace()` or `with_*()` methods
- **HMAC-SHA256 envelope signing** — every envelope cryptographically signed at creation; signature verified before modification
- **Thread-safe state** via non-reentrant `threading.Lock` in `PipelineState`
- **Explicit rollback** via `RollbackSuccess[T]` — a third result type distinct from both `Success` and `Failure`
- **Lazy framework imports** — `LangChainAdapter`, `CrewAIAdapter`, `AutoGenAdapter`, `LocalModelAdapter` are auto-imported on first access via `__getattr__` in `runners/__init__.py`
- **Protocol-based adapter layer** — `AgentRunner` is a `@runtime_checkable` Protocol; adapters need not inherit from a base class

## Layers

**Layer 1 — Context Broker:**
- Purpose: Normalises, timestamps, and cryptographically signs context envelopes
- Location: `src/relay/context_broker.py`, `src/relay/envelope.py`
- Contains: `ContextEnvelope` (frozen dataclass), `ContextBroker` (frozen dataclass), `create_initial_envelope()`, `create_next_envelope()`, `compute_signature()`, `verify_signature()`
- Depends on: `relay.types`, `relay.budget.token_counter`
- Used by: `CoreRelayPipeline`, external integrators

**Layer 2 — Slice Packager:**
- Purpose: Cuts minimal read-only slices per agent based on manifest permissions
- Location: `src/relay/slicer/`
- Contains: `AgentManifest` (frozen dataclass), `RecencySlicePacker`, `StructuralSlicePacker`, `RelevanceSlicePacker`, `EmbeddingProvider` (Protocol), `SlicePacker` (Protocol)
- Depends on: `relay.types`, `relay.envelope`
- Used by: `CoreRelayPipeline`

**Layer 3 — Agent Runner:**
- Purpose: Framework-agnostic adapter layer for agent execution
- Location: `src/relay/runners/`
- Contains: `AgentRunner` (Protocol), `AgentOutput`, `ContextSlice`, `AdapterRegistry`, `RawSDKAdapter`, `LangChainAdapter`, `CrewAIAdapter`, `AutoGenAdapter`, `LocalModelAdapter`
- Depends on: `relay.types`, `relay.slicer.manifest`
- Used by: `CoreRelayPipeline.execute_step_with_runner()`, `parallel/fork_runner.py`

**Layer 4 — Handoff Validator:**
- Purpose: Diff computation, hallucination detection, rollback triggering
- Location: `src/relay/validator.py`
- Contains: `HandoffValidator`, `ValidationResult` (frozen dataclass), `validate_manifest_boundaries()`
- Depends on: `relay.envelope`, `relay.types`, `relay.slicer.manifest` (TYPE_CHECKING only)
- Used by: `CoreRelayPipeline`, `parallel/fork_runner.py`

**Layer 5 — Snapshot Store:**
- Purpose: Immutable JSON checkpoint persistence and retrieval
- Location: `src/relay/snapshot.py`
- Contains: `SnapshotStore`
- Depends on: `relay.envelope`, `relay.types`
- Used by: `CoreRelayPipeline`, `RollbackHandler`

**Pipeline State:**
- Purpose: Thread-safe in-memory state management
- Location: `src/relay/pipeline_state.py`
- Contains: `PipelineState` with `transaction()` context manager (non-reentrant lock)
- Depends on: `relay.envelope`
- Used by: `CoreRelayPipeline`

**Budget Enforcement:**
- Purpose: Hard token budget cap validation before agent calls
- Location: `src/relay/budget/`
- Contains: `HardCapEnforcer`, `TokenCounter` (Protocol), `HeuristicCounter`, `TiktokenCounter` (`AutoTokenCounter`)
- Depends on: `relay.types`
- Used by: `CoreRelayPipeline`

**Parallel Execution:**
- Purpose: Concurrent fork-join agent execution
- Location: `src/relay/parallel/`
- Contains: `ForkSpec`, `ForkResult`, `JoinStrategy` (UNION/VOTE/FIRST_WINS), `run_single_fork()`, `apply_join_strategy()`
- Depends on: `relay.runners`, `relay.validator`, `relay.types`
- Used by: `CoreRelayPipeline.execute_parallel_step()`

## Data Flow

### Primary Request Path (Sequential Step)

1. Entry: `CoreRelayPipeline.execute_step(agent_output)` or `execute_step_with_manifest(agent_output, manifest)` (`core_pipeline.py:153-161`)
2. Lock acquisition: `PipelineState.transaction()` context manager yields current envelope (`pipeline_state.py:54-74`)
3. Initial step routing: `_handle_initial_step()` if current is None, else `_handle_subsequent_step()` (`core_pipeline.py:171-235`)
4. Budget check: `_check_budget()` delegates to `HardCapEnforcer.check()` if enforcer and manifest present (`core_pipeline.py:237-286`)
5. Envelope creation: `ContextBroker.create_initial_envelope()` or `create_next_envelope()` produces signed `ContextEnvelope` (`context_broker.py:62-88`, `envelope.py:186-265`)
6. Manifest application: `_apply_manifest()` validates write boundaries, re-signs if needed (`core_pipeline.py:326-358`)
7. Handoff validation: `HandoffValidator.validate_handoff()` checks pipeline_id, step order, payload diff, hallucination detection (`validator.py:100-119`)
8. Fork decision: if `should_rollback()` → `RollbackSuccess` with restored envelope; else continue (`core_pipeline.py:288-324`)
9. Snapshot persistence: `SnapshotStore.save_snapshot()` writes JSON to `relay_data/snapshots/{pipeline_id}/{snapshot_id}.json` (`snapshot.py:67-129`)
10. State advancement: `PipelineState.archive_and_set()` moves old envelope to history, sets new current (`pipeline_state.py:95-99`)

### Adapter-Routed Step

1. Entry: `CoreRelayPipeline.execute_step_with_runner(adapter_name, manifest)` (`core_pipeline.py:429-487`)
2. Adapter lookup: `AdapterRegistry.get(adapter_name)` (`registry.py:55-64`)
3. Context slice construction: `_build_context_slice()` filters payload to `manifest.reads` (`core_pipeline.py:631-663`)
4. Budget check (advisory, lock released before I/O): `_check_budget()` (`core_pipeline.py:237-286`)
5. Lock released: `adapter.run(slice_, manifest)` executes outside lock (`core_pipeline.py:479`)
6. Payload conversion: `agent_output_to_payload()` shapes AgentOutput to JSONDict (`parallel/types.py:62-72`)
7. Commit: delegates to `execute_step_with_manifest(payload, manifest)` (same flow as primary)

### Parallel Fork-Join Step

1. Entry: `CoreRelayPipeline.execute_parallel_step(fork_specs, join_strategy)` (`core_pipeline.py:489-629`)
2. Validation: non-empty specs, registry set, at least one prior step (`core_pipeline.py:517-533`)
3. Lock held: build per-fork ContextSlice, check per-fork budgets (`core_pipeline.py:528-541`)
4. Lock released: fire all fork coroutines concurrently via `run_single_fork()` (`fork_runner.py:24-123`)
5. Join: `apply_join_strategy(UNION|VOTE|FIRST_WINS, results)` (`join.py:157-178`)
6. Commit: envelope creation, fork metadata attachment, re-sign, validate, snapshot, advance state (all within single lock acquisition)

### Rollback Flow

1. Entry: `CoreRelayPipeline.rollback()` (`core_pipeline.py:414-422`)
2. Lock acquisition: `transaction()` (`core_pipeline.py:416`)
3. History check: `PipelineState.has_history()` (`pipeline_state.py:111-114`)
4. Snapshot restoration: `RollbackHandler.restore_to_previous()` loads snapshot, returns `RollbackSuccess` (`pipeline_rollback.py:19-48`)
5. State update: consume last history entry, set current to restored envelope (`core_pipeline.py:389-392`)

**State Management:**
- In-memory: `PipelineState` holds `_current_envelope`, `_previous_envelopes` list, `_snapshot_ids` dict
- Persisted: `SnapshotStore` writes each envelope to `{storage_path}/{pipeline_id}/{snapshot_id}.json` with `index.json` tracking ordered snapshot list
- Thread safety: non-reentrant `threading.Lock` — all state mutations require `transaction()` context manager; nested calls raise `RuntimeError`

## Key Abstractions

**Result[T] = Success[T] | RollbackSuccess[T] | Failure:**
- Purpose: Replaces exceptions for all operational errors. All three are `@dataclass(frozen=True)`. Every function in the pipeline returns `Result`.
- Examples: `core_pipeline.py`, `snapshot.py`, `envelope.py`, `validator.py`
- Pattern: Use `isinstance()` checks, `unwrap()` (raises on non-Success), `unwrap_or()` (default on both Failure and RollbackSuccess), `map_result()` (transforms RollbackSuccess), `map_error()` (transforms Failure). See `src/relay/types.py:86-135`.

**ContextEnvelope:**
- Purpose: Immutable signed data container wrapping payload with metadata at every pipeline step
- File: `src/relay/envelope.py:48-122`
- Pattern: `@dataclass(frozen=True)` with `with_*()` methods returning new instances

**AgentRunner Protocol:**
- Purpose: Single-method `async def run(slice, manifest) -> AgentOutput` contract for all adapters
- File: `src/relay/runners/protocol.py:70-104`
- Pattern: `@runtime_checkable` Protocol — adapters satisfy structurally, no inheritance

**PipelineState.transaction():**
- Purpose: Non-reentrant lock context manager that yields current envelope
- File: `src/relay/pipeline_state.py:53-74`
- Pattern: `@contextmanager` + `threading.Lock` + thread ID tracking for reentrancy detection

## Entry Points

**CoreRelayPipeline:**
- Location: `src/relay/core_pipeline.py:48`
- Triggers: Direct instantiation or `CoreRelayPipeline.create()` factory
- Responsibilities: Orchestrates all 5 layers, budget enforcement, fork-join parallel execution

**CoreRelayPipeline.create():**
- Location: `src/relay/core_pipeline.py:74-103`
- Triggers: Framework builder code
- Responsibilities: Validates signing_secret via `create_context_broker()`, returns `Result[CoreRelayPipeline]`

**execute_step():**
- Location: `src/relay/core_pipeline.py:153-155`
- Triggers: Per-step agent output
- Responsibilities: Full pipeline cycle without manifest

**execute_step_with_manifest():**
- Location: `src/relay/core_pipeline.py:157-169`
- Triggers: Per-step agent output with AgentManifest
- Responsibilities: Full pipeline cycle with budget/boundary validation

**execute_step_with_runner():**
- Location: `src/relay/core_pipeline.py:429-487`
- Triggers: Adapter name + manifest
- Responsibilities: Lookup adapter, build context slice, run, convert output, commit

**execute_parallel_step():**
- Location: `src/relay/core_pipeline.py:489-629`
- Triggers: ForkSpec list + JoinStrategy
- Responsibilities: Run N adapters concurrently, merge via strategy, commit

**rollback():**
- Location: `src/relay/core_pipeline.py:414-422`
- Triggers: Manual rollback request
- Responsibilities: Restore previous snapshot from history

## Architectural Constraints

- **Threading:** Single-threaded event loop for async adapters; `threading.Lock` for state access. Lock released during I/O (adapter.run() calls). No `asyncio.Lock` used.
- **Non-reentrant lock:** `PipelineState.transaction()` raises `RuntimeError` on nested calls. Every method that acquires the lock documents "Must NOT call self._state.transaction() — lock is non-reentrant."
- **Layer dependency direction:** lower layers never import upper layers. The import chain is: `types.py` → `envelope.py` → `snapshot.py` → `validator.py` → `context_broker.py` → `budget/` + `slicer/` → `pipeline_state.py` → `pipeline_rollback.py` + `parallel/` → `core_pipeline.py`
- **Global state:** No module-level singletons. `HeuristicCounter` module-level instance in `envelope.py` (`_ESTIMATOR`) is the only module-level state — it is stateless.
- **Circular imports:** No known circular dependency chains. `runners/__init__.py` uses `__getattr__` for lazy imports to avoid eager framework dependency chains.
- **pipeline_id validation:** Validated against `^[a-zA-Z0-9_-]{1,128}$` before filesystem use (path traversal prevention in `snapshot.py`).
- **HMAC comparison:** Always via `hmac.compare_digest()`, never `==`, to prevent timing attacks.
- **Framework adapters:** All framework-specific adapters are lazy-imported — importing `relay.runners` does not require any framework to be installed.

## Anti-Patterns

### Direct Construction vs Factory

**What happens:** `CoreRelayPipeline` and `ContextBroker` both support direct construction (bypasses validation) and factory methods (`CoreRelayPipeline.create()`, `create_context_broker()`) that validate first. The docstrings note this is for "internal use with pre-validated secrets."

**Why it's wrong:** Direct construction bypasses `signing_secret` length validation. Callers could accidentally construct with a short secret.

**Do this instead:** Always use `CoreRelayPipeline.create()` and `create_context_broker()` from external code. Only use direct construction in internal code where the secret was already validated by an outer factory call.

### Lock Released Before I/O

**What happens:** In `execute_step_with_runner()` (`core_pipeline.py:472-487`), the lock is acquired only for the budget check and context slice build, then released before `adapter.run()`. Another thread may advance the envelope between the check and execution.

**Why it's wrong:** Budget enforcement is advisory under concurrent load. Token counts are heuristic, so overruns can occur.

**Do this instead:** Documented as a known limitation. The safety net is `execute_step_with_manifest()` which validates post-hoc, and rollback is the recovery path.

## Error Handling

**Strategy:** `Result[T]` union type for all operational errors. No exceptions for expected failures.

**Patterns:**
- Every function returns `Result[T]` — callers use `isinstance()` checks for `Success`, `Failure`, or `RollbackSuccess`
- `unwrap()` extracts `Success.value` or raises `ValueError` (for programmer errors only)
- `unwrap_or()` returns default on both `Failure` and `RollbackSuccess`
- `map_result()` transforms `Success.value` but also transforms `RollbackSuccess.value` (preserving reason)
- `map_error()` transforms `Failure` into another `Failure`, leaves `Success`/`RollbackSuccess` unchanged

## Cross-Cutting Concerns

**Logging:** Standard library `logging.getLogger(__name__)` in `snapshot.py` and `parallel/join.py`. No structured logging framework.

**Validation:**
- Pipeline ID validated via regex `^[a-zA-Z0-9_-]{1,128}$` before filesystem use
- Snapshot ID validated via regex `^[a-zA-Z0-9_-]{1,128}@\d+_[a-f0-9]{12}$`
- Manifest writes validated against payload keys (boundary enforcement)
- Envelope step must monotonically increase

**Authentication:** HMAC-SHA256 envelope signing. `verify_signature()` uses `hmac.compare_digest()`. Optional `max_age_seconds` for staleness checks.

---

*Architecture analysis: 2026-05-17*
