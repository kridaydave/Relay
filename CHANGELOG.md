# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).



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

## [0.1.0] - 2024-01-01

### Added

- **CoreRelayPipeline** — Main pipeline orchestration
- **ContextBroker** — Envelope creation and signing
- **HandoffValidator** — Contradiction detection and rollback triggering
- **SnapshotStore** — Checkpoint persistence and restore
- **Result types** — Success, Failure, RollbackSuccess for error handling
- **ContextEnvelope** — Immutable, signed context wrapper

### Fixed

- Initial release
