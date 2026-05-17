# Coding Conventions

**Analysis Date:** 2026-05-17

## Main Attraction
**Rules:** Every rule in @docs/Relay Coding Rules.md must be enforced -- No releases if the rules arent followed.
**Exceptions:** Tests with logic that PHYSICALLY CANNOT follow the rules are allowed to pass
**Scope:** All code in the repo must follow the rules. No exceptions.
**Methods:** Everything must follow @docs/Relay Design Document.md with 0 scope creep


## Naming Patterns

**Files:**
- `snake_case.py` for all modules — matches project conventions (e.g. `core_pipeline.py`, `context_broker.py`, `pipeline_state.py`)
- Test files prefixed with `test_` (e.g. `test_validator.py`, `test_pipeline.py`)
- Test conftest files named `conftest.py` at any directory level

**Functions:**
- `snake_case` for all functions and methods, both public and private
- Private functions/methods prefixed with `_` (e.g. `_detect_hallucination`, `_check_budget`, `_handle_initial_step`)
- Test functions prefixed with `test_` and use sentence-style names (Rule 7.1):
  ```python
  # CORRECT — full sentence describing behavior
  def test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget() -> None:
  
  # CORRECT — behavior + condition pattern
  def test_success_contains_value() -> None:
  ```
- Test names validated by pre-commit hook via `scripts/check_test_names.py` — must have ≥4 underscore-delimited segments and at least one connecting word (when, returns, raises, with, on, after, etc.)
- Factory/helper functions use `make_` prefix in tests: `make_test_slice()`, `make_test_manifest()`, `make_fork_spec()`, `make_passing_fork_result()`
- Factory classmethods named `create` (e.g. `CoreRelayPipeline.create()`, `create_context_broker()`, `create_initial_envelope()`)

**Variables:**
- `snake_case` for all variables
- Type annotations required on all variables (enforced by `mypy --strict`)
- Module-level constants: `SCREAMING_SNAKE_CASE` (e.g. `MAX_EXTRACTION_DEPTH = 50`, `MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024`)
- Private module-level: `_SAFE_ID`, `_ESTIMATOR`, `_MAX_STEP`

**Types:**
- `PascalCase` for classes, protocols, enums, and type aliases
- Classes: `CoreRelayPipeline`, `ContextBroker`, `HandoffValidator`, `SnapshotStore`, `PipelineState`
- Protocols: `TokenCounter`, `EmbeddingProvider`, `AgentRunner`, `Closeable` — defined as `@runtime_checkable` protocols in dedicated files
- Data classes: `ContextEnvelope`, `ContextSlice`, `AgentOutput`, `ForkResult`, `ForkSpec`, `ValidationResult`, `AgentManifest`
- Enums: `ErrorCode` (StrEnum), `JoinStrategy`
- Type alias `type` keyword with Python 3.12+ syntax:
  ```python
  type Result[T] = Success[T] | RollbackSuccess[T] | Failure
  ```
- Special type: `JSONDict = dict[str, object]` — used for all JSON-serializable dictionary params

## Code Style

**Formatting:**
- No explicit formatter configured (`pyproject.toml` has no `[tool.black]` or `[tool.ruff]` sections)
- Style enforced indirectly by `mypy --strict` and code review

**Linting:**
- `mypy --strict` with zero suppressions — `mypy.ini` enables all strict flags:
  ```
  strict = True
  warn_return_any = True
  disallow_untyped_defs = True
  disallow_incomplete_defs = True
  disallow_untyped_calls = True
  disallow_any_expr = True
  disallow_any_decorated = True
  warn_unused_ignores = True
  ```
- **No `# type: ignore`** allowed anywhere — when mypy complains, fix the code
- **No bare `Any`** — only permitted at untyped boundaries (raw JSON from disk)
- Some modules get relaxed `disallow_any_expr = False` (`token_counter.py`, `local_model.py`)
- Test files get relaxed: `disallow_any_expr = False`, `disallow_any_decorated = False`

- Pre-commit hooks (`.pre-commit-config.yaml`):
  1. `mypy --strict src/`
  2. `pytest tests/unit/`
  3. `check-test-names` (runs `scripts/check_test_names.py`)

**Line Length:** Not explicitly configured — code reviewed manually

## Type System Conventions

**Generic Result type:**
```python
# Python 3.12+ type alias syntax
type Result[T] = Success[T] | RollbackSuccess[T] | Failure

# Usage as return type
def execute_step(self, agent_output: JSONDict) -> Result[ContextEnvelope]: ...
```

**Frozen dataclasses for all domain values:**
```python
@dataclass(frozen=True)
class ContextEnvelope:
    relay_version: str
    pipeline_id: str
    step: int
    # ... more fields
```

**Protocols for dependency inversion:**
```python
@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    def close(self) -> None: ...
```

**Every function has return type annotation — including private methods:**
```python
def _detect_hallucination(self, previous_payload: JSONDict, current_payload: JSONDict) -> str | None: ...
def _check_budget(self, manifest: AgentManifest | None, current_envelope: ContextEnvelope | None, agent_output: JSONDict | None = None) -> Result[None]: ...
```

## Module Docstring Format

Every module uses the three-line format (Rule 8.3):
```python
"""One-sentence description of the module.

Owns: comma-separated list of responsibilities.
Does NOT: things a reader might expect but this module deliberately avoids.
"""
```

Examples:
- `src/relay/types.py`: `"""Result types and error handling for Relay. Owns: Success, Failure, and Result union types, __version__. Does NOT: handle specific domain errors, validate data, or make decisions."""`
- `src/relay/core_pipeline.py`: `"""Core pipeline orchestration for Relay. Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch. Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies."""`
- `src/relay/context_broker.py`: `"""Context broker for envelope lifecycle management. Owns: envelope creation, signing, pipeline ID validation, rollback detection. Does NOT: execute agents, persist envelopes, or manage pipeline state."""`

## Import Organization

**Order:**
1. Standard library imports (e.g. `asyncio`, `hashlib`, `uuid`, `from dataclasses import dataclass`)
2. Third-party imports (e.g. `pytest`)
3. Local/package imports (`from relay.types import ...`, `from relay.envelope import ...`)

**No circular imports** — strict layering enforced:
```
types.py → envelope.py → snapshot.py → validator.py → context_broker.py → budget/ + slicer/ → pipeline_state.py → pipeline_rollback.py + parallel/ → core_pipeline.py
```

**TYPE_CHECKING guards** for type-only imports to break potential cycles:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from relay.slicer.manifest import AgentManifest
```

**Path Aliases:**
- Package root: `src/relay/` is installed as `relay` package
- All imports use absolute package paths: `from relay.types import Result`, `from relay.envelope import ContextEnvelope`
- Test doubles imported via absolute path: `from tests.conftest import FixedCounter`

## Error Handling

**Patterns:**
- **`Result[T]` is the contract** — no exceptions for operational errors (Rule 3.1)
- Raise only for programmer errors: `ValueError`, `AssertionError`, `MaxDepthExceededError`
- Return `Failure` for operational errors: missing file, budget exceeded, validation failed, corrupted JSON
- Pattern for checking results:
  ```python
  result = self._context_broker.create_initial_envelope(...)
  if isinstance(result, Failure):
      return result
  new_envelope = result.value  # Safe after isinstance check
  ```
- `Failure` carries `reason: str` and `code: ErrorCode` — codes are an enum in `src/relay/types.py`
- `Success[T]` wraps a single `value: T`
- `RollbackSuccess[T]` wraps both `value: T` and `reason: str`
- Helper functions: `is_success()`, `is_failure()`, `unwrap()` (raises on non-Success), `unwrap_or()` (returns default), `map_result()`, `map_error()`
- **No bare `except:`** — always catch specific exception types (Rule 3.2):
  ```python
  try:
      agent_output = await adapter.run(slice_, manifest)
  except Exception as e:
      return Failure(reason=f"Adapter '{adapter_name}' failed: {type(e).__name__}: {e}",
                     code=ErrorCode.ADAPTER_EXECUTION_FAILED)
  ```

## Immutability & State Management

- **All domain value types are `@dataclass(frozen=True)`** — never mutable
- Use `dataclasses.replace()` or `with_*` methods for modified copies:
  ```python
  envelope_with_hash = envelope.with_manifest_hash(manifest_hash)
  signed = envelope_with_hash.with_signature(compute_signature(envelope_with_hash, secret))
  ```
- Pipeline state managed via `PipelineState` with `threading.Lock` and `transaction()` context manager
- Lock is non-reentrant — method docstrings document `REQUIRES: caller holds self._state._lock via transaction() context manager`
- `_assert_lock_held()` called within lock-required methods

## Logging

**Framework:** Standard `logging` module (used in `src/relay/snapshot.py`)
```python
import logging
logger = logging.getLogger(__name__)
```

**Patterns:**
- Logging is minimal — most error handling goes through `Result` types
- `snapshot.py` is the primary consumer for logging

## Comments

**When to Comment:**
- Docstrings follow three-line format for all modules
- Class docstrings describe ownership with Owns/Does NOT format
- JSDoc/TSDoc-style docstrings for public methods:
  ```python
  def execute_step_with_runner(self, adapter_name: str, manifest: AgentManifest) -> Result[ContextEnvelope]:
      """Execute a pipeline step by running the named adapter.
      
      Pipeline sequence:
        1. Look up adapter in registry.
        2. Build ContextSlice from current envelope filtered by manifest.reads.
        ...
      
      Args:
          adapter_name: Name of the adapter in the registry to invoke.
          manifest: Agent manifest defining read/write permissions.
      
      Returns:
          Success, Failure, or RollbackSuccess — same contract as execute_step.
      
      Raises:
          Nothing. All errors are returned as Failure.
      """
  ```
- Inline comments for non-obvious design decisions (e.g., skip re-signing optimization, lock ownership)
- `Note:` prefix for important implementation notes in docstrings
- Heuristic/approximation methods include docstrings with the word "approximates" or "estimates" (Rule 6.1)

## Function Design

**Size:** Not explicitly bounded — functions in this codebase range from 3-line helpers to 50+ line orchestrators. Private helper extraction is used to keep public API methods concise.

**Parameters:**
- Explicit named parameters, no `*args`/`**kwargs` except in `__exit__` (where `*_: object` is used)
- Type unions for optional parameters: `manifest: AgentManifest | None = None`
- Defaults provided where sensible (e.g., `token_budget: int = 8000`, `storage_path: str = "./relay_data/snapshots"`)

**Return Values:**
- All functions annotated — `-> None` for void functions
- `Result[T]` for fallible operations
- `T | None` for optional returns (e.g., `get_current_envelope() -> ContextEnvelope | None`)

## Module Design

**Exports:**
- Explicit `__all__` lists in every public module
- `__init__.py` re-exports public API from submodules
- `__init__.py` uses `__all__: list[str] = [...]` with type annotation

**Barrel Files:**
- `src/relay/__init__.py` re-exports all top-level public symbols
- `src/relay/budget/__init__.py` re-exports `HardCapEnforcer` and `TokenCounter` but NOT `AutoTokenCounter` (must be imported from `token_counter` directly)
- `src/relay/runners/__init__.py` — framework adapters are **lazy-imported** (importing `relay.runners` does not require langchain/crewai/autogen/httpx)

**Module Ownership Convention:**
- Every module docstring explicitly states what it Owns and Does NOT (Rule 1.1, Rule 8.3)
- A module that cannot answer both questions is too broad and should be split

## Testing Conventions (in source)

- **No network calls in unit tests** — all LLM calls, HTTP requests, external embeddings mocked (Rule 7.4)
- **Framework adapters are never imported in unit tests** — they use `FixedAgentRunner`, `FixedForkRunner`, `FixedCounter`
- **`isinstance(counter, TokenCounter)`** assertions to verify test doubles satisfy their protocol (Rule 7.6)
- **Every `Result`-returning function** tested for every distinct `Failure` code (Rule 7.5)
- **Concurrent code tested concurrently** using `threading.Thread` and `ThreadPoolExecutor` (Rule 7.3)

---

*Convention analysis: 2026-05-17*
