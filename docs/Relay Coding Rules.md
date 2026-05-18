# Relay Engineering Standards
> Senior-engineer quality bar — every rule here is grounded in a real defect or pattern observed in the Relay codebase.

---

## Philosophy

Relay's value proposition is **trust**: downstream agents trust that context is clean, signed, and reversible. Every engineering decision must reinforce or at minimum not undermine that guarantee. When a rule below seems pedantic, ask: *does breaking this rule create a path where bad context silently propagates?* It usually does.

---

## Section 1 — Module Design

### 1.1 One module, one owner, one sentence description

Every module must answer three questions in its module docstring:

- What does it do?
- What does it own?
- What does it explicitly NOT do?

If you cannot answer all three, the module is doing too many things. Split it.

### 1.2 Layered imports — lower layers never import upper layers

```
types.py          ← no internal imports
envelope.py       ← imports types only
snapshot.py       ← imports envelope, types
validator.py      ← imports envelope, types, slicer.manifest (TYPE_CHECKING only)
context_broker.py ← imports envelope, types
budget/           ← imports envelope, types
slicer/           ← imports types only
pipeline_state.py ← imports envelope
pipeline_*.py     ← imports snapshot, validator, broker, state
core_pipeline.py  ← imports all pipeline_* helpers
```

Circular imports are a sign of wrong layer assignment. Fix the layer, not the import.

### 1.3 Protocols live in their own file, not next to implementations

`TokenCounter` and `EmbeddingProvider` are protocols. They define the contract that callers depend on. Implementations (`TiktokenCounter`, `RecencySlicePacker`, etc.) should import from the protocol file, not the other way. This makes swapping implementations zero-friction.

---

## Section 2 — Type Safety

### 2.1 mypy --strict must pass with zero suppressions

No `# type: ignore`. No `Any` unless the value genuinely is untyped at the boundary (e.g. raw JSON from disk). When mypy complains, fix the code.

### 2.2 Generic Result type alias must be bound correctly

```python
# CORRECT
type Result[T] = Success[T] | RollbackSuccess[T] | Failure        # Python 3.12+
# or for 3.11 compatibility:
ResultT = TypeVar("ResultT")
Result = Union[Success[ResultT], RollbackSuccess[ResultT], Failure]
```

### 2.3 Return type annotations on every method, including private ones

Private methods that lack return annotations break `--strict`. They also make refactoring harder because the reader has to trace execution to understand the shape of the return value. Annotate everything.

### 2.4 Frozen dataclasses for all value types

All domain objects that represent state — `ContextEnvelope`, `AgentManifest`, `ValidationResult`, `BudgetExceeded`, etc. — must be `@dataclass(frozen=True)`. If you need a modified copy, use `dataclasses.replace()` or a dedicated `with_*` method. Never add mutable fields to these types.

---

## Section 3 — Error Handling

### 3.1 Result types are the contract — raise only for programmer errors

The `Result[T]` pattern means callers never need a try/except for expected failure modes. This is the entire point. Violations destroy that guarantee.

**Rule:** Raise `ValueError` or `AssertionError` for programmer errors (wrong types passed, invariants violated at construction time). Return `Failure` for operational errors (missing file, budget exceeded, validation failed, corrupted JSON).

### 3.2 Never use bare `except`

```python
# CORRECT — catch the specific exception you expect
try:
    with open(path) as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    return Failure(reason=f"Corrupted JSON: {e}", code="CORRUPTED_SNAPSHOT")
except OSError as e:
    return Failure(reason=f"Cannot read file: {e}", code="SNAPSHOT_READ_FAILED")
```

### 3.3 Error codes are a public API — treat them as such

`Failure.code` is what callers switch on. Once a code is shipped, changing it is a breaking change. Use SCREAMING_SNAKE_CASE. Keep a registry in `types.py` as a module-level constant or `Enum`. Do not invent new codes for the same condition.

### 3.4 Propagate Failure immediately — no silent discard

```python
# CORRECT
result = do_thing()
if isinstance(result, Failure):
    return result              # bubble it
```

---

## Section 4 — Validation

### 4.1 Validate at the boundary, trust internally (R16)

Every value from outside the process — agent output, config, restored JSON from disk — must be validated the moment it enters. Internal functions that receive already-validated values must not re-validate. Duplicate validation is noise and causes them to fall out of sync.

**Boundary definitions for Relay:**

| Entry point | Validation responsibility |
|---|---|
| `ContextBroker.__post_init__` | `signing_secret` length |
| `create_initial_envelope` | `pipeline_id` non-empty, `payload` non-empty |
| `SnapshotStore._dict_to_envelope` | every field: presence + type |
| `HardCapEnforcer.check` | negative token count |
| `validate_manifest_boundaries` | section names against manifest |

### 4.2 `_dict_to_envelope` must return `Result`, never raise

Snapshot files can be corrupted or manually edited. A `KeyError` here surfaces as an unhandled exception in the caller. Every field extraction must use the `_require_field` helper that already exists — use it consistently for all fields including `manifest_hash`.

### 4.3 Sanitise string inputs that become identifiers or file paths

`pipeline_id` becomes a directory name. If an attacker controls it, they control the path. Validate that `pipeline_id` matches `[a-zA-Z0-9_-]+` at the boundary before it ever touches the filesystem.

```python
import re
_SAFE_ID = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')

def _validate_pipeline_id(pipeline_id: str) -> Result[str]:
    if not _SAFE_ID.match(pipeline_id):
        return Failure(reason="pipeline_id contains unsafe characters", code="INVALID_PIPELINE_ID")
    return Success(pipeline_id)
```

---

## Section 5 — Resource Lifecycle (R15)

### 5.1 Every resource has an explicit owner and cleanup path

Use the `Closeable` protocol:

```python
from typing import Protocol

class Closeable(Protocol):
    def close(self) -> None: ...
```

`CoreRelayPipeline` should implement `__enter__` / `__exit__` so it can be used as a context manager, which makes the cleanup path explicit and enforced by the language:

```python
with CoreRelayPipeline(signing_secret=..., token_budget=8000) as pipeline:
    pipeline.execute_step(...)
# close() called automatically
```

### 5.2 `ThreadPoolExecutor` in tests must be shut down

Ensure no future test creates an executor outside a `with` block or `try/finally`.

### 5.3 Snapshot temp files must be cleaned up on failure

The `save_snapshot` method creates a `.tmp` file and cleans it up on exception. Verify the cleanup runs even if `os.replace` raises (e.g. cross-device link on some systems). Wrap the replace in the try block.

---

## Section 6 — Approximations and Heuristics (R17)

### 6.1 Every heuristic must say it is one

Use the word **"approximates"** or **"estimates"** in the docstring. Without it, callers treat the output as exact.

### 6.2 Every heuristic must have a ground-truth benchmark test

A proper benchmark:

```python
def test_token_estimate_accuracy_against_reference():
    """Benchmark _estimate_tokens against known character-to-token ratios.

    Ground truth: typical English prose tokenizes at ~0.75 tokens/char (GPT-4).
    Our heuristic: len(json) // 3 ≈ 0.33 tokens/char.
    Acceptable error: within 2x of a real tokenizer on representative payloads.
    """
    payload = {"summary": "Apple reported record revenue for fiscal Q4 2024.",
               "entities": ["Apple", "Q4", "2024"], "step": 3}
    estimate = _estimate_tokens(payload)
    json_chars = len(json.dumps(payload, sort_keys=True))
    # Real BPE for this payload is roughly json_chars * 0.30 to 0.40
    lower = int(json_chars * 0.20)
    upper = int(json_chars * 0.55)
    assert lower <= estimate <= upper, (
        f"Estimate {estimate} outside acceptable range [{lower}, {upper}] "
        f"for {json_chars} chars"
    )
```

### 6.3 The hallucination heuristic needs a ground-truth test

`_detect_hallucination` uses a 2.0× ratio threshold.

1. Constructs a payload where a human would agree hallucination occurred.
2. Asserts the detector fires.
3. Constructs a payload where a human would agree no hallucination occurred.
4. Asserts the detector is silent.

Document the known false-positive and false-negative cases in the test file.

---

## Section 7 — Testing Practices

### 7.1 Test names are sentences, not identifiers (Rule 7.1)

Test names are **full sentences** describing the behavior:

```python
# CORRECT
def test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget():
def test_context_broker_rejects_signing_secret_shorter_than_32_characters():
def test_envelope_signature_verification_fails_when_tampered():
def test_pipeline_state_raises_on_reentrant_transaction():
```

Pattern: `test_<subject>_<expected_behavior>_<condition>`

### 7.2 Every public function has a test — no exceptions

Make sure every function is tested, including error and failure paths.

### 7.3 Concurrent code must be tested concurrently (R18)

Any component that mutates state and is accessed from multiple threads must be tested concurrently. Assert **final state consistency**:

```python
def test_concurrent_steps_final_envelope_is_consistent():
    """Final envelope step must equal exactly one of the submitted steps."""
    pipeline = ...
    results = run_n_threads(pipeline.execute_step, payloads=[...] * 5)
    final = pipeline.get_current_envelope()
    valid_steps = {1, 2, 3, 4, 5}
    assert final.step in valid_steps
    # No corrupted blend of two steps
    assert final.payload in [p for p in payloads]
```

### 7.4 No network calls in unit tests (R7)

All LLM calls, HTTP requests, and external embedding calls must be mocked. All external dependencies are mocked via test doubles defined in `tests/conftest.py` and module-specific `conftest.py` files. Never let a unit test fail because of network availability.

### 7.5 Failure path tests are mandatory alongside happy-path tests (Rule 7.5)

Every function that returns `Result[T]` must have at least one test for the `Success` path and at least one test for each distinct `Failure` code it can return. A function with three failure codes needs four tests minimum. CI enforces this via `scripts/check_failure_coverage.py`.

Example pattern:
```python
def test_create_context_broker_fails_with_invalid_secret():
    result = create_context_broker(signing_secret="short")
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.INVALID_SECRET
```

### 7.6 Test doubles must satisfy the Protocol

Use `isinstance(FixedCounter(5), TokenCounter)` as a sanity assertion in at least one test. If the protocol changes and the test double diverges, this catches it immediately.

### 7.7 Test Framework & Organization

| Tool | Version | Config |
|------|---------|--------|
| pytest | ≥8.0, <9 | `pyproject.toml:[tool.pytest.ini_options]` |
| pytest-asyncio | ≥0.23, <0.25 | `asyncio_mode = "auto"` |
| coverage | ≥7.0, <8 | Branch coverage, ≥80% threshold |

**Directory Structure:**
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

### 7.8 Test Coverage & CI Enforcement

- **Branch coverage** enabled (`branch = true`)
- **Minimum threshold**: 80% (`coverage report --fail-under=80`)
- **No `# type: ignore` in source** — hard error
- **No `assert` in production code** — hard error (use explicit `Failure` returns)
- **`py.typed` marker** must exist

### 7.9 Quality Gate Scripts

| Script | Purpose | CI Step |
|--------|---------|---------|
| `scripts/check_test_names.py` | Enforces Rule 7.1 naming | Yes |
| `scripts/check_failure_coverage.py` | Ensures all ErrorCode variants tested | Yes |
| `scripts/check_layer_violations.py` | Detects layer dependency violations | Yes |
| `scripts/check_no_private_api_imports.py` | Warns on private API imports in tests | Yes (`--warn`) |

### 7.10 Test Patterns

**Testing Result Types:**
```python
def test_envelope_creation_returns_success():
    result = create_initial_envelope(...)
    assert isinstance(result, Success)
    assert result.value.step == 1
```

**Testing with Test Doubles:**
```python
def test_budget_enforcer_blocks_when_exceeded():
    counter = FixedCounter(value=1000)
    enforcer = HardCapEnforcer(counter)
    result = enforcer.check(budget_used=500, budget_total=1000, projected_slice="x" * 3000)
    assert isinstance(result, Failure)
    assert result.code == ErrorCode.BUDGET_EXCEEDED
```

**Async Testing:**
```python
async def test_execute_step_with_runner_calls_adapter():
    # asyncio_mode = "auto" means no @pytest.mark.asyncio needed
    pipeline = await setup_pipeline_with_adapter()
    result = await pipeline.execute_step_with_runner("test", manifest)
    assert isinstance(result, Success)
```

---

## Section 8 — Commits and Documentation (R12, R14, R19)

### 8.1 Commit messages: what and why, not how

```
# CORRECT
fix(snapshot): return Failure instead of raising RuntimeError on index update

# Pattern: type(scope): imperative sentence
# Types: feat, fix, refactor, test, docs, chore, perf
```

### 8.2 Docstrings must stay accurate after every behaviour change (R19)

When a PR changes what a function does, the docstring changes in the same commit. A reviewer must explicitly check that every modified function's docstring still matches its implementation. A docstring that lies is worse than no docstring.

### 8.3 Module docstrings use the three-line format

```python
"""What this module does in one sentence.

Owns: specific things this module is responsible for.
Does NOT: things a reader might expect but this module deliberately avoids.
"""
```

Every module. No exceptions.

---

## Section 9 — Security

### 9.1 The default signing secret must be removed

```python
# CORRECT — make it required
def create_initial_envelope(..., secret: str):
```

A function with a default insecure secret will be used with that secret in production. Remove the default entirely. If callers need a "testing" secret, they can pass `"a" * 32` explicitly — making it visible in the test.

### 9.2 HMAC comparison must always use `hmac.compare_digest`

`verify_signature` already does this correctly. Do not introduce any direct `==` comparison of secrets or signatures anywhere in the codebase.

### 9.3 `pipeline_id` must be validated before filesystem use

See Section 4.3. A path traversal via `pipeline_id = "../../../etc"` would create directories outside the storage path. Validate before any `Path` construction.

---

## Section 10 — Architecture Decisions (Resolved)

All decisions from the v0.3 era have been resolved.

| Decision | Resolution |
|---|---|
| `RelayPipeline` wrapper class | ✅ **Resolved** — class deleted from source |
| Layer 2 (Agent Runner) | ✅ **Resolved** — implemented as `AdapterRegistry`/`AgentRunner` in v0.3 |
| `manifest_hash` default `""` | ✅ **Resolved** — defaults removed from `ContextBroker` and envelope factories |
| Error code registry | ✅ **Resolved** — `ErrorCode` Enum defined in `types.py` |
| `_estimate_tokens` accuracy claim | ✅ **Resolved** — claim softened to "not benchmarked, heuristic only" |

---

## Section 11 — Technology Stack

### 11.1 Languages & Runtime

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | ≥3.12 (tested on 3.12, 3.13) |
| Type hints | PEP 695 `type` syntax | Python 3.12+ (`type Result[T] = ...`) |
| Package manager | pip / setuptools | setuptools ≥61.0 |

### 11.2 Core Dependencies (Zero Runtime Deps)

The core package has **zero required runtime dependencies**. All external libraries are optional extras. This is a deliberate design choice: Relay is a middleware library that doesn't force any specific LLM framework on consumers.

### 11.3 Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `dev` | `pytest`, `pytest-asyncio`, `anyio`, `mypy`, `coverage` | Development tooling |
| `tiktoken` | `tiktoken` | Accurate BPE token counting (cl100k_base) |
| `langchain` | `langchain-core` | LangChain adapter |
| `crewai` | `crewai` | CrewAI adapter |
| `autogen` | `pyautogen` | AutoGen adapter |
| `local` | `httpx` | Local model runner (HTTP-based) |

### 11.4 Type Checking

- **Strictness:** `mypy --strict` with **zero `# type: ignore` suppressions** (enforced in CI)
- **Coverage:** Both `src/` and `tests/` are type-checked
- **Marker:** `src/relay/py.typed` present for PEP 561 compatibility

### 11.5 Python Standard Library Usage

Heavy use of stdlib modules: `dataclasses`, `typing` (Protocol, Generic), `enum`, `hmac`, `hashlib`, `json`, `uuid`, `datetime`, `threading` (Lock), `asyncio`, `pathlib`, `logging`.

---

## Section 12 — Known Constraints & Concerns

### 12.1 Budget Enforcement is Advisory Under Concurrent Load

The budget check is advisory under concurrent load. The lock is released before adapter execution to avoid holding it during I/O, so another thread may advance the envelope between the check and execution. The `RollbackSuccess` safety net handles post-hoc detection.

### 12.2 Heuristic Token Counting

Default token counting uses `len(json_str) // 3` as a coarse approximation (0.33 tokens/char). While suitable for budget estimation, it is NOT precise. For accurate BPE counting, the `tiktoken` optional dependency should be used.

### 12.3 Non-Reentrant Lock

`PipelineState` uses a non-reentrant `threading.Lock`. Nested `transaction()` calls will cause a `RuntimeError` (hard crash). This is a deliberate design choice to prevent subtle reentrancy bugs.

### 12.4 Snapshot I/O Performance

Every pipeline step writes a JSON file to disk (max 100 MB). Currently, there is no batching or async I/O for snapshot writes. While `InMemorySnapshotStore` is available for testing, production relies on synchronous filesystem I/O.

### 12.5 Entity Extraction Heuristics

`HandoffValidator` uses heuristic key-based entity detection which may have false positives/negatives. It traverses JSON iteratively with a depth limit (50) and entity limit (10,000).

---

## Quick Pre-commit Checklist

Before every commit, verify:

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
