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

**Current violation to fix:** `core_pipeline.py` owns pipeline lifecycle but also calls into snapshot management, rollback, and budget enforcement directly. Those concerns are now partially delegated to `pipeline_snapshot.py`, `pipeline_rollback.py`, and `pipeline_state.py` — finish the job. `core_pipeline.py` should read like an orchestrator: call helpers, handle their results, move on. No direct `json.dumps`, no direct file paths, no business logic.

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

**Specific fixes required:**

```python
# WRONG — current core_pipeline.py
_snapshot_ids: dict[str, str]  # accessed with int keys everywhere

# CORRECT
_snapshot_ids: dict[int, str]
```

### 2.2 Generic Result type alias is broken — fix it

```python
# WRONG — current types.py
Result: TypeAlias = Union[Success[T], RollbackSuccess[T], Failure]
# T is not bound here. mypy accepts it but it's a lie.

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

**Current violation:**
```python
# snapshot.py — currently raises
raise RuntimeError(f"Failed to update index: {e}")

# Must be:
return Failure(reason=f"Failed to update index: {e}", code="INDEX_UPDATE_FAILED")
```

### 3.2 Never use bare `except`

```python
# WRONG
try:
    ...
except Exception as e:
    raise RuntimeError(...)

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
# WRONG — swallows the failure path
result = do_thing()
if isinstance(result, Failure):
    return Success(envelope)   # pretends everything is fine

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

Currently `TiktokenCounter` has a `close()` method but `CoreRelayPipeline.close()` only calls it if the attribute exists via `hasattr`. This is fragile. Use the `Closeable` protocol:

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

`tests/unit/test_pipeline.py` uses `ThreadPoolExecutor` but the `with` block is already correct there. Ensure no future test creates an executor outside a `with` block or `try/finally`.

### 5.3 Snapshot temp files must be cleaned up on failure

The current `save_snapshot` creates a `.tmp` file and cleans it up on exception — good. Verify the cleanup runs even if `os.replace` raises (e.g. cross-device link on some systems). Wrap the replace in the try block.

---

## Section 6 — Approximations and Heuristics (R17)

### 6.1 Every heuristic must say it is one

Use the word **"approximates"** or **"estimates"** in the docstring. Without it, callers treat the output as exact.

### 6.2 Every heuristic must have a ground-truth benchmark test

The `_estimate_tokens` function claims 50% accuracy but the test only checks the formula, not the accuracy claim. A proper benchmark:

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

`_detect_hallucination` uses a 2.0× ratio threshold with no empirical basis documented. Add a test that:

1. Constructs a payload where a human would agree hallucination occurred.
2. Asserts the detector fires.
3. Constructs a payload where a human would agree no hallucination occurred.
4. Asserts the detector is silent.

Document the known false-positive and false-negative cases in the test file.

---

## Section 7 — Testing

### 7.1 Test names are sentences, not identifiers

```python
# WRONG
def test_enforcer_1():
def test_snapshot_load():

# CORRECT
def test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget():
def test_snapshot_load_returns_failure_when_file_is_missing():
```

### 7.2 Every public function has a test — no exceptions

Functions currently missing explicit tests:

- `SnapshotStore.list_snapshots` — exists but only tested as a side effect of integration tests
- `ContextEnvelope` constructor validation (the frozen invariant is tested; field constraints are not)
- `unwrap_or`, `map_result`, `map_error` — only happy-path tested
- `pipeline_state.py` public methods — no dedicated unit tests
- `pipeline_snapshot.py` and `pipeline_rollback.py` — no dedicated unit tests

### 7.3 Concurrent code must be tested concurrently (R18)

`PipelineState` mutates `_current_envelope`, `_previous_envelopes`, and `_snapshot_ids` and is accessed from multiple threads via `core_pipeline.py`. The existing concurrent tests in `test_pipeline.py` are a good start but they only assert "no exception raised." They must also assert **final state consistency**:

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

All LLM calls, HTTP requests, and external embedding calls must be mocked. Use `FixedEmbeddingProvider` and `FixedCounter` from `conftest.py`. Never let a unit test fail because of network availability.

### 7.5 Failure path tests are mandatory alongside happy-path tests

Every function that returns `Result[T]` must have at least one test for the `Success` path and at least one test for each distinct `Failure` code it can return. A function with three failure codes needs four tests minimum.

### 7.6 Test doubles must satisfy the Protocol

Use `isinstance(FixedCounter(5), TokenCounter)` as a sanity assertion in at least one test. If the protocol changes and the test double diverges, this catches it immediately.

---

## Section 8 — Commits and Documentation (R12, R14, R19)

### 8.1 Commit messages: what and why, not how

```
# WRONG
fix: updated stuff in snapshot

# CORRECT
fix(snapshot): return Failure instead of raising RuntimeError on index update

# Pattern: type(scope): imperative sentence
# Types: feat, fix, refactor, test, docs, chore, perf
```

### 8.2 Docstrings must stay accurate after every behaviour change (R19)

When a PR changes what a function does, the docstring changes in the same commit. A reviewer must explicitly check that every modified function's docstring still matches its implementation. A docstring that lies is worse than no docstring.

**Currently inaccurate docstring:**
```python
# core_pipeline.py — says "Does NOT: define agent behavior, manage prompts"
# but the class also now owns budget enforcement and slicer orchestration.
# Update it.
```

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
# WRONG — current envelope.py
def create_initial_envelope(..., secret: str = "default-secret"):

# CORRECT — make it required
def create_initial_envelope(..., secret: str):
```

A function with a default insecure secret will be used with that secret in production. Remove the default entirely. If callers need a "testing" secret, they can pass `"a" * 32` explicitly — making it visible in the test.

### 9.2 HMAC comparison must always use `hmac.compare_digest`

`verify_signature` already does this correctly. Do not introduce any direct `==` comparison of secrets or signatures anywhere in the codebase.

### 9.3 `pipeline_id` must be validated before filesystem use

See Section 4.3. A path traversal via `pipeline_id = "../../../etc"` would create directories outside the storage path. Validate before any `Path` construction.

---

## Section 10 — Architecture Decisions to Resolve

These are open questions the team must decide before v0.3 ships.

| Decision | Options | Recommendation |
|---|---|---|
| `RelayPipeline` wrapper class | Remove it (empty subclass) or add real behaviour | Remove — it adds confusion with no value |
| Layer 2 (Agent Runner) | Implement in v0.3 or update design doc | Implement per design doc — the doc says v0.3 |
| `manifest_hash` default `""` | Still present in `create_initial_envelope` | Remove the default now — it was a migration scaffold |
| Error code registry | Ad-hoc strings vs `Enum` | Enum in `types.py` — prevents typos and enables exhaustive switch |
| `_estimate_tokens` accuracy claim | "50%" in docstring but no benchmark confirms this | Add the benchmark test or lower the claim |

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
