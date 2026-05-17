# Testing Patterns

**Analysis Date:** 2026-05-17

## Test Framework

**Runner:**
- `pytest` (via `[tool.pytest.ini_options]` in `pyproject.toml`)
- `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions are automatically detected and run with an event loop
- Config: `tests/__init__.py` is a package; test discovery uses `test_*.py` pattern

**Assertion Library:**
- Standard `pytest` assertions with plain `assert` statements
- `pytest.approx()` for floating-point comparisons (confidence scores)
- `pytest.raises()` for exception testing

**Run Commands:**
```bash
pytest tests/unit -v              # Run all unit tests (verbose)
pytest tests/integration -v       # Run all integration tests
pytest tests/unit/test_types.py -v  # Single test file
pytest -k "test_unwrap"           # Filter by test name
pytest --cov                      # Run with coverage (requires pytest-cov)
mypy --strict src/relay           # Static type check (pre-commit gate)
```

**Pre-commit gates** (`.pre-commit-config.yaml`):
1. `mypy --strict src/` — zero `# type: ignore` allowed
2. `pytest tests/unit/` — all unit tests must pass
3. `python scripts/check_test_names.py` — enforces Rule 7.1 (test names as sentences)

## Test File Organization

**Location:**
- Unit tests: `tests/unit/` — mirror `src/relay/` package structure
- Integration tests: `tests/integration/` — end-to-end tests with real wiring, no mocks
- Test doubles: `tests/conftest.py` (project-wide), `tests/unit/test_runners/conftest.py` (module-specific), `tests/unit/test_parallel/conftest.py` (module-specific)

**Directory structure:**
```
tests/
├── conftest.py                      # Shared test doubles (FixedCounter, FixedEmbeddingProvider)
├── __init__.py
├── unit/
│   ├── __init__.py
│   ├── conftest.py                  # (empty — shared fixtures in parent conftest)
│   ├── test_types.py
│   ├── test_envelope.py
│   ├── test_validator.py
│   ├── test_context_broker.py
│   ├── test_snapshot.py
│   ├── test_pipeline.py
│   ├── test_pipeline_state.py
│   ├── test_pipeline_rollback.py
│   ├── test_budget.py
│   ├── test_slicer.py
│   ├── test_runners/
│   │   ├── conftest.py              # FixedAgentRunner, make_test_slice(), make_test_manifest()
│   │   ├── test_protocol.py
│   │   ├── test_registry.py
│   │   ├── test_langchain.py
│   │   ├── test_crewai.py
│   │   ├── test_autogen.py
│   │   ├── test_local_model.py
│   │   └── test_raw_sdk.py
│   └── test_parallel/
│       ├── conftest.py              # FixedForkRunner, make_fork_spec(), make_passing_fork_result()
│       ├── test_types.py
│       ├── test_fork_runner.py
│       └── test_join.py
└── integration/
    ├── __init__.py
    ├── test_pipeline_integration.py
    ├── test_parallel_pipeline.py
    └── test_runners_integration.py
```

**Naming:**
- Test files: `test_<module_name>.py` — e.g. `test_validator.py` tests `relay.validator`
- Sub-package tests: `test_runners/test_protocol.py` tests `relay.runners.protocol`
- Test classes: `Test<Functionality>` — e.g. `TestSuccess`, `TestValidateHandoff`, `TestHardCapEnforcer`
- Test functions: `test_<sentence_description>` — e.g. `test_pipeline_creates_envelope_on_first_step`

## Test Structure

**Suite Organization:**
Every test file uses class-based organization to group related tests:
```python
class TestValidateHandoff:
    def test_validate_handoff_fails_when_pipeline_id_mismatch(self) -> None:
        ...
    def test_validate_handoff_fails_when_step_not_increasing(self) -> None:
        ...

class TestShouldRollback:
    def test_validator_should_rollback_returns_true_on_contradiction(self) -> None:
        ...
```

**Patterns:**
- **Setup:** Done via `@pytest.fixture` functions or `setup_method()`/`teardown_method()` in classes
- **Teardown:** `shutil.rmtree()` for temp directories, context managers for resources
- **Assertion pattern:** Always use `isinstance(result, Success)` / `isinstance(result, Failure)` checks before accessing `.value`:
  ```python
  result = validator.validate_handoff(previous_envelope, current_envelope)
  assert isinstance(result, Success)
  assert result.value.has_contradiction is False
  ```
- **Return type:** Every test function annotated with `-> None`

**Fixture Patterns:**
```python
# Project-wide test double fixtures in tests/conftest.py
@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""
    value: int
    def count(self, text: str) -> int: return self.value

# Module-specific fixtures in tests/unit/test_runners/conftest.py
@pytest.fixture()
def make_pipeline_components() -> tuple[AdapterRegistry, HandoffValidator]:
    registry = AdapterRegistry()
    validator = HandoffValidator()
    return registry, validator

# Temp directory fixture (used in both unit and integration tests)
@pytest.fixture
def temp_storage() -> Generator[str, None, None]:
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)
```

## Mocking

**Framework:** `unittest.mock` — `MagicMock`, `AsyncMock`, `patch`

**Patterns:**
```python
# Mocking a function return value
with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_create:
    mock_create.return_value = Success[ContextEnvelope](...)
    result = broker.create_initial_envelope(pipeline_id="pipeline-123", ...)
    mock_create.assert_called_once()

# Mocking with side effects for sequential calls
enforcer.check.side_effect = [
    Success[None](None),
    Failure(reason="Budget exceeded", code=ErrorCode.BUDGET_EXCEEDED),
]

# Mocking for async functions
mock_run = AsyncMock()
mock_run.return_value = AgentOutput(...)

# Mocking class constructors
with patch("relay.core_pipeline.SnapshotStore") as mock_store_cls:
    mock_store = MagicMock()
    mock_store.save_snapshot.return_value = Success[str]("snapshot-id")
    mock_store_cls.return_value = mock_store
```

**What to Mock:**
- External dependencies: LLM calls, HTTP requests, file I/O in unit tests
- Internal components at module boundaries: `ContextBroker.create_initial_envelope`, `HardCapEnforcer.check`, `SnapshotStore`
- Token counting (use `FixedCounter` instead of real counter)

**What NOT to Mock:**
- Domain value types (`Success`, `Failure`, `ContextEnvelope`, `ValidationResult`, `AgentOutput`) — use real constructors
- Test doubles (`FixedCounter`, `FixedAgentRunner`, `FixedForkRunner`) — these satisfy Protocols without mocking
- Pure logic functions (`is_success()`, `unwrap()`, `compute_diff()`) — test with real values

## Fixtures and Factories

**Test Data:**
```python
# Helper functions in test files
def create_mock_envelope(step: int, pipeline_id: str, payload: JSONDict, ...) -> ContextEnvelope:
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload=payload,
        manifest_hash="",
        signature=f"sig{step}",
    )

# Factory functions in conftest.py
def make_test_slice(sections=None, token_count=100, step=1) -> ContextSlice: ...
def make_test_manifest(reads=None, writes=None, max_tokens=4000) -> AgentManifest: ...
def make_fork_spec(adapter_name="test-adapter", ...) -> ForkSpec: ...
def make_passing_fork_result(fork_index=0, ...) -> ForkResult: ...
def make_failing_fork_result(fork_index=0, ...) -> ForkResult: ...
```

**Location:**
- Project-wide: `tests/conftest.py` — `FixedCounter`, `FixedEmbeddingProvider`
- Module-specific: `tests/unit/test_runners/conftest.py` — `FixedAgentRunner`, `make_test_slice()`, `make_test_manifest()`
- Module-specific: `tests/unit/test_parallel/conftest.py` — `FixedForkRunner`, `make_fork_spec()`, `make_passing_fork_result()`, `make_failing_fork_result()`
- Inline: `_make_envelope()`, `create_mock_envelope()` in individual test files

## Coverage

**Requirements:** No explicit coverage target enforced in CI.
- Configured in `pyproject.toml` under `[tool.coverage.run]`:
  ```toml
  [tool.coverage.run]
  source = ["."]
  omit = ["tests/*", "*/tests/*"]
  branch = true
  
  [tool.coverage.report]
  precision = 2
  show_missing = true
  skip_covered = false
  ```
- Coverage files: `.coverage` (binary data file in project root)

**View Coverage:**
```bash
pytest --cov
coverage report -m
```

## Pre-commit Checklist (from `docs/Relay Coding Rules.md`)

Before every commit:
- [ ] `mypy --strict` passes with zero errors
- [ ] `pytest tests/unit -v` passes
- [ ] No new `# type: ignore` comments added
- [ ] Every new public function has at least one test
- [ ] Every new `Result`-returning function has tests for each `Failure` code
- [ ] Docstrings updated if behaviour changed
- [ ] No bare `except:` or `except Exception:` added
- [ ] No new default secrets or insecure defaults added
- [ ] Commit message follows `type(scope): imperative sentence` format
- [ ] If touching shared state: concurrent test added or existing one extended

## Test Types

### Unit Tests
- **Scope:** Individual modules/classes in isolation
- **Location:** `tests/unit/`
- **Approach:** Use test doubles (`FixedCounter`, `FixedAgentRunner`, `FixedForkRunner`) or `unittest.mock` patches to isolate the unit under test
- **No network calls** (Rule 7.4)
- **Concurrent code tested concurrently** with `threading.Thread` (Rule 7.3):
  ```python
  class TestConcurrentPipeline:
      """R18: Concurrent code must be tested concurrently."""
      
      def test_concurrent_step_execution_produces_consistent_results_when_run_in_parallel(
          self, temp_storage: str
      ) -> None:
          ...
          threads = [threading.Thread(target=execute_step, args=(i,)) for i in range(3)]
          for t in threads: t.start()
          for t in threads: t.join()
          assert len(errors) == 0
  ```
- **Failure path tests mandatory alongside happy-path** (Rule 7.5):
  ```python
  class TestHardCapEnforcer:
      def test_check_passes_when_exact_boundary_reached(self) -> None:  # Happy
      def test_check_returns_failure_when_over_budget(self) -> None:     # Failure
      def test_check_passes_for_zero_token_slice_even_at_limit(self) -> None:  # Edge
      def test_check_passes_when_under_budget(self) -> None:             # Happy
  ```

### Integration Tests
- **Scope:** End-to-end behavior with real wiring
- **Location:** `tests/integration/`
- **Approach:** No mocks of Relay internals — `ContextBroker`, `HandoffValidator`, and `SnapshotStore` all wired together with `CoreRelayPipeline`
- **External calls still mocked:** Use `FixedForkRunner` instead of real LLM adapters
- **File I/O is real:** Snapshots written to and read from temp directories
- **Docstring says "No mocks — this exercises the actual pipeline"**

  Example from `tests/integration/test_pipeline_integration.py`:
  ```python
  """Integration tests for relay.pipeline end-to-end behavior.
  
  Tests the real wiring of ContextBroker, HandoffValidator, and SnapshotStore.
  No mocks — this exercises the actual pipeline.
  """
  ```

### E2E Tests
- **Not used** — no separate E2E test directory or framework

## Common Patterns

### Protocol Compliance Testing
Test doubles must satisfy their Protocol — verified with `isinstance`:
```python
def test_fixed_counter_complies_with_token_counter_protocol(self) -> None:
    counter = FixedCounter(42)
    assert isinstance(counter, TokenCounter)

def test_fixed_embedding_provider_complies_with_embedding_provider_protocol(self) -> None:
    provider = FixedEmbeddingProvider([0.1, 0.2, 0.3])
    assert isinstance(provider, EmbeddingProvider)
```

### Heuristic Ground-Truth Testing (Rule 6.2, 6.3)
Every heuristic must have a benchmark test documenting known accuracy bounds:
```python
def test_heuristic_counter_approximates_bpe_when_benchmarked(self) -> None:
    """HeuristicCounter (len//3) approximates BPE within a documented tolerance.
    This is a ground-truth benchmark per Rule 6.2."""
    ...
    assert lower <= estimate <= upper

class TestHallucinationGroundTruth:
    """R6.3: Hallucination heuristic ground-truth tests.
    
    Human-agreed ground truth:
    - FABRICATION: Agent invents 5 new entities while dropping all 4 previous ones.
    - CLEAN ADDITION: Agent adds 2 new entities while keeping all 3 previous ones.
    - ENTITY DECAY: Agent removes 2 entities with no additions.
    
    Known false-positive cases: ...
    Known false-negative cases: ...
    """
```

### Async Testing
Uses `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions run automatically:
```python
async def test_async_behavior(self) -> None:
    result = await some_async_function()
    assert isinstance(result, Success)
```

For synchronous wrappers around async code in tests:
```python
result = asyncio.run(pipeline.execute_parallel_step(
    fork_specs=[ForkSpec("agent-a", manifest_a)],
    join_strategy=JoinStrategy.UNION,
))
```

### Exception Testing
```python
def test_extract_entities_raises_on_excessive_depth(self) -> None:
    with pytest.raises(MaxDepthExceededError):
        validator._extract_entities(deeply_nested)

def test_unwrap_raises_on_failure(self) -> None:
    with pytest.raises(ValueError, match="Unwrap called on non-Success"):
        unwrap(Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR))
```

### Context Manager Testing
```python
def test_context_manager_enter_returns_pipeline(self, temp_storage: str) -> None:
    pipeline = CoreRelayPipeline(signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage)
    with pipeline as p:
        assert p is pipeline
```

### Edge Case Testing
Testing boundary conditions explicitly:
```python
def test_detect_hallucination_is_silent_when_at_threshold_boundary(self) -> None:
    """Test that exactly 2.0x ratio is not flagged (boundary case)."""
def test_check_passes_when_exact_boundary_reached(self) -> None:
    """Exact boundary (used + projected == total) must pass."""
```

## Test Naming Convention (Rule 7.1 Enforcement)

The `scripts/check_test_names.py` script enforces:
- Test names must start with `test_`
- Must have at least 4 underscore-delimited segments
- Must contain at least one "connecting word" from: `when, if, returns, raises, with, on, after, before, for, contains, creates, fails, succeeds, validates, updates, sets`

**Valid examples:**
- `test_success_contains_value` (3 words + test_ = 4 segments, "contains" is a connecting word)
- `test_pipeline_creates_envelope_on_first_step`
- `test_validate_handoff_fails_when_pipeline_id_mismatch`

**Invalid examples (would be caught):**
- `test_validator_should_rollback` (only 3 segments, no connecting word)
- `test_basic_functionality` (only 2 segments, no connecting word)

---

*Testing analysis: 2026-05-17*
