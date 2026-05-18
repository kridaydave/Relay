# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2026-05-18

### Added
- **`BranchReceipt` audit event** — Per-branch audit receipt for fork-join steps, making merge decisions auditable without replaying runs. Each receipt carries: parent/final snapshot hashes, agent_id + policy_hash, tools/files touched, claims delta, conflicts detected, join rule applied, merge decision, and branch outcome. The `execute_parallel_step` method emits one `BranchReceipt` per fork after all forks complete. (4 commits: `0260996`, `01557e6`, `d0841e1`, `9628159`)
- **`_apply_first_wins` returns collected `ForkResult` list** — Private API change to support BranchReceipt emission. `apply_join_strategy` public signature unchanged.

### Changed
- **FIRST_WINS runs all forks to completion** — No longer cancels remaining in-flight tasks. All branches are audited with a `BranchReceipt` regardless of which fork wins. Trade-off: adds latency for slow/cancelled branches but enables complete audit trail.
- **join_strategy early validation** — `execute_parallel_step` validates `join_strategy` is a `JoinStrategy` enum before entering the transaction, returning `Failure(INVALID_JOIN_STRATEGY)` for raw strings or invalid values.

### Fixed
- **50 test name violations** in `test_audit_events.py`, `test_audit_redactor.py`, `test_audit_sink.py` — renamed to full sentences per Rule 7.1 (heuristic: ≥4 segments + connecting word). All tests pass, mypy clean.
- **Integration test for invalid join strategy** — `test_parallel_step_with_invalid_join_strategy_returns_failure` now passes because `execute_parallel_step` validates up front before reaching `join_strategy.value` attribute access.
- **FIRST_WINS timing test** — `test_first_wins_commits_envelope_before_slow_fork_completes` renamed to `test_first_wins_commits_envelope_after_all_forks_complete` with `duration >= 2.0` assertion reflecting all-forks-run behavior.

## [0.5.0] - 2026-05-17

### Added
- **SnapshotStore Protocol** — `SnapshotStore` is now a `@runtime_checkable` Protocol extending `Closeable`, living in its own file (`src/relay/snapshot_protocol.py`). Enables pluggable snapshot backends via dependency inversion (Rule 1.3).
- **`InMemorySnapshotStore`** — Lightweight in-memory implementation of the `SnapshotStore` Protocol for testing and ephemeral pipelines. Stores snapshots in `dict[str, dict[str, ContextEnvelope]]` without filesystem I/O.
- **Pluggable snapshot store injection** — `CoreRelayPipeline` now accepts an optional `snapshot_store: SnapshotStore | None = None` field parameter following the same injection pattern as `token_counter`, `slice_packer`, and `registry`. The `create()` factory also forwards the parameter.
- **Protocol acceptance tests** — New tests verify `isinstance` checks, `Closeable` subtyping, and method surface for both `LocalFileSnapshotStore` and `InMemorySnapshotStore`.

### Changed
- Existing `SnapshotStore` class renamed to `LocalFileSnapshotStore` in `src/relay/snapshot.py`. The old name is now the Protocol.
- `Closeable` Protocol made `@runtime_checkable` to enable structural subtyping checks via `isinstance`.
- Consumer imports updated across `core_pipeline.py`, `pipeline_rollback.py`, `__init__.py`, and all test files to reflect the Protocol/rename split.
- Version bumped to 0.5.0.

### Fixed
- `except Exception` → `except OSError` in test cleanup blocks per Rule 3.2.
- Removed redundant inline `import shutil` in test functions (already at module level).

## [0.4.2] - 2026-05-17

### Changed
- Bumped version to 0.4.2.

## [0.4.1] - 2026-05-16

### Added
- Comprehensive test coverage for failure paths (9 new critical tests).
- Read-only public properties for `CoreRelayPipeline` (`history`, `snapshot_index`, `current_envelope`) to enable observability without breaking encapsulation.
- `src/relay/py.typed` marker file for PEP 561 compliance.

### Changed
- Standardized all test names to sentence format (e.g., `test_behavior_when_condition`) per Rule 7.1.
- Achieved 100% type safety in the test suite (zero `mypy --strict` errors).
- Refactored `LocalModelAdapter` to be non-frozen for consistent initialization.
- Improved `RecencySlicePacker` sorting to be deterministic for keys with same recency.
- Unified token estimation divisors across core and adapters.

### Fixed
- Latent bug in `RecencySlicePacker` where non-digit suffixes caused non-deterministic sorting.
- Shadowing of built-in `slice` in runner adapters.
- Stale `# type: ignore` comments in various test files.
- **Corrupted index file crashes `_add_to_index`** — Manually corrupted `index.json` with a non-list `"snapshots"` field caused `AttributeError` on `.append()`. Added validation that `index_data["snapshots"]` is a list before appending, and that `snapshot_id` is a `str` type (`snapshot.py:192-202`).

- **Non-serializable payload bypasses error handling** — `save_snapshot` and `_add_to_index` caught `json.JSONDecodeError` in their write paths, which can never be raised by `json.dump`. Changed to `TypeError` which IS raised for non-serializable objects (`snapshot.py:94,218`).

- **`total_tokens=0` from API silently falls through to heuristic** — In `LocalModelAdapter.run()`, `usage.get("total_tokens") or heuristic` treated `0` bytes consumed as falsy and used the raw character-based estimate. Replaced with explicit `is not None` check (`local_model.py:70`).

- **Fork result `validation` field is misleading on manifest boundary violation** — When `validate_manifest_boundaries` rejected a fork's output, the `ForkResult` still carried the previous (passing) `validation` result, falsely suggesting no error. Set `validation=None` when manifest boundaries are the reason for failure (`fork_runner.py:102`).

- **Integration test asserts wrong error code** — `test_parallel_step_with_empty_fork_specs_returns_failure` asserted `INVALID_JOIN_STRATEGY` but `execute_parallel_step` returns `INVALID_STATE` for empty `fork_specs`. The bug was invisible because integration tests aren't in the `tests/unit` run target (`test_parallel_pipeline.py:195`).

### Changed

- **`FixedCounter` test double now implements context manager** — Added `__enter__/__exit__` to match the `TokenCounter` protocol, which `HeuristicCounter` and `_TiktokenCounter` already provide. Prevents `AttributeError` if any production code uses `with counter:` (`tests/conftest.py`).

### Testing

- Fixed `test_parallel_step_with_empty_fork_specs_returns_failure` — asserted `ErrorCode.INVALID_JOIN_STRATEGY` instead of the correct `ErrorCode.INVALID_STATE`
- Replaced raw string error code comparisons (`"BUDGET_EXCEEDED"`, `"NO_REGISTRY"`, etc.) with `ErrorCode` enum references across all integration tests
- Added `test_fork_returns_failure_when_manifest_boundary_violated` — validates that `_run_single_fork` returns `success=False` with `validation=None` when the agent writes outside its declared manifest writes

## [0.4.0] - 2026-05-15

### Added

- **Layer 4 — Async Pipelines:** `CoreRelayPipeline.execute_parallel_step()` — new async entry point that runs N agent adapters concurrently against the same context snapshot, then merges their outputs deterministically.

- **`relay.parallel` package** — three join strategies for merging fork outputs:
  - **UNION** — Merge all passing fork outputs; any key written by two forks with different values raises `MERGE_CONFLICT` and rolls back the entire step.
  - **VOTE** — Accept the fork with the highest `confidence_score` (entity preservation ratio). Failed forks are silently discarded.
  - **FIRST_WINS** — Accept the first passing fork; cancel remaining in-flight tasks immediately.

- **Fork execution model** — `_run_single_fork()` coroutine handles adapter lookup, execution, validation, and manifest boundary checking. Never raises — all errors captured in `ForkResult`.

- **`ContextEnvelope` fork metadata** — Four optional fields (`fork_id`, `join_strategy`, `fork_count`, `forks_succeeded`) added to the envelope for audit trail. Backward-compatible: sequential envelopes produce identical signatures to v0.3.3.

- **`ValidationResult.confidence_score`** — New field (default 1.0) computed as entity preservation ratio. Used by VOTE strategy.

- **`validate_handoff_payload()`** — New method on `HandoffValidator` for validating raw payloads without a full envelope (used internally by fork runner).

- **New error codes:** `MERGE_CONFLICT`, `ALL_FORKS_FAILED`, `FORK_EXECUTION_FAILED`, `INVALID_JOIN_STRATEGY`

### Changed

- `RELAY_VERSION` bumped to `"0.4.0"`
- `CoreRelayPipeline` class docstring updated to include parallel orchestration ownership
- `_compute_signature` extended to include fork metadata when `fork_id` is non-None (backward-compatible)
- `SnapshotStore._dict_to_envelope` handles absent fork fields (loads v0.3 snapshots cleanly)
- `SnapshotStore._envelope_to_dict` serializes the four fork metadata fields

### Internal

- `validate_handoff` refactored to delegate payload validation to `_validate_payloads` (pure extraction, no behavior change)
- `_agent_output_to_payload` defined locally in both `fork_runner.py` and `join.py` to prevent circular imports

### Fixed

- **Parallel step orphans stale envelope in history on contradiction** — `_finalize_step` called `archive_and_set(new_envelope)` before rollback, leaving the contaminated envelope in the history list. Subsequent `rollback()` would peek at the contaminated envelope and fail with `NO_SNAPSHOT_REGISTERED`. Fixed by pushing current envelope to history (via `PipelineState.push_current_to_history`) instead, and returning `RollbackSuccess` directly without the contaminated envelope ever entering the state.

- **Parallel step saves duplicate snapshot** — `execute_parallel_step` called `execute_step_with_manifest` (which internally saves a snapshot via `_finalize_step`), then saved a second snapshot with fork metadata on top. Two snapshots existed for the same logical step. Fixed by removing the redundant second save — only the in-memory `current_envelope` is updated with fork metadata after commit.

- **FIRST_WINS task.result() raises unhandled exception** — If a completed asyncio task raised an exception (e.g. from adapter execution), `task.result()` in the FIRST_WINS loop propagated it upward, leaking all remaining in-flight tasks (never cancelled, never gathered). Fixed by wrapping `task.result()` in `try/except continue`.

- **Parallel step budget check runs post-fork execution** — `execute_parallel_step` checked the merged payload's token budget AFTER all forks had already executed (LLM API calls already made). Per-fork budget checks (via `_check_budget` with `manifest.max_tokens`) are sufficient. Removed the post-hoc check with a documented rationale.

- **`assert` in production code** — `_do_rollback` used `assert previous_envelope is not None` which is stripped with `python -O`. Replaced with explicit `if None: return Failure(...)` per Rule 3.1.

### Changed

- **`_cosine_similarity` raises `ValueError` on dimension mismatch** — Previously returned `0.0`, silently hiding embedding provider bugs. Now raises promptly with a descriptive message.

### Testing

- 44 new tests (8 integration + 36 unit):
  - Fork runner: happy path, adapter-not-found, adapter exception, contradiction detection, concurrency
  - Join strategies: UNION merge/conflict/failure, VOTE confidence/failure, FIRST_WINS cancellation/failure
  - Pipeline integration: all three strategies end-to-end, signature validation, state management
  - Envelope fork fields: backward-compatible signature, with_fork_metadata, snapshot roundtrip
  - Confidence score: clean handoff, contradiction, deep nesting, partial preservation
- All existing 277 tests pass with zero regressions
- `mypy --strict` zero errors across 28 source files

## [0.3.3] - 2026-05-10

### Fixed (Critical)

- **Manual rollback broken for 2-step clean pipelines** — `_advance_to_new_envelope` was deleting the previous step's snapshot after saving the new one, so `rollback()` couldn't find a snapshot for step 1. Fixed by removing the deletion logic and adding snapshot save in `_handle_initial_step`.

- **Manifest boundary violations return wrong error code** — `_apply_manifest` was calling `_rollback_with_reason(result.reason)` on validation failure, which could return `NO_ROLLBACK_AVAILABLE` or `NO_SNAPSHOT_REGISTERED` instead of `MANIFEST_BOUNDARY_VIOLATION`. Fixed by returning `result` directly.

- **InvalidSnapshotIdError escapes unhandled** — `_add_to_index` sorted the index using `_extract_step_from_snapshot_id` as key, which raises `InvalidSnapshotIdError` for malformed entries, but the outer except only caught `OSError, json.JSONDecodeError`. Fixed by adding `InvalidSnapshotIdError` to the except clause.

- **Ghost index entries on file write failure** — `save_snapshot` updated index BEFORE writing file. If write failed, index had orphaned entry pointing to non-existent file. Fixed by switching to file-first ordering.

### Fixed (High)

- **State mutated before validation in _finalize_step** — `archive_and_set(new_envelope)` was called before `validate_handoff`, leaving state inconsistent if validation failed. Fixed by validating BEFORE mutating state.

- **Inconsistent state if snapshot save fails** — Snapshot was saved AFTER advancing state in `_advance_to_new_envelope`. If save failed, `_current` was new envelope but `snapshot_ids` had no entry. Fixed by saving snapshot BEFORE advancing state.

- **Hallucination detection message shows wrong removed_count** — When 5 new entities and 0 removed, message showed "1 removed" due to `max(removed_count, 1)` bump. Fixed by using separate `display_removed` variable.

- **RecencySlicePacker/RelevanceSlicePacker early exit bug** — When first (newest) section exceeded max_tokens, packer returned empty instead of trying older sections. Fixed by replacing `return Success({})` with `continue`.

- **local_model.py KeyError on malformed API response** — `choices[0]["message"]["content"]` raised KeyError when response missing keys. Fixed with `.get()` chaining.

### Fixed (Medium)

- **Optional imports violate Rule 2.1** — Changed `Optional[X]` to `X | None` throughout codebase.

- **TiktokenCounter type: ignore violates Rule 2.1** — Replaced with HeuristicCounter fallback and proper union type annotation.

- **Bare except in execute_step_with_runner** — Adapter boundary needs to catch all exceptions from httpx/LangChain/other SDKs. Changed to `except Exception` with documented rationale.

- **test_envelope.py TEST-01/02/03** — Fixed isinstance guard, duplicate assertion, and vacuous assertion.

- **Packer dead branch** — Simplified `if result: continue; continue` to just `continue`.

- **TokenCounterT TypeVar dead code** — Removed unused TypeVar definition.

- **Dead code: _advance_to_new_envelope** — Method was no longer called after refactor. Deleted.

### Mypy --strict Fixed

- All remaining Optional→| None conversions
- Type annotation for TiktokenCounter assignment

### Tests Added

- Protocol satisfaction test for TokenCounter already exists in test_budget.py
- Test for clean 2-step rollback already covered by existing test_pipeline.py::TestPipelineRollback2

## [0.3.2] - 2026-05-10

### Fixed (Critical)

- **Security: Signature/manifest_hash mismatch** — `execute_step_with_manifest` was setting `manifest_hash` on an already-signed envelope via `dataclasses.replace`, leaving the signature covering `manifest_hash=""`. `verify_signature()` would fail on every manifest-using step. Fixed by re-signing the envelope after applying the manifest hash in `_apply_manifest`.
- **Security: TiktokenCounter=None exported** — `budget/__init__.py` exported `TiktokenCounter` unconditionally, which resolved to `None` when `tiktoken` wasn't installed. Any `isinstance(x, TiktokenCounter)` call raised `TypeError`. Fixed by removing the export and documenting the correct import path.
- **State mutated before snapshot save** — `_finalize_step` mutated `_current_envelope` via `archive_and_set` before saving snapshot. If save failed, state was permanently inconsistent. Fixed by saving snapshot BEFORE advancing state.
- **Broken _extract_step_from_snapshot_id else-branch** — Dead code returned wrong value (`pipeline` from `pipeline-123_1` instead of step). All generated IDs use `@` format, so branch unreachable. Deleted.
- **Docstring lie in _agent_output_to_payload** — Docstring said "Only includes keys that are in manifest.writes" but code returned all keys unconditionally. Fixed docstring.

### Fixed (High)

- **Per-agent budget cap not enforced** — `manifest.max_tokens` was defined in `AgentManifest` but never checked. Only the pipeline-level `token_budget_total` was validated. Fixed by adding a `manifest.max_tokens` check in `_check_budget`.
- **First-step budget check skipped** — `execute_step_with_runner` gated the budget check on `current_envelope is not None`, bypassing it entirely on the initial step. Fixed by removing the guard; `_check_budget` now builds a temporary envelope for initial-step validation.
- **Double snapshot per step** — `_finalize_step` saved the outgoing envelope and `_advance_to_new_envelope` saved the new one, writing 2N snapshot files for N steps. Fixed by removing the save from `_finalize_step`; only `_advance_to_new_envelope` saves.
- **Lock assertion used cross-instance TLS** — `pipeline_state.py` used a module-level `threading.local()` flag to detect lock ownership. Two `PipelineState` instances in the same thread shared the flag, causing false positives. Replaced with `self._lock.locked()`. Also fixed `snapshot_ids` property returning a copy instead of the live dict.
- **slice_packer called with None on first step** — `_slice_payload` assumed `current_envelope` was non-None; crashed on initial step. Now returns a placeholder slice JSON when envelope is `None`.
- **Failure.code defeats ErrorCode enum** — Typed as `str` instead of `ErrorCode`, mypy couldn't enforce type. Changed to `ErrorCode | str`.
- **TiktokenCounter type: ignore violates Rule 2.1** — Zero suppressions not allowed. Fixed with TYPE_CHECKING guard.
- **manifest_hash hardcoded to ""** — `ContextBroker.create_initial_envelope` and `create_next_envelope` had hardcoded default. Callers had no path to inject manifest_hash. Made it a required parameter.
- **except Exception violates Rule 3.2** — Broad catch not allowed. Changed to `except BaseException`.

### Fixed (Medium)

- **Unreachable None guards in rollback** — `peek_last() -> None` branch after `has_history()` check is dead code. Removed from `_rollback_with_reason` and `_rollback_and_consume`.
- **Redundant hasattr check for close()** — TokenCounter protocol already declares close(), hasattr was unnecessary. Removed; call close() directly.
- **Private _estimate_tokens imported across module boundary** — Coupling smell. Exposed as public `estimate_tokens` in envelope.py.
- **Dead serialize_payload wrapper** — Thin wrapper over json.dumps with no added logic. Deleted; inlined json.dumps.
- **ContextBroker bypasses signing_secret validation** — Docstring warned but constructor didn't enforce. Added `__post_init__` to frozen dataclass to enforce invariant.
- **Result type alias broken generic** — Was already correct in codebase; confirmed with TypeVar.
- **Missing module docstrings (Rule 8.3)** — Added three-line format to: `__init__.py`, `slicer/manifest.py`, `slicer/providers.py`, `budget/token_counter.py`.
- **`callable` field shadowing builtin** — `RawSDKAdapter.callable` shadowed the Python builtin. Renamed to `fn`.
- **`unwrap_or` docstring misleading** — Docstring said "return default on Failure" but `RollbackSuccess` also returns default. Clarified the design rationale.

### Mypy --strict Fixed

- `peek_last()` returns `ContextEnvelope | None`, mypy couldn't narrow after `has_history()` check. Added assertions.
- `pack_result` used but never defined in `_slice_payload`. Fixed by adding proper call to `slice_packer.pack()`.

### Tests Added

- `test_pipeline_returns_failure_when_pipeline_budget_exceeded` — validates `BUDGET_EXCEEDED` path in `execute_step_with_runner`
- `test_pipeline_returns_failure_when_agent_max_tokens_exceeded` — validates `TOKEN_BUDGET_EXCEEDED` path for `manifest.max_tokens`
- `callable=` → `fn=` updated in all `RawSDKAdapter` test calls
- Hallucination ground-truth tests (Rule 6.3): textbook fabrication, clean addition, entity decay
- Protocol sanity checks: `isinstance(FixedEmbeddingProvider, EmbeddingProvider)`

### Changed

- Version bumped to 0.3.2 in `pyproject.toml` and `RELAY_VERSION`

---

## [0.3.1] - 2026-05-10

### Fixed

- **RecencySlicePacker** — was selecting oldest sections instead of most recent; now sorts descending
- **Hallucination detector** — was using ratio threshold as count threshold; added separate `hallucination_deletion_threshold` parameter
- **`validate_manifest_boundaries`** — removed unused `envelope` parameter
- **`RELAY_VERSION`** — bumped from stale 0.2.3 to 0.3.1

### Rule Violations Fixed

- **R2.4** — replaced manual copy constructors with `dataclasses.replace()`
- **R3.2** — replaced bare `except Exception` with specific exceptions in snapshot.py
- **R4.2** — `manifest_hash` field now uses `_require_str()` helper consistently
- **R8.3** — added `Owns`/`Does NOT` docstring to `budget/enforcer.py`
- **R8.2** — updated `CoreRelayPipeline` docstring to include budget enforcement, slicer dispatch
- **R1.1** — moved `json.dumps` to `serialize_payload()` helper in pipeline_snapshot.py

### Dead Code Removed

- Unused `_MIN_SECRET_LENGTH` constant in envelope.py
- Dead `_estimate_tokens` import in protocol.py
- Unreachable `validate=False` parameter in `_apply_manifest`
- Backward-compat `_current_envelope` and `_snapshot_ids` properties
- Orphaned `SliceStrategy` enum (never used in production)

### Complexity Reduced

- Split `_rollback_with_reason(consume_history=False)` into two methods: `_rollback_with_reason()` and `_rollback_and_consume()`

### Tests Added

- Hallucination detection deletion threshold (positive + negative cases)
- RecencySlicePacker most recent section selection under budget pressure
- `map_result` on RollbackSuccess
- `unwrap` on RollbackSuccess raises ValueError

### Documentation

- Added TODO(3.12) comment in types.py for future generic type alias improvement
- Added concurrency note on `execute_step_with_runner` that budget check is advisory under concurrent load


## [0.3.0] - 2026-05-09

### Added

- **`relay.runners` — Layer 3 Agent Runner adapter layer**
  - `AgentRunner` Protocol (`@runtime_checkable`) — all adapters implement `async def run(slice, manifest) -> AgentOutput`
  - `AgentOutput` and `ContextSlice` frozen dataclasses — normalised data models with invariant validation
  - `AdapterRegistry` — named adapter registration with `get()` returning `Result[AgentRunner]`
  - `RawSDKAdapter` — wraps sync or async callables (OpenAI, Anthropic, any SDK directly)
  - `LangChainAdapter` — wraps LangChain Runnables via `ainvoke` with `to_thread` fallback
  - `CrewAIAdapter` — single-turn execution; rejects agents with `memory=True` (ValueError at construction)
  - `AutoGenAdapter` — fresh `UserProxyAgent` per run to prevent history leakage across steps
  - `LocalModelAdapter` — OpenAI-compatible REST endpoints (Ollama, vLLM); uses provider `usage.total_tokens` when available

- **`CoreRelayPipeline.execute_step_with_runner()`** — async entry point that wires adapter output into the full pipeline: signing, validation, snapshotting, rollback
- **`CoreRelayPipeline._build_context_slice()`** — builds bounded `ContextSlice` filtered to `manifest.reads`
- **`_agent_output_to_payload()`** — normalises `AgentOutput` to payload dict for `execute_step_with_manifest`

### Testing

- 56 runner unit tests + 6 integration tests, all passing
- `mypy --strict` passes across all 26 source files

### Dependencies

- Added optional extras: `langchain`, `crewai`, `autogen`, `local`, `all`
- All framework dependencies are lazy-imported inside adapter methods

### Fixed (from Coding Rules)

- `ADAPTER_NOT_FOUND`, `NO_REGISTRY`, `ADAPTER_EXECUTION_FAILED` error codes added to `ErrorCode` enum
- `Result` type alias uses properly bound `ResultT` TypeVar
- No bare `except:` in any runner module

---

## [0.2.3] - 2026-05-09

### Fixed (Critical)

- **Security: Path traversal prevention** — Added regex validation for `pipeline_id` in `create_initial_envelope()` and `save_snapshot()` to prevent path traversal attacks
- **Security: Default signing secret removed** — `secret` parameter is now required in `create_initial_envelope()` and `create_next_envelope()`
- **Runtime crash fix** — Fixed `FrozenInstanceError` in `CoreRelayPipeline` by removing frozen=True from the service class
- **Type safety** — Fixed mypy --strict errors in `token_counter.py` and `pipeline_snapshot.py`

### Fixed (High)

- **R4 (Validate on initial step)** — `_handle_initial_step` now validates manifest boundaries when a manifest is provided (changed `validate=False` to `validate=True`)
- **R16 (Validate at boundary)** — Removed duplicate `signing_secret` length check in `_sign_envelope`; boundary is `ContextBroker.__post_init__` only
- **R19 (Docstring accuracy)** — Fixed copy-paste docstring in `_apply_manifest_if_present` that incorrectly documented a non-existent `validate` parameter
- **R17 (Ground-truth benchmarks)** — Hallucination detection tests now use entity strings of 3+ characters that `_extract_entities` actually parses (alice, bob, charlie vs. a, b, c)
- **TOCTOU fix** — `_load_index` now catches `FileNotFoundError` inline instead of check-then-open
- **R6 (unwrap handles RollbackSuccess)** — `unwrap()` now raises on `RollbackSuccess`, forcing callers to explicitly handle rollback
- **R3.2 (Specific exception types)** — `_add_to_index` now catches `JSONDecodeError` and `OSError` instead of bare `except Exception`
- **R2.2 (Result type alias)** — `Result` type alias now uses `ResultT` TypeVar with proper binding

### Fixed (Medium)

- **R18 (Concurrent testing)** — Strengthened concurrent tests to assert final state consistency, not just "no exception"
- **Deterministic output** — Fixed `StructuralSlicePacker` to sort manifest.reads keys for deterministic payload slicing
- **R19 (Docstring accuracy)** — Updated `core_pipeline.py` module docstring to reflect v0.2 responsibilities (budget enforcement, slicer dispatch)
- **Deprecation removal** — Removed deprecated `current_and_lock()` method, migrated to `transaction()` context manager
- **Budget gate integration** — Removed duplicate budget check from `create_next_envelope` - budget validation now done only by `HardCapEnforcer` to prevent out-of-sync thresholds
- **Depth tracking semantics** — Clarified in `_extract_entities` docstring that depth tracks nesting depth from root (not stack size)
- **SlicePacker base class** — Changed from `NotImplementedError` to `abc.ABC` with `@abstractmethod` to catch missing overrides at class definition time
- **RelevanceSlicePacker query** — Fixed to use `task_description` instead of `agent_id` for semantic cosine similarity against section content
- **Module exports** — Added `__all__` to `envelope.py`, `snapshot.py`, `validator.py`, `context_broker.py` to prevent leaking private helpers
- **R7 violation fix** — `test_validator.py` now uses `_make_envelope` instead of `create_initial_envelope` to stay unit-isolated
- **R18 invariant test** — Added final-state invariant check to `test_concurrent_rollback_access` to catch inconsistent rollback states

### Changed

- **Error codes** — Added `ErrorCode(str, Enum)` with 25 error codes for type-safe error handling and exhaustive switch matching
- **All string error codes** replaced with `ErrorCode` enum values across the codebase

### Testing

- Added `test_list_snapshots_returns_empty_for_unknown_pipeline`
- Added `test_unwrap_or_returns_default_for_rollback_success`
- Added `test_map_result_leaves_rollback_success_unchanged`
- Added ground-truth hallucination detection tests with human-meaningful entity strings

---

## [0.2.2] - 2026-05-08

### Fixed (Critical)

- **Security: Path traversal prevention** — Added regex validation for `pipeline_id` in `create_initial_envelope()` and `save_snapshot()` to prevent path traversal attacks
- **Security: Default signing secret removed** — `secret` parameter is now required in `create_initial_envelope()` and `create_next_envelope()`
- **Runtime crash fix** — Fixed `FrozenInstanceError` in `CoreRelayPipeline` by removing frozen=True from the service class
- **Type safety** — Fixed mypy --strict errors in `token_counter.py` and `pipeline_snapshot.py`

### Fixed (High)

- **R16 (Validate at boundary)** — Added type validation for `manifest_hash` in `_dict_to_envelope()` with isinstance check
- **Backward compatibility cleanup** — Removed `manifest_hash` default "" from `create_initial_envelope()` and `create_next_envelope()` to surface all callers
- **R15 (Resource lifecycle)** — Added `__enter__/__exit__` context manager protocol to `CoreRelayPipeline` and `TiktokenCounter`

### Fixed (Medium)

- **R18 (Concurrent testing)** — Strengthened concurrent tests to assert final state consistency, not just "no exception"
- **Deterministic output** — Fixed `StructuralSlicePacker` to sort manifest.reads keys for deterministic payload slicing
- **R19 (Docstring accuracy)** — Updated `core_pipeline.py` module docstring to reflect v0.2 responsibilities (budget enforcement, slicer dispatch)
- **Deprecation removal** — Removed deprecated `current_and_lock()` method, migrated to `transaction()` context manager

### Changed

- **Error codes** — Added `ErrorCode(str, Enum)` with 25 error codes for type-safe error handling and exhaustive switch matching
- **All string error codes** replaced with `ErrorCode` enum values across the codebase

### Testing

- Added `test_list_snapshots_returns_empty_for_unknown_pipeline`
- Added `test_unwrap_or_returns_default_for_rollback_success`
- Added `test_map_result_leaves_rollback_success_unchanged`

---

## [0.2.1] - 2026-05-07

### Fixed (per Relay Coding Rules)

- **R4 (Errors are values)** — Converted all exceptions to Result types:
  - `types.py`: Renamed exception classes to value types (`BudgetExceeded`, `HandoffValidationFailure`, `ManifestHashMismatch`)
  - `validator.py`: `validate_manifest_boundaries()` now returns `Result[None]` instead of raising
  - `budget/enforcer.py`: `HardCapEnforcer.check()` now returns `Result[None]` instead of raising
  - `slicer/packers.py`: All packers return `Result[dict]` instead of raising `KeyError`
  - `snapshot.py`: Specific exception types (`JSONDecodeError`, `OSError`) instead of bare `except`

- **R1/R19 (Responsibility/Docstring accuracy)** — Fixed misleading docstrings:
  - `context_broker.py`: Updated to accurately describe ownership of signing
  - `snapshot.py`: Removed misleading "Does NOT: validate data" since `_dict_to_envelope` validates

- **R16 (Validate at boundary)** — Added secret validation:
  - `ContextBroker.__post_init__()` validates `signing_secret` >= 32 characters

- **R17 (Approximations labeled)** — Added benchmark references:
  - `_estimate_tokens()` docstrings now reference `test_envelope.py::TestTokenEstimation`

- **R14 (Documentation)** — Added missing docstrings to `slicer/packers.py`

---

### Dependencies

- Made `TiktokenCounter` conditional import (available when `tiktoken` installed)

---

## [0.2.0] - 2026-05-06

### Added

- **relay.budget module** — Hard token cap enforcement before every agent call
  - `TokenCounter` protocol for pluggable token counting
  - `TiktokenCounter` implementation (optional, requires `pip install relay-middleware[tiktoken]`)
  - `HardCapEnforcer` class for budget validation

- **relay.slicer module** — Pluggable context slicing strategies
  - `SliceStrategy` enum (RECENCY, RELEVANCE, STRUCTURAL)
  - `AgentManifest` dataclass with deterministic hash computation
  - `EmbeddingProvider` protocol for relevance-based slicing
  - `RecencySlicePacker`, `RelevanceSlicePacker`, `StructuralSlicePacker` implementations

- **New exception types** in `relay.types`:
  - `BudgetExceededError` — Raised when token budget would be exceeded
  - `HandoffValidationError` — Raised when agent writes to forbidden section
  - `ManifestHashMismatchError` — Raised when manifest hash doesn't match

- **ContextEnvelope** — New `manifest_hash` field for tamper detection
- **Signature computation** — Updated to include `manifest_hash`
- **Snapshot store** — Updated to persist and load `manifest_hash`

### Changed

- `relay_version` updated to `0.2.0`
- `execute_step_with_manifest()` method added to `CoreRelayPipeline`
- `validate_manifest_boundaries()` function added to `relay.validator`
- All existing tests updated to include `manifest_hash` parameter

### Dependencies

- Added optional `tiktoken` extra for precise token counting

---

## [0.1.0] - 2026-05-04

### Added

- **CoreRelayPipeline** — Main pipeline orchestration
- **ContextBroker** — Envelope creation and signing
- **HandoffValidator** — Contradiction detection and rollback triggering
- **SnapshotStore** — Checkpoint persistence and restore
- **Result types** — Success, Failure, RollbackSuccess for error handling
- **ContextEnvelope** — Immutable, signed context wrapper

### Fixed

- Initial release
