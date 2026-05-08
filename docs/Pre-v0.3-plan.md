# Relay — Fix Implementation Plan

> Derived from the code review: 7 bugs, 5 dead code items, 6 complexity issues, 8 design violations.
> Each entry is one atomic commit. Do them in order — later commits depend on earlier ones.
> Run `mypy --strict src/` and `pytest tests/ -v` after every commit before moving on.

---

## Severity legend

| Symbol | Meaning |
|--------|---------|
| 🔴 | Runtime crash or security hole. Fix before anything else. |
| 🟠 | Incorrect behaviour or broken contract. Fix before v0.3. |
| 🟡 | Quality / maintainability. Fix before cutting the v0.3 branch. |
| 🟢 | Polish. Fine to do alongside v0.3 work. |

---

## Schedule overview

| Week | Theme | Commits |
|------|-------|---------|
| 1 | Stop the bleeding — runtime crashes and broken type system | C-01 → C-04 |
| 2 | Ownership and contracts — dead code, shared state, lock model | C-05 → C-08 |
| 3 | Design rule compliance — docstrings, validation boundary, tests | C-09 → C-12 |
| 4 | Polish — complexity reduction, slicer correctness | C-13 → C-14 |

---

## Week 1 — Runtime crashes and broken type system

---

### C-01 — Fix import order causing `NameError` in `envelope.py` 🔴

**Fixes:** B-02

**Root cause.**
`_validate_pipeline_id` is defined near the top of `envelope.py` and references `Result`, `Failure`, `Success`, and `ErrorCode` — but those names are imported from `relay.types` in a block that appears *after* the function definition. Python executes module bodies top-to-bottom; calling `_validate_pipeline_id` raises `NameError: name 'Result' is not defined` at runtime.

**Current (broken):**
```python
# envelope.py — top of file
PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

def _validate_pipeline_id(pipeline_id: str) -> Result[str]:   # NameError: Result
    if not pipeline_id:
        return Failure(reason="...", code=ErrorCode.INVALID_PIPELINE_ID)
    ...

from relay.types import ErrorCode, Failure, Result, Success   # too late
```

**Fix — move all imports above every function definition:**
```python
# envelope.py — correct order
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from relay.types import ErrorCode, Failure, Result, Success   # FIRST

RELAY_VERSION = "0.2.0"
PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

def _validate_pipeline_id(pipeline_id: str) -> Result[str]:  # now safe
    ...
```

**Test to add** in `tests/unit/test_envelope.py`:
```python
def test_envelope_module_imports_without_error():
    """Import must not raise NameError regardless of call order."""
    import importlib
    import relay.envelope
    importlib.reload(relay.envelope)
```

**Commit message:** `fix(envelope): move relay.types imports above function definitions to prevent NameError`

---

### C-02 — Fix broken `Result` TypeAlias — T is unbound 🔴

**Fixes:** B-01

**Root cause.**
```python
T = TypeVar("T")
Result: TypeAlias = Union[Success[T], RollbackSuccess[T], Failure]
```
`T` is a module-level `TypeVar` but is not bound at the alias definition site. mypy accepts the syntax but `Result[str]` does not actually constrain `Success` or `RollbackSuccess` to hold `str`. The alias provides false type safety throughout the entire codebase.

**Decision to make before implementing:** check your Python version floor.

If targeting **Python 3.12+** (cleanest — update `requires-python` in `pyproject.toml`):
```python
type Result[T] = Success[T] | RollbackSuccess[T] | Failure
```

If staying on **Python 3.11**:
```python
from typing import TypeVar, Union, TypeAlias

_T = TypeVar("_T")
Result: TypeAlias = Union[Success[_T], RollbackSuccess[_T], Failure]
```

Either way, rename the module-level `T` to `_T` to mark it as internal and avoid shadowing at call sites.

**Verify:** `mypy --strict src/relay/types.py` must pass with zero errors.

**Commit message:** `fix(types): correct unbound TypeVar in Result generic alias`

---

### C-03 — Add secret strength validation inside `_sign_envelope` 🔴

**Fixes:** B-03

**Root cause.**
`ContextBroker.__post_init__` validates `signing_secret >= 32 chars`, but `create_initial_envelope` and `create_next_envelope` in `envelope.py` accept any `secret: str` with no validation. Any caller that bypasses `ContextBroker` and calls `envelope.py` directly (including all existing test helpers that pass `"secret"` or `"test-secret"`) gets no protection.

**Fix — add the check inside `_sign_envelope`**, the single choke-point all signing passes through:
```python
_MIN_SECRET_LENGTH = 32

def _sign_envelope(envelope: ContextEnvelope, secret: str) -> ContextEnvelope:
    """Create a signed copy of the envelope.

    Raises:
        ValueError: If secret is shorter than _MIN_SECRET_LENGTH characters.
            Weak secrets are a programmer error, not an operational failure.
    """
    if len(secret) < _MIN_SECRET_LENGTH:
        raise ValueError(
            f"signing_secret must be at least {_MIN_SECRET_LENGTH} characters, "
            f"got {len(secret)}. Weak secrets compromise envelope integrity."
        )
    signature = _compute_signature(envelope, secret)
    return envelope.with_signature(signature)
```

`ValueError` is correct here per coding rule R3.1 — a weak secret is a programmer error.
`ContextBroker.__post_init__` keeps its own check as an earlier, friendlier gate.

All existing tests that pass a short secret (e.g. `"secret"`, `"test-secret"`) must be updated to use `"a" * 32` or a shared fixture.

**Tests to add** in `tests/unit/test_envelope.py`:
```python
def test_create_initial_envelope_raises_on_weak_secret():
    with pytest.raises(ValueError, match="32 characters"):
        create_initial_envelope(
            pipeline_id="pipe-1",
            initial_payload={"x": 1},
            secret="short",
            manifest_hash="",
        )

def test_create_next_envelope_raises_on_weak_secret():
    first = create_initial_envelope(
        pipeline_id="pipe-1", initial_payload={"x": 1},
        secret="a" * 32, manifest_hash=""
    ).value
    with pytest.raises(ValueError, match="32 characters"):
        create_next_envelope(
            previous_envelope=first,
            secret="weak",
            agent_output={"y": 2},
            manifest_hash="",
        )
```

**Commit message:** `fix(envelope): validate secret strength in _sign_envelope to prevent bypass via direct calls`

---

### C-04 — Replace `Any`-typed `_require_field` with typed helpers 🔴

**Fixes:** B-04

**Root cause.**
`_require_field` returns `Any`. mypy cannot detect a caller that skips the `isinstance(result, Failure)` guard and passes a `Failure` object downstream as valid data — a silent type corruption.

**Fix — replace with three typed helpers:**
```python
# snapshot.py

def _require_str(self, data: dict[str, Any], key: str) -> "Result[str]":
    value = data.get(key)
    if value is None or not isinstance(value, str):
        return Failure(reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT)
    return Success(value)

def _require_int(self, data: dict[str, Any], key: str) -> "Result[int]":
    value = data.get(key)
    if value is None or not isinstance(value, int):
        return Failure(reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT)
    return Success(value)

def _require_dict(self, data: dict[str, Any], key: str) -> "Result[dict[str, Any]]":
    value = data.get(key)
    if value is None or not isinstance(value, dict):
        return Failure(reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT)
    return Success(value)
```

Update `_dict_to_envelope` to use these. Delete `_require_field`. mypy can now verify every call site.

**Commit message:** `fix(snapshot): replace Any-typed _require_field with typed helpers for mypy correctness`

---

## Week 2 — Ownership and contracts

---

### C-05 — Remove dead code: `rollback_to_last`, `last_envelope`, `RelayPipeline`, unused imports 🟠

**Fixes:** D-01, D-02, D-03, D-05, V-07

Four dead-code items small enough to clean up together.

**1. Delete `src/relay/pipeline.py`** — the empty `RelayPipeline` subclass adds a second import path with no behaviour. If you want a public alias, add one line to `src/relay/__init__.py`:
```python
from relay.core_pipeline import CoreRelayPipeline as RelayPipeline
```

**2. Delete `PipelineState.rollback_to_last()`** — no production code calls it. `core_pipeline.py` uses `peek_last()` + `consume_last()` directly. Remove the method and delete `TestRollbackToLast` from `test_pipeline_state.py`.

**3. Delete `PipelineState.last_envelope()`** — identical implementation to `peek_last()`, zero production callers. Remove the method. Rename `TestLastEnvelope` to `TestPeekLast` and keep the assertions unchanged.

**4. Remove the two unused inline imports inside `validate_manifest_boundaries`** in `validator.py`:
```python
# Delete both of these lines from inside the function body:
from relay.slicer.manifest import AgentManifest    # already imported via TYPE_CHECKING
from relay.types import HandoffValidationFailure   # never used anywhere
```

**Commit message:** `refactor: remove dead code — RelayPipeline subclass, rollback_to_last, last_envelope, unused inline imports`

---

### C-06 — Remove unused value types `HandoffValidationFailure` and `ManifestHashMismatch` 🟡

**Fixes:** D-04

**Before acting:** run `grep -r "HandoffValidationFailure\|ManifestHashMismatch" src/` to confirm zero production usage. If confirmed unused:

- Delete both dataclasses from `types.py`
- Remove from any `__all__` export list if present
- Delete any tests that exist solely to test these types

If you intend to use them in v0.3, add a comment and keep them:
```python
# TODO(v0.3): used by relay.runners adapter layer for structured error values
@dataclass(frozen=True)
class HandoffValidationFailure:
    ...
```
But they must be used within that milestone or deleted again at v0.3 time.

**Commit message:** `refactor(types): remove unused HandoffValidationFailure and ManifestHashMismatch dataclasses`

---

### C-07 — Make `SnapshotManager` stateless — remove shared dict reference 🟠

**Fixes:** V-08, C-04 (complexity)

**Root cause.**
`CoreRelayPipeline.__post_init__` passes `self._state.snapshot_ids` (a live `dict` reference) into `SnapshotManager.__init__`. Both objects now hold the same dict. Mutations from either are immediately visible in the other — shared mutable state between two objects, violating R2. Ownership is invisible without tracing object identity.

**Fix — make `SnapshotManager` stateless. It saves snapshots and returns IDs; the caller registers them:**
```python
# pipeline_snapshot.py
class SnapshotManager:
    """Manages snapshot persistence for the pipeline.

    Owns: snapshot save/load logic.
    Does NOT: own snapshot_id state — callers update their own registries.
    """

    def __init__(self, snapshot_store: SnapshotStore) -> None:
        self._snapshot_store = snapshot_store

    def save(self, envelope: ContextEnvelope) -> Result[str]:
        """Save snapshot. Returns the snapshot ID. Caller registers it."""
        return self._snapshot_store.save_snapshot(envelope)

    def load(self, snapshot_id: str) -> Result[ContextEnvelope]:
        return self._snapshot_store.load_snapshot(snapshot_id)
```

**Update `core_pipeline.py` to own all `snapshot_ids` mutations explicitly:**
```python
# __post_init__ — no dict passed in
self._snapshot_manager = SnapshotManager(self._snapshot_store)

# _finalize_step — explicit registration
save_result = self._snapshot_manager.save(current_envelope)
if isinstance(save_result, Failure):
    return save_result
self._state.snapshot_ids[current_envelope.step] = save_result.value

# _advance_to_new_envelope — explicit registration + explicit cleanup
save_result = self._snapshot_manager.save(new_envelope)
if isinstance(save_result, Failure):
    return save_result
self._state.snapshot_ids[new_envelope.step] = save_result.value
if oldest_in_history is not None:
    self._state.snapshot_ids.pop(oldest_in_history.step, None)
```

**Update `test_pipeline_snapshot.py`** — remove the `snapshot_ids` fixture parameter from `SnapshotManager` construction. Tests for ID registration move to `test_pipeline.py` where state ownership actually lives.

**Commit message:** `refactor(snapshot): make SnapshotManager stateless — callers own snapshot_id registration`

---

### C-08 — Document non-reentrant lock contract and add debug assertions 🟠

**Fixes:** C-01 (complexity), B-07

**Root cause.**
`PipelineState.transaction()` acquires a non-reentrant `threading.Lock`. `execute_step_with_manifest` holds that lock for the entire step duration. All helpers it calls (`_handle_initial_step`, `_finalize_step`, etc.) call `self._state.*` mutation methods directly — correct because the outer call already holds the lock, but this contract is completely invisible. If any helper ever calls `transaction()` again, it deadlocks silently with no error message.

**Fix — three parts:**

**Part 1: Pass the captured envelope into helpers** instead of re-reading state mid-step. This resolves B-07 (stale yield) and removes any reason for helpers to call `transaction()` themselves:
```python
def execute_step_with_manifest(self, agent_output, manifest=None):
    with self._state.transaction() as current_envelope:
        if current_envelope is None:
            return self._handle_initial_step(agent_output, manifest)
        # Pass the captured value — helpers must not re-read from state
        return self._handle_subsequent_step(agent_output, manifest, current_envelope)
```

**Part 2: Add a debug assertion to every state mutation method:**
```python
# pipeline_state.py
def _assert_lock_held(self) -> None:
    """Assert _lock is held by the calling thread. Active only when __debug__ is True.

    Call at the top of every method that requires the lock.
    Disappears under python -O. Cost-free in tests.
    """
    if __debug__:
        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self._lock.release()
            raise AssertionError(
                f"{self.__class__.__name__} mutation called without holding _lock. "
                "Wrap the call site in `with self._state.transaction()`."
            )

def set_current(self, envelope: ContextEnvelope) -> None:
    self._assert_lock_held()
    self._current_envelope = envelope

def archive_and_set(self, new_envelope: ContextEnvelope) -> None:
    self._assert_lock_held()
    ...

def peek_last(self) -> ContextEnvelope | None:
    self._assert_lock_held()
    ...

def consume_last(self) -> ContextEnvelope:
    self._assert_lock_held()
    ...
```

**Part 3: Add docstring contracts to every helper in `core_pipeline.py`:**
```python
def _handle_subsequent_step(self, agent_output, manifest, current_envelope):
    """Handle a subsequent pipeline step.

    REQUIRES: caller holds self._state._lock via transaction() context manager.
    Must NOT call self._state.transaction() — lock is non-reentrant.
    """
```

**Commit message:** `fix(pipeline): document non-reentrant lock contract, add debug assertions, pass captured envelope to helpers`

---

## Week 3 — Design rule compliance

---

### C-09 — Remove duplicate `PIPELINE_ID_PATTERN` — validate at the boundary only 🟡

**Fixes:** V-03, R16

**Current state:** `PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")` exists independently in both `envelope.py` and `snapshot.py`. `SnapshotStore.save_snapshot` re-validates a `pipeline_id` that was already validated when the `ContextEnvelope` was constructed. Per R16, validate once at the entry boundary and trust internally.

**Fix:** keep the pattern and `_validate_pipeline_id` in `envelope.py` only. In `snapshot.py`, delete the duplicate constant and remove the validation block from `save_snapshot`:
```python
def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
    """Save an envelope as a snapshot.

    Trusts that envelope.pipeline_id is valid — validated at construction
    time by create_initial_envelope via _validate_pipeline_id.
    """
    # No pipeline_id re-validation here.
    pipeline_path = self._storage_path / envelope.pipeline_id
    ...
```

**Commit message:** `refactor(snapshot): remove duplicate pipeline_id validation — trust envelope boundary per R16`

---

### C-10 — Fix module docstrings to match actual behaviour 🟡

**Fixes:** V-01, V-06, V-04, R19, R14

Three module docstrings lie about what the module owns or does.

**`envelope.py`** claims "Does NOT: create envelopes" but contains `create_initial_envelope`, `create_next_envelope`, and `_sign_envelope`:
```python
"""Context envelope data model and factory functions for Relay.

Owns: ContextEnvelope data model, envelope construction, HMAC signing.
Does NOT: persist envelopes, manage pipeline state, or validate agent output.

Note: signing lives here rather than in context_broker because the signature
covers fields that only envelope.py knows how to serialise canonically.
context_broker.py decides *when* to create envelopes; envelope.py owns *how*.
"""
```

**`context_broker.py`** claims to own "cryptographic signing" but delegates entirely to `envelope.py`:
```python
"""Context envelope lifecycle management for Relay.

Owns: deciding when to create envelopes, enforcing secret strength,
      coordinating construction via relay.envelope.
Does NOT: implement signing (owned by relay.envelope), persist envelopes,
          validate agent output, or manage pipeline state.
"""
```

**`slicer/packers.py`** has no module docstring at all:
```python
"""Slice packer implementations for context selection strategies.

Owns: RecencySlicePacker, StructuralSlicePacker, RelevanceSlicePacker.
Does NOT: define SliceStrategy enum, own EmbeddingProvider protocol,
          or count tokens precisely (delegates to envelope._estimate_tokens).
"""
```

**Commit message:** `docs: fix module docstrings in envelope.py, context_broker.py, slicer/packers.py per R19/R14`

---

### C-11 — Replace tautological token estimation test with a real benchmark 🟡

**Fixes:** V-05, R17

**Current test — a tautology that always passes regardless of correctness:**
```python
def test_token_estimate_within_realistic_tolerance(self):
    payload = {"key": "value" * 50}
    estimate = _estimate_tokens(payload)
    json_str = json.dumps(payload, sort_keys=True)
    assert estimate == len(json_str) // 3   # just re-runs the formula
```

This would pass even if `_estimate_tokens` returned 0.

**Fix — replace with a ground-truth benchmark:**
```python
class TestTokenEstimationAccuracy:
    """Ground-truth benchmark for _estimate_tokens per R17.

    Ground truth: English prose and JSON tokenise at roughly 0.25–0.40
    tokens/char under BPE tokenisers (GPT-4 family, cl100k_base).
    Our formula: len(json) // 3 ≈ 0.33 tokens/char — within that range.

    The 3x tolerance is intentionally wide because the heuristic is coarse.
    For precise counting, use TiktokenCounter. These tests catch a completely
    broken implementation (returning 0, returning len, etc.).
    """

    PAYLOADS = [
        {"summary": "Apple reported strong Q4 revenue growth.", "step": 1},
        {"entities": ["Alice", "Bob", "Charlie"], "facts": ["revenue up", "costs flat"]},
        {"data": "x" * 200},
        {"nested": {"a": {"b": {"c": "deep"}}}},
    ]

    def test_estimate_is_positive_for_all_representative_payloads(self):
        for payload in self.PAYLOADS:
            assert _estimate_tokens(payload) > 0, f"Zero estimate for {payload}"

    def test_estimate_stays_within_3x_of_char_based_reference(self):
        for payload in self.PAYLOADS:
            estimate = _estimate_tokens(payload)
            json_len = len(json.dumps(payload, sort_keys=True))
            baseline = max(1, json_len // 4)
            assert estimate >= baseline // 3, (
                f"Estimate {estimate} too low vs baseline {baseline} for {payload}"
            )
            assert estimate <= baseline * 3, (
                f"Estimate {estimate} too high vs baseline {baseline} for {payload}"
            )

    def test_larger_payload_produces_larger_estimate(self):
        small = {"x": "a" * 10}
        large = {"x": "a" * 1000}
        assert _estimate_tokens(large) > _estimate_tokens(small)
```

Also update the `_estimate_tokens` docstring: replace "~50% accuracy" with "within 3x of a 4-chars/token BPE baseline; see TestTokenEstimationAccuracy for the benchmark".

**Commit message:** `test(envelope): replace tautological token estimate test with ground-truth benchmark per R17`

---

### C-12 — Cross-check envelope body step against snapshot filename 🟠

**Fixes:** B-06

**Root cause.**
`load_snapshot` extracts `step = int(parts[0])` from the snapshot ID to validate the format, but then never uses `step` again. It loads the envelope from disk without checking that `envelope.step` matches the step encoded in the filename. A tampered snapshot file with a modified `step` field in the body passes silently.

**Fix — cross-check after loading:**
```python
try:
    expected_step = int(parts[0])
except ValueError:
    return Failure(
        reason="Invalid step in snapshot ID", code=ErrorCode.INVALID_SNAPSHOT_ID
    )

snapshot_path = self._storage_path / pipeline_id / f"{snapshot_id}.json"
try:
    with open(snapshot_path, "r") as f:
        data = json.load(f)
    envelope_result = self._dict_to_envelope(data)
    if isinstance(envelope_result, Failure):
        return envelope_result
    envelope = envelope_result.value

    if envelope.step != expected_step:
        return Failure(
            reason=(
                f"Snapshot integrity error: filename indicates step {expected_step} "
                f"but envelope body contains step {envelope.step}"
            ),
            code=ErrorCode.INVALID_SNAPSHOT,
        )

    return Success(envelope)
```

**Test to add** in `tests/unit/test_snapshot.py`:
```python
def test_load_snapshot_fails_when_body_step_mismatches_filename(self):
    """Tampered snapshot where body step differs from filename is rejected."""
    env = self._create_envelope(step=1)
    snapshot_id = self.store.save_snapshot(env).value

    path = Path(self.temp_dir) / env.pipeline_id / f"{snapshot_id}.json"
    data = json.loads(path.read_text())
    data["step"] = 99
    path.write_text(json.dumps(data))

    result = self.store.load_snapshot(snapshot_id)
    assert isinstance(result, Failure)
    assert result.code == "INVALID_SNAPSHOT"
```

**Commit message:** `fix(snapshot): cross-check envelope body step against snapshot filename for integrity`

---

## Week 4 — Complexity reduction and slicer correctness

---

### C-13 — Consolidate `CoreRelayPipeline` step-execution helpers 🟡

**Fixes:** C-02, C-03, C-05

The current pipeline has 7 private helpers for a single step execution path, most 4–6 lines each. The indirection makes thread-safety reasoning harder without adding clarity. Three targeted reductions:

**1. Inline `_create_next_envelope`** — it is a single-line wrapper with no independent value:
```python
# Before (pointless indirection):
result = self._create_next_envelope(current_envelope, agent_output)

# After (inline directly in _handle_subsequent_step):
result = self._context_broker.create_next_envelope(
    previous_envelope=current_envelope, agent_output=agent_output
)
```

**2. Merge `_apply_manifest` and `_apply_manifest_validation`** into one method with a `validate` flag:
```python
def _apply_manifest(
    self,
    envelope: ContextEnvelope,
    manifest: Optional[AgentManifest],
    validate: bool = False,
) -> Result[ContextEnvelope]:
    """Apply manifest hash to envelope, optionally validating write boundaries.

    Args:
        validate: True for subsequent steps (has prior payload to diff against).
                  False for the initial step.
    REQUIRES: caller holds self._state._lock.
    """
    if manifest is None:
        return Success(envelope)
    if validate:
        result = validate_manifest_boundaries(
            envelope, manifest, set(envelope.payload.keys())
        )
        if isinstance(result, Failure):
            return self._rollback_internal(result.reason)
    return Success(envelope.with_manifest_hash(manifest.compute_hash()))
```

**3. Replace `_rollback_with_reason` + `_do_rollback(consume_history=bool)` with two clearly named methods** — the boolean flag is the tell that two different things needed two different names:
```python
def _rollback_internal(self, reason: str) -> Result[ContextEnvelope]:
    """Rollback triggered by contradiction or validation failure.

    Does NOT consume history. REQUIRES: caller holds self._state._lock.
    """
    if not self._state.has_history():
        return Failure(
            reason="No previous envelope to rollback to",
            code=ErrorCode.NO_ROLLBACK_AVAILABLE,
        )
    previous_envelope = self._state.peek_last()
    if previous_envelope is None:
        return Failure(reason="No previous envelope", code=ErrorCode.INVALID_STATE)
    result = self._rollback_handler.restore_to_previous(
        previous_envelope, self._state.snapshot_ids, self._snapshot_store, reason
    )
    if isinstance(result, RollbackSuccess):
        self._state.set_current(result.value)
    return result

def rollback(self) -> Result[ContextEnvelope]:
    """Manual rollback. Consumes history so repeated calls step back further."""
    with self._state.transaction():
        if not self._state.has_history():
            return Failure(
                reason="No previous envelope to rollback to",
                code=ErrorCode.NO_ROLLBACK_AVAILABLE,
            )
        previous_envelope = self._state.peek_last()
        if previous_envelope is None:
            return Failure(reason="No previous envelope", code=ErrorCode.INVALID_STATE)
        result = self._rollback_handler.restore_to_previous(
            previous_envelope, self._state.snapshot_ids, self._snapshot_store,
            "Manual rollback"
        )
        if isinstance(result, RollbackSuccess):
            self._state.consume_last()
            self._state.set_current(result.value)
        return result
```

After this commit the private helper count for step execution drops from 7 to 4, and the happy path is readable in a single scroll.

**Commit message:** `refactor(pipeline): consolidate step-execution helpers — inline one-liners, merge manifest methods, replace consume_history bool`

---

### C-14 — Fix slicer token estimation crash on non-string payload values 🟠

**Fixes:** C-06

**Root cause.**
`RecencySlicePacker` and `RelevanceSlicePacker` both do:
```python
section_tokens = len(section_text) // 3
```
where `section_text = payload[key]`. Since `payload: dict[str, Any]`, a value can be a list, dict, int, or bool. `len()` on an `int` raises `TypeError`. `len()` on a `list` returns item count, not character length — a meaningless token estimate.

**Fix — call `_estimate_tokens` from `envelope.py`**, which handles all types correctly via JSON serialisation:
```python
# packers.py — add import
from relay.envelope import _estimate_tokens as _estimate_section_tokens

# RecencySlicePacker.pack — replace:
section_tokens = len(section_text) // 3
# with:
section_tokens = _estimate_section_tokens({key: payload[key]})

# RelevanceSlicePacker.pack — replace:
section_tokens = len(payload[key]) // 3
# with:
section_tokens = _estimate_section_tokens({key: payload[key]})
```

Wrapping in a single-key dict ensures the full JSON-serialised cost is measured, including structural overhead from keys and brackets.

**Tests to add** in `tests/unit/test_slicer.py`:
```python
def test_recency_packer_handles_non_string_section_values():
    """Packer must not raise TypeError when payload values are lists, dicts, or ints."""
    packer = RecencySlicePacker()
    payload = {
        "section_1": ["item1", "item2", "item3"],
        "section_2": {"nested": "dict"},
        "section_3": 42,
    }
    manifest = AgentManifest("a1", frozenset(), frozenset(), 10000)
    result = packer.pack(payload, manifest)
    assert isinstance(result, Success)

def test_relevance_packer_handles_non_string_section_values():
    """Packer must not raise TypeError when payload values are non-strings."""
    provider = FixedEmbeddingProvider([1.0, 0.0])
    packer = RelevanceSlicePacker(provider)
    payload = {"section_1": [1, 2, 3], "section_2": {"k": "v"}}
    manifest = AgentManifest("a1", frozenset(), frozenset(), 10000)
    result = packer.pack(payload, manifest)
    assert isinstance(result, Success)
```

**Commit message:** `fix(slicer): use _estimate_tokens for section cost — fixes TypeError on non-string payload values`

---

## Commit order and dependency map

```
C-01  fix import order in envelope.py           (no deps)
C-02  fix Result TypeAlias                      (no deps — run mypy after)
C-03  secret validation in _sign_envelope       (depends on C-01)
C-04  typed _require_field helpers              (no deps)

C-05  remove dead code                          (depends on C-04)
C-06  remove unused value types                 (depends on C-05)
C-07  stateless SnapshotManager                 (depends on C-05)
C-08  lock contract + debug assertions          (depends on C-07)

C-09  remove duplicate pipeline_id validation   (depends on C-03)
C-10  fix module docstrings                     (no deps)
C-11  replace tautological benchmark            (no deps)
C-12  load_snapshot integrity cross-check       (depends on C-04)

C-13  consolidate pipeline helpers              (depends on C-07, C-08)
C-14  fix slicer token estimation               (no deps)
```

---

## Pre-commit checklist

Run this after every commit before moving to the next one.

- [ ] `mypy --strict src/` — zero errors
- [ ] `pytest tests/unit -v` — all passing
- [ ] `pytest tests/integration -v` — all passing
- [ ] No new `# type: ignore` added
- [ ] Every new public function has at least one test
- [ ] Every new `Result`-returning function has a test for each `Failure` code it can return
- [ ] Docstring updated if behaviour changed
- [ ] No bare `except:` or `except Exception:` added
- [ ] Commit message follows `type(scope): imperative sentence` format
- [ ] If shared state was touched: concurrent test extended
