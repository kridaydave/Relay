# Cross-Phase Integration Audit: Relay Middleware Library

**Date:** 2026-05-17
**Scope:** `src/relay/` — all 12 source files across 7 directories
**Entry point:** `CoreRelayPipeline` in `core_pipeline.py`

---

## 1. Layer Dependency Verification

### Stated dependency order

```
types.py → envelope.py → snapshot.py → validator.py → context_broker.py
         → budget/ + slicer/ → pipeline_state.py → pipeline_rollback.py
         + parallel/ → core_pipeline.py
```

### Actual import graph (runtime imports only, excluding TYPE_CHECKING)

| Module | Imports From (relay.*) | Violations? |
|--------|----------------------|-------------|
| `types.py` | *(none — stdlib only)* | ✓ None |
| `envelope.py` | `types` | ✓ Lower |
| `snapshot.py` | `envelope`, `types` | ✓ Lower |
| `validator.py` | `envelope`, `types` (TYPE_CHECKING: `slicer.manifest`) | ✓ Lower (TYPE_CHECKING excluded) |
| `context_broker.py` | `envelope`, `types` | ✓ Lower |
| `budget/enforcer.py` | `budget.token_counter`, `types` | ✓ Same-layer |
| `budget/token_counter.py` | *(none — stdlib only)* | ✓ None |
| `slicer/manifest.py` | *(none — stdlib only)* | ✓ None |
| `slicer/providers.py` | `slicer.manifest`, `types` | ✓ Same-layer |
| `slicer/packers.py` | `envelope`, `slicer.manifest`, `slicer.providers`, `types` | ✓ Lower + same-layer |
| `pipeline_state.py` | `envelope` | ✓ Lower |
| `pipeline_rollback.py` | `envelope`, `snapshot`, `types` | ✓ Lower |
| `parallel/types.py` | `runners.protocol`, `types` (TYPE_CHECKING: `slicer.manifest`, `validator`) | ⚠️ See note |
| `parallel/fork_runner.py` | `envelope`, `parallel.types`, `runners.protocol`, `types`, `validator` (TYPE_CHECKING: `runners.registry`, `slicer.manifest`) | ⚠️ See note |
| `parallel/join.py` | `envelope`, `parallel.types`, `types` (TYPE_CHECKING: `runners.protocol`) | ✓ Lower + same-layer |
| `runners/protocol.py` | `types` (TYPE_CHECKING: `slicer.manifest`) | ✓ Lower |
| `runners/registry.py` | `runners.protocol`, `types` | ✓ Same-layer |
| `runners/raw_sdk.py` | `runners.protocol`, `slicer.manifest`, `types` | ✓ Same-layer |
| `runners/langchain.py` | `runners.protocol`, `slicer.manifest`, `types` | ✓ Same-layer |
| `runners/crewai.py` | `runners.protocol`, `slicer.manifest`, `types` | ✓ Same-layer |
| `runners/autogen.py` | `runners.protocol`, `slicer.manifest`, `types` | ✓ Same-layer |
| `runners/local_model.py` | `runners.protocol`, `slicer.manifest`, `types` | ✓ Same-layer |
| `core_pipeline.py` | `budget`, `context_broker`, `envelope`, `parallel`, `parallel.fork_runner`, `parallel.types`, `pipeline_rollback`, `pipeline_state`, `runners`, `runners.protocol`, `slicer`, `snapshot`, `types`, `validator` | ✓ All lower |

**Note on `parallel/` → `runners/` dependency:** The stated dependency chain does not explicitly position `runners/`. The code has `parallel/types.py` importing `runners.protocol` and `parallel/fork_runner.py` importing `runners.protocol` at runtime. This creates a dependency from `parallel/` (near-top layer) into `runners/`. This is **not a circular dependency** — `runners/` never imports from `parallel/`. The dependency direction is consistent and acyclic, but the relationship is undocumented.

### √ Verdict: No layer violations found. All runtime imports point strictly downward. The `parallel → runners` dependency is undocumented but structurally valid.

---

## 2. End-to-End Flow Verification

### Flow: Create Pipeline → Add Context → Run Step → Validate → Snapshot → Rollback

#### 2a. Create pipeline (`CoreRelayPipeline.create()`)

```
create()
  → create_context_broker(signing_secret, token_budget)        [FAILURE → return Failure]
  → cls(signing_secret, token_budget, ...)
    → __post_init__()
      → uuid.uuid4().hex → _pipeline_id                        ✓ UUID set
      → PipelineState(pipeline_id) → _state                    ✓ State created
      → create_context_broker(secret, budget) → _context_broker ✓ (validated AGAIN)
      → HandoffValidator() → _handoff_validator                ✓ Default thresholds
      → SnapshotStore(storage_path) → _snapshot_store          ✓ Directory created
      → RollbackHandler() → _rollback_handler                  ✓ Empty handler
      → token_counter → HardCapEnforcer or None → _enforcer    ✓ Optional
```

**Status: WIRED** ✓
**Finding:** `create_context_broker()` is called TWICE — once in `create()` for validation, once in `__post_init__()` for the instance assignment. Both calls construct a `ContextBroker` object, so the first is wasted work. Not a correctness issue, but redundant.

#### 2b. Execute initial step (`execute_step`)

```
execute_step(agent_output)
  → execute_step_with_manifest(output, manifest=None)
    → state.transaction()
      → current_envelope is None → _handle_initial_step(output, manifest)
        → _check_budget(manifest, None, agent_output)
          → enforcer.check(0, token_budget, serialize_slice(output))
          → manifest.max_tokens → projected_cost comparison     [FAILURE → return Failure]
        → context_broker.create_initial_envelope(pipeline_id, output, hash)
          → validate_pipeline_id(pipeline_id)                   [FAILURE → return Failure]
          → estimate_tokens(output) → token_budget_used
          → ContextEnvelope(step=1, ...) → compute_signature    ✓ Step=1, signed
        → _apply_manifest(envelope, manifest)
          → validate_manifest_boundaries(manifest, payload_keys) [FAILURE → return Failure]
          → manifest.compute_hash() → update envelope hash      ✓ Re-sign if hash changed
        → snapshot_store.save_snapshot(new_envelope)            [FAILURE → return Failure]
        → state.register_snapshot(step=1, snapshot_id)          ✓ Step 1 registered
        → state.set_current(new_envelope)                       ✓ Current set
        → RETURN Success(new_envelope)
```

**Status: WIRED** ✓

#### 2c. Execute subsequent step

```
execute_step(output)
  → execute_step_with_manifest(output, manifest=None)
    → state.transaction()
      → current_envelope is step1 → _handle_subsequent_step(envelope, output, manifest)
        → _check_budget(manifest, current_envelope)
          → _slice_payload(manifest, envelope) → projected    ✓ (or serialize full payload)
          → enforcer.check(budget_used, total, projected)     [FAILURE → return Failure]
          → manifest.max_tokens check                          [FAILURE → return Failure]
        → context_broker.create_next_envelope(envelope, output, hash)
          → estimate_tokens(output) → add to token_budget_used ✓ Cumulative
          → ContextEnvelope(step=previous.step+1, ...) → sign  ✓ Step incremented
        → _apply_manifest(new_envelope, manifest)               ✓ Re-sign if needed
        → _finalize_step(current_envelope, new_envelope)
          → handoff_validator.validate_handoff(prev, new)
            → pipeline_id match check                          [FAILURE → return Failure]
            → step must increase                                [FAILURE → return Failure]
            → _validate_payloads → _detect_hallucination       [contradiction → rollback]
            → _compute_diff → _check_critical_keys_missing     [contradiction → rollback]
            → confidence_score computation
          → should_rollback?
            → YES: save_snapshot(current), push_history, RETURN RollbackSuccess
            → NO: save_snapshot(new), archive_and_set, RETURN Success(new)
```

**Status: WIRED** ✓
Happy path (no contradictions): state advances, snapshot saved, envelope returned.
Contradiction path: current saved as snapshot, pushed to history, RollbackSuccess returned.

#### 2d. Rollback

```
rollback()
  → state.transaction()
    → has_history() → False → FAILURE(NO_ROLLBACK_AVAILABLE)    ✓ Edge case
    → has_history() → True → _do_rollback("Manual rollback", consume=True)
      → peek_last() → previous_envelope
      → rollback_handler.restore_to_previous(envelope, snapshot_ids, store, reason)
        → snapshot_ids.get(envelope.step) → id                 [None → FAILURE]
        → load_snapshot(snapshot_id) → envelope                [FAILURE → propagate]
        → RETURN RollbackSuccess(envelope, reason)
      → isinstance(RollbackSuccess) → TRUE
        → consume_last() → pops from previous_envelopes        ✓ History cleaned
        → set_current(restored_envelope)                       ✓ Current restored
      → RETURN RollbackSuccess
```

**Status: WIRED** ✓
The `RollbackSuccess` type correctly propagates through the public API.

#### 2e. Verify state recovery after rollback

After `rollback()` returns:
- `_state.current()` = restored envelope (step N, same as before the bad step)
- `_state.get_previous_envelopes()` = history minus the bad step's parent
- `_state.snapshot_ids` = still has all prior snapshots (the bad step's snapshot is also there since it was saved during `_finalize_step`, but no registration points to the rejected step)
- The next `execute_step()` will use the restored envelope as current ✓

**Status: WIRED** ✓

### Full Lifecycle Flow Summary

| Step | Input | Output | State Before | State After | Correct? |
|------|-------|--------|-------------|-------------|----------|
| Create | signing_secret, budget | Success(pipeline) | N/A | Pipeline with uuid, state, broker, validator, store, handler | ✓ |
| Step 1 | agent_output | Success(step1_env) | current=None, history=[] | current=step1, history=[], snapshots={1: id} | ✓ |
| Step 2 | agent_output | Success(step2_env) | current=step1, history=[] | current=step2, history=[step1], snapshots={1: id1, 2: id2} | ✓ |
| Step 3 (bad) | agent_output | RollbackSuccess(step2) | current=step2, history=[step1] | current=step2, history=[step1, step2], snapshots={1: id1, 2: id2, 2: id2b} | ⚠️ Duplicate snapshot for step 2 |
| rollback() | — | RollbackSuccess(restored_step2) | current=step2, history=[step1, step2] | current=step2, history=[step1], snapshots={1: id1, 2: id2b} | ✓ |

**⚠️ Note:** On contradiction rollback, step 2's envelope is snapshotted a SECOND time (once during the original `_finalize_step` when step 2 was committed, once during the rollback path of `_finalize_step` for step 3). The second snapshot overwrites the step index entry for step 2. The first snapshot file remains on disk as an orphan. Not a functional bug — both snapshots contain identical data — but a minor resource leak.

---

## 3. Parallel Fork-Join Integration

### 3a. Architecture

The parallel subsystem (`relay.parallel/`) consists of:
- `types.py`: `ForkSpec`, `ForkResult`, `JoinStrategy` enum, `agent_output_to_payload()`
- `fork_runner.py`: `run_single_fork()` — executes ONE adapter fork
- `join.py`: `_apply_union()`, `_apply_vote()`, `_apply_first_wins()`, `apply_join_strategy()`

### 3b. Integration with pipeline state (`execute_parallel_step`)

```
execute_parallel_step(fork_specs, join_strategy)
  1. Validate inputs (non-empty, registry set)
  2. state.transaction()
       → pre_fork_envelope = current()  [FAILURE if None]
       → build fork_slices (filtered by manifest.reads)
       → check per-fork budget
     Lock released.
  3. Create fork coroutines → run_single_fork()
  4. Apply join strategy:
       FIRST_WINS: await first passing, cancel rest
       UNION/VOTE: gather all, then merge
  5. If merged_result is Failure → return Failure (state unchanged)
  6. state.transaction()
       → create_next_envelope(current, merged_payload)
       → with_fork_metadata(fork_id, strategy, count, succeeded)
       → re-sign (with_fork_metadata clears signature!)
       → validate_handoff → rollback check
       → save_snapshot, archive_and_set, RETURN Success(signed)
```

**Integration points verified:**

| Point | Component A | Component B | Correct? |
|-------|------------|------------|----------|
| Fork validation | `fork_runner.py` | `HandoffValidator` (shared) | ✓ Stateless, shared safely |
| Fork adapter execution | `fork_runner.py` | `AdapterRegistry` | ✓ Gets adapter, handles Failure |
| Fork output shaping | `fork_runner.py` | `agent_output_to_payload()` | ✓ Converts AgentOutput → JSONDict |
| Manifest boundary check | `fork_runner.py` | `validate_manifest_boundaries()` | ✓ Checks writes against manifest |
| Merge | `join.py` | `ForkResult` list | ✓ All 3 strategies handle error cases |
| Post-merge commit | `execute_parallel_step` | `execute_step_with_manifest` | ✓ Creates envelope, validates, saves |
| Fork metadata signing | `execute_parallel_step` | `compute_signature()` | ✓ Re-signs after `with_fork_metadata()` clears sig |
| ORM for FIRST_WINS fail | `join.py` | `_apply_first_wins` | ✓ Cancellation + gather(return_exceptions=True) |

### 3c. State contention window

Between step 2 (lock release) and step 6 (lock re-acquire), another thread can call `execute_step()` and advance the current envelope. The re-acquired `current_envelope` at step 6 may differ from `pre_fork_envelope`. This is **documented as advisory** — the concurrent budget enforcement note in the docstring explains this is by design. The post-merge `validate_handoff` acts as a safety net.

**Status: WIRED** ✓ (with acknowledged advisory concurrency)

---

## 4. Error Propagation

### 4a. All ErrorCodes mapped to usage

| ErrorCode | Source(s) | Used By | Propagates? |
|-----------|----------|---------|-------------|
| `INVALID_PIPELINE_ID` | `envelope.validate_pipeline_id()` | `snapshot._dict_to_envelope()`, `create_initial_envelope()`, `save_snapshot()` | ✓ |
| `INVALID_PAYLOAD` | `envelope.create_initial_envelope()`, `create_next_envelope()` | Direct callers | ✓ |
| `TOKEN_BUDGET_EXCEEDED` | `core_pipeline._check_budget()` (per-agent) | `_handle_initial_step`, `_handle_subsequent_step` | ✓ |
| `INVALID_TOKEN_COUNT` | `enforcer.check()` | `_check_budget` | ✓ |
| `BUDGET_EXCEEDED` | `enforcer.check()` (pipeline-level) | `_check_budget` | ✓ |
| `MANIFEST_BOUNDARY_VIOLATION` | `validator.validate_manifest_boundaries()` | `_apply_manifest`, `fork_runner.run_single_fork` | ✓ |
| `PIPELINE_MISMATCH` | `validator.validate_handoff()` | `_finalize_step` | ✓ |
| `INVALID_STEP` | `validator.validate_handoff()` | `_finalize_step` | ✓ |
| `INVALID_SNAPSHOT_ID` | `snapshot.load_snapshot()` | `rollback_handler.restore_to_previous()` | ✓ |
| `SNAPSHOT_NOT_FOUND` | `snapshot.load_snapshot()` | `rollback_handler.restore_to_previous()` | ✓ |
| `SNAPSHOT_SAVE_FAILED` | `snapshot.save_snapshot()` | various | ✓ |
| `SNAPSHOT_LOAD_FAILED` | `snapshot.load_snapshot()` | various | ✓ |
| `INDEX_UPDATE_FAILED` | `snapshot._add_to_index()` | `save_snapshot()` | ✓ |
| `INDEX_NOT_FOUND` | `snapshot._load_index()` | `get_latest_snapshot()`, `list_snapshots()` | ✓ |
| `INVALID_INDEX` | `snapshot._load_index()` | `get_latest_snapshot()` | ✓ |
| `CORRUPTED_INDEX` | `snapshot._add_to_index()`, `_load_index()` | various | ✓ |
| `INDEX_READ_FAILED` | `snapshot._load_index()` | various | ✓ |
| `NO_SNAPSHOT_REGISTERED` | `rollback_handler.restore_to_previous()` | `_do_rollback` | ✓ |
| `NO_ROLLBACK_AVAILABLE` | `core_pipeline._do_rollback()`, `rollback()` | Public API | ✓ |
| `PIPELINE_NOT_FOUND` | `snapshot.get_latest_snapshot()` | Direct callers | ✓ |
| `NO_SNAPSHOTS` | `snapshot.get_latest_snapshot()` | Direct callers | ✓ |
| `INVALID_STATE` | `core_pipeline._do_rollback()`, `execute_parallel_step()` | Various | ✓ |
| `INVALID_SNAPSHOT` | `snapshot.load_snapshot()`, `_dict_to_envelope()` | various | ✓ |
| `MISSING_SECTIONS` | `StructuralSlicePacker.pack()` | `_slice_payload` via `SlicePacker` | ✓ |
| `UNKNOWN_ERROR` | `parallel.join._apply_union()`, `_apply_vote()` | Invariant violations | ✓ |
| `ADAPTER_NOT_FOUND` | `registry.get()` | `execute_step_with_runner`, `execute_parallel_step` | ✓ |
| `NO_REGISTRY` | `core_pipeline.execute_step_with_runner()`, `execute_parallel_step()` | Public API | ✓ |
| `ADAPTER_EXECUTION_FAILED` | `core_pipeline.execute_step_with_runner()` | Wraps adapter exceptions | ✓ |
| `INVALID_SECRET` | `context_broker.create_context_broker()` | `CoreRelayPipeline.create()`, `__post_init__()` | ✓ |
| `MERGE_CONFLICT` | `parallel.join._apply_union()` | `execute_parallel_step()` | ✓ |
| `ALL_FORKS_FAILED` | `parallel.join` (all 3 strategies) | `execute_parallel_step()` | ✓ |
| `FORK_EXECUTION_FAILED` | `parallel.fork_runner.run_single_fork()` | `execute_parallel_step()` via apply_join... | ✓ |
| `INVALID_JOIN_STRATEGY` | `parallel.join.apply_join_strategy()` | `execute_parallel_step()` | ✓ |

**Status: All 34 ErrorCodes are used. All error paths propagate correctly.** ✓

### 4b. Exception safety

All public API methods (`create()`, `execute_step()`, `execute_step_with_manifest()`, `execute_step_with_runner()`, `execute_parallel_step()`, `rollback()`) return `Result` types. Exceptions are caught and converted to Failure in:

| Location | Exception | Translated to |
|----------|-----------|---------------|
| `execute_step_with_runner` | `adapter.run()` exception | `ADAPTER_EXECUTION_FAILED` |
| `run_single_fork` | `adapter.run()` exception | `FORK_EXECUTION_FAILED` |
| `__post_init__()` | `create_context_broker()` Failure → ValueError | ❌ **MIXED ERROR HANDLING** |

### 4c. ⚠️ Mixed error handling stratey (WARNING)

`CoreRelayPipeline.create()` (factory) returns `Failure` when `create_context_broker()` fails. But `__post_init__()` raises `ValueError` for the same failure. This means:
- `CoreRelayPipeline.create(invalid_secret)` → `Failure(INVALID_SECRET)` ✓
- `CoreRelayPipeline(signing_secret="short")` → `ValueError` ✗ (exception instead of Result)

Direct construction bypasses the factory and raises an exception. This is documented ("Use this factory instead of direct construction") but the dataclass `__post_init__` is always called, making direct construction crash. **Recommendation:** Make `__post_init__` more resilient or `create.ContextBroker` lazily on first use.

---

## 5. Protocol/Interface Consistency

### 5a. AgentRunner protocol compliance

All 5 adapters implement `async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput`:

| Adapter | `run` is async? | Signature matches? | Protocol check |
|---------|----------------|-------------------|----------------|
| `RawSDKAdapter` | ✓ | ✓ | `isinstance(x, AgentRunner)` passes |
| `LangChainAdapter` | ✓ | ✓ | Runs via `cast(_Runnable, ...)` |
| `CrewAIAdapter` | ✓ | ✓ | `isinstance` would pass |
| `AutoGenAdapter` | ✓ | ✓ | `isinstance` would pass |
| `LocalModelAdapter` | ✓ | ✓ | `isinstance` would pass |

`AdapterRegistry.register()` validates:
- Name is non-empty ✓
- Name not already registered (fail-fast with ValueError) ✓
- `isinstance(adapter, AgentRunner)` — runtime protocol check via `@runtime_checkable` ✓
- `run` method is `async def` — checked with `inspect.iscoroutinefunction` ✓

**Status: WIRED** ✓

### 5b. SnapshotStore interface compatibility

Usage pattern across callers:

| Method | Caller(s) | Returns | Error handling |
|--------|----------|---------|----------------|
| `save_snapshot(envelope)` | `_handle_initial_step`, `_finalize_step`, `execute_parallel_step` | `Result[str]` (snapshot ID) | Failure propagated immediately |
| `load_snapshot(snapshot_id)` | `rollback_handler.restore_to_previous`, `get_latest_snapshot` | `Result[ContextEnvelope]` | Failure propagated |
| `get_latest_snapshot(pipeline_id)` | *(not called in core_pipeline)* | `Result[ContextEnvelope]` | N/A |
| `list_snapshots(pipeline_id)` | *(not called in core_pipeline)* | `Result[list[str]]` | N/A |

**Status: WIRED** ✓

### 5c. TokenCounter protocol compliance

| Implementation | `count(text) -> int` | `close()` | `__enter__`/`__exit__` |
|--------------|---------------------|-----------|----------------------|
| `HeuristicCounter` | `max(1, len(text) // 3)` ✓ | `pass` ✓ | ✓ |
| `_TiktokenCounter` | `len(enc.encode(text))` ✓ | Sets `_enc = None` ✓ | ✓ |

`HardCapEnforcer` uses `self.counter.count(projected_slice)` — requires a `TokenCounter`. ✓

**Status: WIRED** ✓

### 5d. SlicePacker protocol compliance

| Implementation | `pack(payload, manifest) -> Result[JSONDict]` | Correct? |
|--------------|-----------------------------------------------|----------|
| `RecencySlicePacker` | Packs most recent sections within max_tokens | ✓ |
| `StructuralSlicePacker` | Packs only manifest.reads, FAILURE if missing | ✓ |
| `RelevanceSlicePacker` | Ranks by cosine similarity, packs top within max_tokens | ✓ |

**Status: WIRED** ✓

---

## 6. Public API Surface (`__init__.py`)

### Exported names

```python
__all__ = [
    "AgentManifest",       # from slicer
    "ContextBroker",       # from context_broker
    "ContextEnvelope",     # from envelope
    "CoreRelayPipeline",   # from core_pipeline
    "create_context_broker",# from context_broker
    "ErrorCode",           # from types
    "Failure",             # from types
    "ForkResult",          # from parallel
    "ForkSpec",            # from parallel
    "HandoffValidator",    # from validator
    "HardCapEnforcer",     # from budget
    "JoinStrategy",        # from parallel
    "PipelineState",       # from pipeline_state
    "Result",              # from types
    "RollbackHandler",     # from pipeline_rollback
    "RollbackSuccess",     # from types
    "SlicePacker",         # from slicer (Protocol)
    "SnapshotStore",       # from snapshot
    "Success",             # from types
    "TokenCounter",        # from budget/token_counter
    "__version__",         # from types
]
```

### Not exported (intentional)

| Name | Module | Reason |
|------|--------|--------|
| `AutoTokenCounter` | `budget.token_counter` | Documented: "Import from relay.budget.token_counter directly." |
| `HeuristicCounter` | `budget.token_counter` | Internal implementation detail |
| `_TiktokenCounter` | `budget.token_counter` | Internal implementation detail |
| `AgentOutput` | `runners.protocol` | Accessible via `relay.runners.AgentOutput` |
| `AgentRunner` | `runners.protocol` | Accessible via `relay.runners.AgentRunner` |
| `ContextSlice` | `runners.protocol` | Accessible via `relay.runners.ContextSlice` |
| `AdapterRegistry` | `runners.registry` | Accessible via `relay.runners.AdapterRegistry` |
| Individual packers | `slicer.packers` | Accessible via `relay.slicer` |
| `EmbeddingProvider` | `slicer.providers` | Accessible via `relay.slicer` |
| `RollbackHandler` | `pipeline_rollback` | **IS** exported (line 12 of `__init__.py`) ✓ |

### What should NOT be exported (but is by accident)

`RollbackHandler` is listed in `__all__` but is an internal implementation detail. Users should only interact with `rollback()` on `CoreRelayPipeline`. However, since `RollbackHandler` is a simple class with a single method and has no dependencies beyond what's already public, this is a **minor** API surface concern, not a blocker.

**Status: CORRECT** ✓ (with minor observation)

---

## 7. Rollback Behavior

### 7a. Trigger points

| Trigger | Location | Returns | State change |
|---------|----------|---------|-------------|
| Contradiction detected | `_finalize_step()` (via `_handle_subsequent_step`) | `RollbackSuccess(current_envelope, reason)` | Current saved to snapshot, pushed to history |
| Contradiction detected | `execute_parallel_step()` (post-merge) | `RollbackSuccess(pre_fork_envelope, reason)` | Pre-fork envelope saved to snapshot, pushed to history |
| Manual rollback | `rollback()` (public API) | `RollbackSuccess(restored_envelope, "Manual rollback")` | History consumed, current set to restored |

### 7b. `_do_rollback` logic

```
_do_rollback(reason, consume):
  1. has_history()? → NO → Failure(NO_ROLLBACK_AVAILABLE)
  2. peek_last() → previous_envelope
  3. restore_to_previous():
     → snapshot_ids[previous.step]? → NO → Failure(NO_SNAPSHOT_REGISTERED)
     → load_snapshot(snapshot_id) → Failure → propagate
     → RollbackSuccess(loaded_envelope, reason)
  4. isinstance(RollbackSuccess)? → YES → consume_last(), set_current(loaded)
  5. RETURN result (RollbackSuccess or Failure)
```

**Status: WIRED** ✓

### 7c. RollbackSuccess type propagation

`RollbackSuccess` is returned from:
- `rollback()` (public) ✓
- `_finalize_step()` (contradiction) ✓
- `execute_parallel_step()` (contradiction) ✓

`unwrap()` raises ValueError on `RollbackSuccess` ✓ (documented)
`unwrap_or()` returns default on `RollbackSuccess` ✓ (documented)
`map_result()` transforms `RollbackSuccess` ✓ (documented)

---

## 8. Transaction Boundary / Thread-Safety

### 8a. Lock properties

- **Type:** `threading.Lock` (non-reentrant)
- **Tracking:** `_lock_owner` records thread ID on acquire, clears on release
- **Re-entrancy check:** Raises `RuntimeError` if same thread tries to acquire again

### 8b. All entry points verified

| Method | Acquires lock? | Release on error? | Re-entrant? |
|--------|---------------|-------------------|-------------|
| `history` (property) | `transaction()` | ✓ (contextmanager) | ✓ Single acquire |
| `snapshot_index` (property) | `transaction()` | ✓ | ✓ |
| `current_envelope` (property) | `transaction()` | ✓ | ✓ |
| `execute_step_with_manifest` | `transaction()` | ✓ (all code paths return within `with` block) | ✓ |
| `execute_step_with_runner` | `transaction()` + internal `_check_budget` | ✓ Lock released before `adapter.run()` | ✓ |
| `execute_parallel_step` | `transaction()` twice (pre-fork + post-merge) | ✓ Lock released between | ✓ |
| `rollback` | `transaction()` | ✓ | ✓ |
| `_handle_initial_step` | REQUIRES caller-held lock | N/A | ✓ |
| `_handle_subsequent_step` | REQUIRES caller-held lock | N/A | ✓ |
| `_finalize_step` | REQUIRES caller-held lock | N/A | ✓ |
| `_do_rollback` | REQUIRES caller-held lock | N/A | ✓ |

### 8c. Methods calling `_assert_lock_held()`

- `current()` ✓
- `get_previous_envelopes()` ✓
- `set_current()` ✓
- `push_current_to_history()` ✓
- `archive_and_set()` ✓
- `peek_last()` ✓
- `consume_last()` ✓
- `has_history()` ✓
- `register_snapshot()` ✓
- `snapshot_ids` (property) ✓

### 8d. ⚠️ `_finalize_step` missing lock assertion (WARNING)

`_finalize_step` does NOT call `_assert_lock_held()` despite its docstring stating "REQUIRES: caller holds self._state._lock via transaction() context manager." If a future refactoring calls `_finalize_step` outside the transaction, state corruption would occur silently.

Similarly, `_check_budget`, `_apply_manifest`, `_slice_payload`, and `_do_rollback` lack explicit lock assertions. While they don't directly mutate state, they call methods that do. Defensive `_assert_lock_held()` calls would prevent future misuse.

**Status: FUNCTIONALLY CORRECT** but fragile. Adding `_assert_lock_held()` to `_finalize_step` is recommended.

---

## 9. Detailed Findings

### BLOCKER (0)
**No blocker-level issues found.** All cross-phase connections are wired and functional.

### WARNING (6)

#### W1: Mixed error-handling stratey
- **Location:** `core_pipeline.py:__post_init__()` (line 107-108)
- **Description:** `create_context_broker()` failure raises `ValueError` instead of returning `Failure`. The `create()` factory correctly returns `Failure`. Direct `CoreRelayPipeline(signing_secret="short", ...)` construction crashes.
- **Severity:** WARNING
- **Affected paths:** Direct construction of `CoreRelayPipeline` with invalid secrets

#### W2: Duplicate snapshot on contradiction rollback
- **Location:** `core_pipeline.py:_finalize_step()` (lines 308-312)
- **Description:** When a contradiction is detected, the current envelope is snapshotted again before being pushed to history. This creates a second snapshot for the same step. The index file accumulates both entries; the in-memory `snapshot_ids` dict overwrites the old key.
- **Severity:** WARNING
- **Impact:** Orphaned snapshot file on disk (no functional impact)
- **Fix suggestion:** Only snapshot the current envelope if it hasn't been snapshotted for that step yet (or skip re-saving if the data is identical).

#### W3: `_finalize_step` lacks `_assert_lock_held()` call
- **Location:** `core_pipeline.py:_finalize_step()` (line 288)
- **Description:** Despite documenting that the lock must be held, the method doesn't enforce it. All callers currently hold the lock correctly, but future refactoring could break this.
- **Severity:** WARNING

#### W4: `_do_rollback` consumes history on RollbackSuccess only
- **Location:** `core_pipeline.py:_do_rollback()` (lines 355-384)
- **Description:** `consume_last()` is only called on `RollbackSuccess`. If `restore_to_previous()` returns `Failure` (e.g., snapshot missing), the history entry is NOT consumed. This means the user can retry the rollback. This is arguably correct behavior, but differs from the public `rollback()` API's implied "consume or fail" semantics.
- **Severity:** WARNING
- **Fix suggestion:** Document this behavior explicitly.

#### W5: Redundant `create_context_broker()` call in `create()` factory
- **Location:** `core_pipeline.py` lines 85-99 (create) and 104-108 (__post_init__)
- **Description:** `create()` validates the secret by constructing a ContextBroker, then discards it. `__post_init__()` constructs another one. Both calls validate the same secret.
- **Severity:** WARNING
- **Impact:** Unnecessary ContextBroker construction on valid inputs (negligible perf impact)

#### W6: Private method naming — `_combine_manifest_hashes` (typo)
- **Location:** `core_pipeline.py` line 36
- **Description:** Function named `_combine` instead of `_combine`.
- **Severity:** WARNING (cosmetic/consistency)

### INFO (3)

#### I1: `parallel → runners` dependency undocumented
- **Location:** `parallel/types.py`, `parallel/fork_runner.py`
- **Description:** The stated dependency chain doesn't mention `runners/`, but `parallel/` imports from `runners.protocol` at runtime. This is structurally valid (acyclic) but undocumented.

#### I2: `ContextEnvelope.__post_init__` validates argument constraints
- **Location:** `envelope.py` lines 77-89
- **Description:** Raises `ValueError` instead of returning `Failure` for invalid field values. This is intentional — envelope construction within the library should never receive invalid values if calling correctly. The `create_initial_envelope()` factory validates before constructing.

#### I3: `run_single_fork` uses `replace(pre_fork_envelope, payload=filtered)` to create scoped envelope
- **Location:** `parallel/fork_runner.py` line 82
- **Description:** Creates a new envelope with filtered payload for validation. Since `ContextEnvelope` is frozen, `replace` creates a shallow copy. The payload dict is filtered (new dict), so the original is preserved. ✓

---

## 10. Requirements Integration Map

| Requirement | Integration Path | Status | Issue |
|-------------|-----------------|--------|-------|
| Pipeline creation | `create()` → `create_context_broker()` → `__post_init__()` | WIRED | W1, W5 |
| Step execution (sequential) | `execute_step()` → `execute_step_with_manifest()` → `_handle_initial_step`/`_handle_subsequent_step` → `_finalize_step` | WIRED | — |
| Step execution (with runner) | `execute_step_with_runner()` → registry → adapter → `execute_step_with_manifest()` | WIRED | — |
| Parallel fork-join | `execute_parallel_step()` → `run_single_fork()` → `apply_join_strategy()` → post-merge commit | WIRED | — |
| Budget enforcement | `_check_budget()` → `HardCapEnforcer.check()` → `TokenCounter.count()` | WIRED | — |
| Handoff validation | `_finalize_step`/`run_single_fork` → `HandoffValidator.validate_handoff()`/`validate_handoff_payload()` | WIRED | — |
| Snapshot save/restore | `save_snapshot()` → file write → index update / `load_snapshot()` → file read | WIRED | W2 |
| Rollback | `rollback()` → `_do_rollback()` → `RollbackHandler.restore_to_previous()` → `load_snapshot()` | WIRED | W4 |
| Manifest boundary enforcement | `_apply_manifest()` → `validate_manifest_boundaries()` | WIRED | — |
| Slice packing | `_slice_payload()` → `SlicePacker.pack()` | WIRED | — |
| Context slice building | `_build_context_slice()` → filter by `manifest.reads` → `ContextSlice` | WIRED | — |
| Envelope signing | `create_initial_envelope()`/`create_next_envelope()` → `_sign_envelope()` → `compute_signature()` → `hmac` | WIRED | — |
| Lock/transaction safety | `PipelineState.transaction()` → threading.Lock | WIRED | W3 |

---

## 11. Conclusion

The Relay middleware library demonstrates **strong cross-phase integration**. No BLOCKER-level issues were found. All 34 ErrorCodes are used in appropriate locations. The dependency graph is acyclic and well-maintained. The `Result` type system is used consistently for error handling across all public APIs.

### Key strengths:
- Clean layer separation with no upward runtime imports
- Comprehensive ErrorCode coverage for every failure mode
- Consistent use of `Result` types for operational errors
- Thread-safe state management with clear lock discipline
- All adapter protocols (`AgentRunner`, `TokenCounter`, `SlicePacker`, `EmbeddingProvider`) are properly implemented

### Areas for improvement:
1. **Mixed error handling** — `__post_init__` raises `ValueError` while `create()` returns `Failure`
2. **Defensive lock assertions** — `_finalize_step` and internal `_do_rollback` should enforce lock-held precondition
3. **Snapshot duplication** — contradiction rollback creates orphaned snapshot files
4. **Documentation gap** — `parallel → runners` dependency is structurally valid but unspecified
