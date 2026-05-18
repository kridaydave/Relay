---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "quality"
---

# TESTING.md — Testing Practices

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## Test Framework & Configuration

| Tool | Version | Config |
|------|---------|--------|
| pytest | ≥8.0, <9 | `pyproject.toml:[tool.pytest.ini_options]` |
| pytest-asyncio | ≥0.23, <0.25 | `asyncio_mode = "auto"` |
| coverage | ≥7.0, <8 | Branch coverage, ≥80% threshold |

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

## Test Organization

```
tests/
├── conftest.py              # Shared test doubles
├── unit/                    # Unit tests (fast, isolated)
│   ├── test_*.py            # One per source module
│   ├── test_parallel/       # Parallel submodule tests
│   └── test_runners/        # Runner submodule tests
└── integration/             # Integration tests (end-to-end flows)
    ├── test_pipeline_integration.py
    ├── test_parallel_pipeline.py
    └── test_runners_integration.py
```

## Test Naming (Rule 7.1)

Test names are **full sentences** describing the behavior:

```python
def test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget():
def test_context_broker_rejects_signing_secret_shorter_than_32_characters():
def test_envelope_signature_verification_fails_when_tampered():
def test_pipeline_state_raises_on_reentrant_transaction():
```

Pattern: `test_<subject>_<expected_behavior>_<condition>`

## Test Doubles

Defined in `tests/conftest.py` and module-specific `conftest.py` files:

| Double | Module | Purpose |
|--------|--------|---------|
| `FixedCounter` | `tests/conftest.py` | TokenCounter returning fixed value |
| `FixedAuditSink` | `tests/conftest.py` | AuditSink collecting events for assertions |
| `FixedEmbeddingProvider` | `tests/conftest.py` | EmbeddingProvider returning fixed vector |
| `FixedAgentRunner` | `tests/unit/test_runners/conftest.py` | AgentRunner returning fixed output |
| `FixedForkRunner` | `tests/unit/test_runners/conftest.py` | Fork runner for parallel tests |

**No network calls in unit tests** — all external dependencies are mocked via test doubles.

## Test Coverage Requirements

- **Branch coverage** enabled (`branch = true`)
- **Minimum threshold**: 80% (`coverage report --fail-under=80`)
- **Source**: `.` (entire project)
- **Omitted**: `tests/*`, `*/tests/*`
- **Show missing**: enabled for debugging

## Failure Code Testing (Rule 7.5)

Every `Result`-returning function needs tests for **every distinct `Failure` code**. CI enforces this via `scripts/check_failure_coverage.py`.

Example pattern:
```python
def test_create_context_broker_fails_with_invalid_secret():
    result = create_context_broker(signing_secret="short")
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.INVALID_SECRET
```

## Quality Gate Scripts

| Script | Purpose | CI Step |
|--------|---------|---------|
| `scripts/check_test_names.py` | Enforces Rule 7.1 naming | Yes |
| `scripts/check_failure_coverage.py` | Ensures all ErrorCode variants tested | Yes |
| `scripts/check_layer_violations.py` | Detects layer dependency violations | Yes |
| `scripts/check_no_private_api_imports.py` | Warns on private API imports in tests | Yes (`--warn`) |

## CI Test Enforcement

1. **No `# type: ignore` in source** — hard error
2. **No `# type: ignore` in tests** — warning only
3. **No `assert` in production code** — hard error (use explicit `Failure` returns)
4. **Version consistency** — `pyproject.toml` matches `types.py`
5. **`py.typed` marker** must exist
6. **Coverage ≥80%** — hard threshold

## Test Patterns

### Testing Result Types

```python
def test_envelope_creation_returns_success():
    result = create_initial_envelope(...)
    assert isinstance(result, Success)
    assert result.value.step == 1

def test_envelope_creation_fails_with_empty_payload():
    result = create_initial_envelope(pipeline_id="test", initial_payload={}, ...)
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.INVALID_PAYLOAD
```

### Testing with Test Doubles

```python
def test_budget_enforcer_blocks_when_exceeded():
    counter = FixedCounter(value=1000)
    enforcer = HardCapEnforcer(counter)
    result = enforcer.check(budget_used=500, budget_total=1000, projected_slice="x" * 3000)
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.BUDGET_EXCEEDED
```

### Async Testing

```python
async def test_execute_step_with_runner_calls_adapter():
    # asyncio_mode = "auto" means no @pytest.mark.asyncio needed
    pipeline = await setup_pipeline_with_adapter()
    result = await pipeline.execute_step_with_runner("test", manifest)
    assert isinstance(result, Success)
```

### Integration Testing

Integration tests use real components (not test doubles) to verify end-to-end flows:
- `test_pipeline_integration.py` — full pipeline lifecycle
- `test_parallel_pipeline.py` — fork/jork parallel execution
- `test_runners_integration.py` — adapter integration
