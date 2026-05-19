# Phase 2: Structured Audit Logging — Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 12 new/modified files
**Analogs found:** 10 / 12 (2 trivial/modifications)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/relay/audit/__init__.py` | config | static-export | `src/relay/budget/__init__.py` | exact |
| `src/relay/audit/events.py` | model | static-data | `src/relay/types.py` (frozen dataclass) + `src/relay/envelope.py:57-138` (ContextEnvelope) | exact |
| `src/relay/audit/sink.py` | contract + utility | request-response | `src/relay/snapshot_protocol.py` (Protocol + Closeable) + `src/relay/snapshot.py` (logging) | exact |
| `src/relay/audit/redactor.py` | utility | transform | `src/relay/slicer/packers.py:40-60` (RecencySlicePacker transform) | role-match |
| `src/relay/core_pipeline.py` | controller | request-response | existing file (modify: injection + event calls) | exact |
| `src/relay/envelope.py` | controller | request-response | existing file (modify: `max_age_seconds` already exists) | trivial |
| `src/relay/types.py` | model | static-data | existing file (modify: add ErrorCode member) | trivial |
| `src/relay/__init__.py` | config | static-export | existing file (modify: add exports) | trivial |
| `tests/unit/test_audit_events.py` | test | static-data | `tests/unit/test_snapshot.py:1-80` | role-match |
| `tests/unit/test_audit_sink.py` | test | request-response | `tests/unit/test_budget.py:37-42` | role-match |
| `tests/unit/test_audit_redactor.py` | test | transform | `tests/unit/test_budget.py:61-69` | role-match |
| `tests/conftest.py` | test | static-data | existing file (modify: add FixedAuditSink) | trivial |

## Pattern Assignments

---

### `src/relay/audit/__init__.py` (config, static-export)

**Analog:** `src/relay/budget/__init__.py` (10 lines)

**Imports + exports pattern** (lines 1-10):
```python
"""Budget enforcement module for token cap validation.

Owns: HardCapEnforcer, TokenCounter protocol.
Does NOT: count tokens directly, or import tiktoken eagerly.
"""

from relay.budget.enforcer import HardCapEnforcer
from relay.budget.token_counter import TokenCounter

__all__ = ["HardCapEnforcer", "TokenCounter"]
```

**Key pattern:** Module docstring (three-line format: summary, Owns, Does NOT). Re-export from submodules via `from relay.audit.sink import ...`. Explicit `__all__` list.

---

### `src/relay/audit/events.py` (model, static-data)

**Analog 1:** `src/relay/types.py` lines 44-78 — `ErrorCode(str, Enum)` pattern for `AuditOutcome` enum

**Enum pattern** (types.py:44-46):
```python
class ErrorCode(str, Enum):
    """Error codes for Relay failures. Used exhaustively for type safety."""

    INVALID_PIPELINE_ID = "INVALID_PIPELINE_ID"
    # ...
```

**Analog 2:** `src/relay/types.py` lines 110-132 — `@dataclass(frozen=True)` for `Success`, `Failure`

**Frozen dataclass pattern** (types.py:110-115):
```python
@dataclass(frozen=True)
class Success(Generic[T]):
    """Represents a successful result with a value."""

    value: T
```

**Analog 3:** `src/relay/envelope.py` lines 57-138 — `ContextEnvelope` frozen dataclass with default values and `__post_init__` validation

**Frozen dataclass with defaults pattern** (envelope.py:57-107):
```python
@dataclass(frozen=True)
class ContextEnvelope:
    """Immutable context envelope passed between agents."""

    relay_version: str
    pipeline_id: str
    step: int
    # ... required fields ...

    fork_id: str | None = None
    join_strategy: str | None = None
    # ... optional fields with defaults ...

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError(f"step must be >= 1, got {self.step}")
        # ...
```

**Key pattern for 17 event types:** Each event is a separate `@dataclass(frozen=True)` class. Common fields (event_type with default, pipeline_id, step, outcome, timestamp, latency_ms) are repeated in each class. Event-specific fields follow. Use `field(default_factory=...)` for `timestamp`:

```python
# Derived pattern from envelope.py + types.py conventions:
@dataclass(frozen=True)
class PipelineCreated:
    """Emitted when a pipeline is created."""
    event_type: str = field(default="pipeline_created", init=False)
    pipeline_id: str
    step: int = 0
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    latency_ms: float = 0.0
    relay_version: str = ""
    storage_path: str = ""
```

**Union type alias pattern** (RESEARCH.md:364-386, for Python 3.12):
```python
type AuditEvent = (
    PipelineCreated
    | PipelineClosed
    | StepExecutionStarted
    # ...all 17...
)
```

---

### `src/relay/audit/sink.py` (contract + utility, request-response)

**Protocol analog:** `src/relay/snapshot_protocol.py` lines 16-86 — `SnapshotStore(Closeable, Protocol)`

**`@runtime_checkable` Protocol extending `Closeable`** (snapshot_protocol.py:16-86):
```python
@runtime_checkable
class SnapshotStore(Closeable, Protocol):
    """Protocol for snapshot storage backends."""

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID.
        Args:
            envelope: The context envelope to persist.
        Returns:
            Success with the snapshot ID string, or Failure...
        """
        ...

    def close(self) -> None:
        """Release any resources held by the snapshot store."""
        ...
```

**`Closeable` Protocol** (types.py:37-41):
```python
@runtime_checkable
class Closeable(Protocol):
    """Protocol for resources that require explicit cleanup."""

    def close(self) -> None: ...
```

**Protocol imports pattern** (snapshot_protocol.py:7-13):
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from relay.types import Closeable, Result
```

**Logging pattern** (snapshot.py:7-8, 16):
```python
import logging

logger = logging.getLogger(__name__)
```

**Default emit failure handling:** fire-and-forget with ERROR-level logging (derived from D-06, no analog — this is new behavior). But the logging pattern itself matches `snapshot.py:16`.

**JsonLogSink pattern** (derived from RESEARCH.md:486-497):
```python
class JsonLogSink:
    def __init__(self, logger_name: str = "relay.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, event: AuditEvent) -> None:
        try:
            record = json.dumps(asdict(event), default=str, sort_keys=True)
            self._logger.info(record)
        except Exception:
            logger.error("Failed to serialize audit event: %s", type(event).__name__, exc_info=True)

    def close(self) -> None:
        pass
```

---

### `src/relay/audit/redactor.py` (utility, transform)

**Analog:** `src/relay/slicer/packers.py` lines 40-60 — `RecencySlicePacker.pack()` method that transforms payload dicts

**Transform pattern** (packers.py:40-60, signature style):
```python
class RecencySlicePacker:
    def pack(self, payload: JSONDict, manifest: AgentManifest) -> Result[JSONDict]:
        """Slice the payload to retain only the most recent sections by recency."""
        def _recency_sort_key(k: str) -> tuple[int, int, str]:
            if "_" in k and k.split("_")[-1].isdigit():
                return (0, int(k.split("_")[-1]), k)
            # ...
```

**Key pattern for `PayloadRedactor`:** dict-comprehension filter with frozenset allowlist:

```python
# Derived pattern from RESEARCH.md:275-293
class PayloadRedactor:
    """Default-deny allowlist-based payload redactor."""

    ALLOWED_FIELDS: frozenset[str] = frozenset({
        "adapter_name", "agent_name", "step", "pipeline_id",
        "token_count", "budget_used", "budget_limit",
    })

    def redact_payload(self, payload: JSONDict) -> JSONDict:
        """Return only allowlisted fields from payload."""
        return {k: v for k, v in payload.items() if k in self.ALLOWED_FIELDS}
```

---

### `src/relay/core_pipeline.py` (controller, request-response) — MODIFY

**Analog:** Existing file. Follow `snapshot_store` optional injection pattern.

**Field declaration pattern** (core_pipeline.py:68-71):
```python
token_counter: TokenCounter | None = None
slice_packer: SlicePacker | None = None
registry: AdapterRegistry | None = None
snapshot_store: SnapshotStore | None = None
# NEW:
audit_sink: AuditSink | None = None
```

**Private field init pattern** (core_pipeline.py:77):
```python
# In @dataclass body, init=False field:
_audit_sink: AuditSink = field(init=False, repr=False)
```

**Default construction in `__post_init__`** (core_pipeline.py:124-127):
```python
if self.snapshot_store is not None:
    self._snapshot_store = self.snapshot_store
else:
    self._snapshot_store = LocalFileSnapshotStore(storage_path=self.storage_path)
```

**`create()` factory parameter injection** (core_pipeline.py:82-111):
```python
@classmethod
def create(
    cls,
    signing_secret: str,
    token_budget: int = 8000,
    storage_path: str = "./relay_data/snapshots",
    token_counter: TokenCounter | None = None,
    # ... existing params ...
    snapshot_store: SnapshotStore | None = None,
    audit_sink: AuditSink | None = None,                         # NEW
) -> Result["CoreRelayPipeline"]:
    # ...
    pipeline = cls(
        signing_secret=signing_secret,
        # ... existing ...
        snapshot_store=snapshot_store,
        audit_sink=audit_sink,                                    # NEW
    )
```

**`close()` resource cleanup pattern** (core_pipeline.py:152-160):
```python
def close(self) -> None:
    self._snapshot_store.close()
    # NEW:
    self._audit_sink.close()
```

---

### `src/relay/envelope.py` (controller, request-response) — MODIFY

**Analog:** Existing file. `max_age_seconds` parameter already exists at line 187.

**Existing `verify_signature` with `max_age_seconds`** (envelope.py:184-205):
```python
def verify_signature(
    envelope: ContextEnvelope,
    secret: str,
    max_age_seconds: int | None = 86400,
) -> bool:
    """Verify the signature of an envelope."""
    if max_age_seconds is not None:
        age = (datetime.now(timezone.utc) - envelope.timestamp).total_seconds()
        if age > max_age_seconds:
            return False
    expected_sig = compute_signature(envelope, secret)
    return hmac.compare_digest(envelope.signature, expected_sig)
```

**Note:** The `max_age_seconds` parameter already exists with default `86400`. No structural change needed for `verify_signature` — the callers in `core_pipeline._apply_manifest()` now emit `signature_verification_stale` events when the age check fails.

---

### `src/relay/types.py` (model, static-data) — MODIFY

**Analog:** Existing file. Add `STALE_SIGNATURE` to `ErrorCode` enum.

**ErrorCode enum pattern** (types.py:44-78, add entry):
```python
class ErrorCode(str, Enum):
    """Error codes for Relay failures. Used exhaustively for type safety."""

    INVALID_PIPELINE_ID = "INVALID_PIPELINE_ID"
    # ... existing entries ...
    ALL_FORKS_FAILED = "ALL_FORKS_FAILED"
    FORK_EXECUTION_FAILED = "FORK_EXECUTION_FAILED"
    INVALID_JOIN_STRATEGY = "INVALID_JOIN_STRATEGY"
    STALE_SIGNATURE = "STALE_SIGNATURE"          # NEW — add after INVALID_JOIN_STRATEGY
```

---

### `src/relay/__init__.py` (config, static-export) — MODIFY

**Analog:** Existing file. Append audit imports.

**Existing export pattern** (__init__.py:7-18):
```python
from relay.budget import HardCapEnforcer, TokenCounter
from relay.snapshot import LocalFileSnapshotStore
from relay.snapshot_in_memory import InMemorySnapshotStore
from relay.snapshot_protocol import SnapshotStore
from relay.types import ErrorCode, Failure, Result, RollbackSuccess, Success, __version__
```

**Add after `from relay.snapshot_protocol import SnapshotStore`:**
```python
from relay.audit import AuditSink, AuditEvent, AuditOutcome, JsonLogSink
```

**Append to `__all__`:**
```python
__all__: list[str] = [
    # ... existing ...
    "AuditEvent",
    "AuditOutcome",
    "AuditSink",
    "JsonLogSink",
]
```

---

### `tests/unit/test_audit_events.py` (test, static-data) — NEW

**Analog:** `tests/unit/test_snapshot.py` lines 1-80

**Test file structure pattern** (test_snapshot.py:1-80):
```python
"""Unit tests for relay.snapshot."""

import pytest

from relay.audit.events import (
    PipelineCreated, PipelineClosed, AuditOutcome,
    # ... all 17 event types ...
)

class TestAuditEvents:
    def test_pipeline_created_has_required_fields(self) -> None:
        """Test name is a sentence describing the behavior."""
        event = PipelineCreated(
            pipeline_id="test-123",
            relay_version="1.0",
            storage_path="./data",
        )
        assert event.event_type == "pipeline_created"
        assert event.pipeline_id == "test-123"
        assert event.outcome == AuditOutcome.SUCCESS
        assert isinstance(event.timestamp, str)
        assert event.timestamp  # non-empty ISO string

    def test_event_is_frozen_cannot_be_mutated(self) -> None:
        """Verify frozen dataclass immutability."""
        event = PipelineCreated(pipeline_id="test-123")
        with pytest.raises(AttributeError):
            event.pipeline_id = "changed"  # type: ignore[misc]
```

**Protocol compliance test pattern** (test_budget.py:38-42):
```python
from relay.types import Closeable

class TestAuditSinkProtocol:
    def test_audit_sink_protocol_is_runtime_checkable(self) -> None:
        """Verify Protocol compliance."""
        sink = JsonLogSink()
        from relay.audit.sink import AuditSink
        assert isinstance(sink, AuditSink)
        assert isinstance(sink, Closeable)
```

### `tests/unit/test_audit_sink.py` (test, request-response) — NEW

**Analog:** `tests/unit/test_budget.py` lines 37-42

**Test sink pattern — use `FixedAuditSink` test double:**

```python
"""Unit tests for relay.audit.sink."""

import json
import pytest

from relay.audit.events import PipelineCreated
from relay.audit.sink import AuditSink, JsonLogSink
from relay.types import Closeable
from tests.conftest import FixedAuditSink


class TestAuditSink:
    def test_audit_sink_protocol_is_runtime_checkable(self) -> None:
        sink = FixedAuditSink()
        assert isinstance(sink, AuditSink)
        assert isinstance(sink, Closeable)

    def test_emit_appends_event_to_list(self) -> None:
        sink = FixedAuditSink()
        event = PipelineCreated(pipeline_id="test-123")
        sink.emit(event)
        assert len(sink.events) == 1
        assert sink.events[0].pipeline_id == "test-123"

    def test_json_log_sink_serializes_to_valid_json(self) -> None:
        import logging
        sink = JsonLogSink()
        event = PipelineCreated(pipeline_id="test-123")
        # JsonLogSink.emit() should not raise
        sink.emit(event)
```

### `tests/unit/test_audit_redactor.py` (test, transform) — NEW

```python
"""Unit tests for relay.audit.redactor."""

import pytest

from relay.audit.redactor import PayloadRedactor
from relay.types import JSONDict


class TestPayloadRedactor:
    def test_redactor_strips_non_allowlisted_fields(self) -> None:
        redactor = PayloadRedactor()
        payload: JSONDict = {
            "adapter_name": "test-adapter",
            "agent_name": "test-agent",
            "secret_key": "should-not-appear",
            "user_data": {"ssn": "123-45-6789"},
        }
        result = redactor.redact_payload(payload)
        assert "adapter_name" in result
        assert "secret_key" not in result
        assert "user_data" not in result

    def test_redactor_passes_allowlisted_fields_through(self) -> None:
        redactor = PayloadRedactor()
        payload: JSONDict = {"adapter_name": "test", "pipeline_id": "abc"}
        result = redactor.redact_payload(payload)
        assert result == {"adapter_name": "test", "pipeline_id": "abc"}
```

---

### `tests/conftest.py` (test, static-data) — MODIFY

**Analog:** Existing `FixedCounter` test double pattern (conftest.py:6-22)

**Add `FixedAuditSink` test double:**

```python
from relay.audit.events import AuditEvent


@dataclass
class FixedAuditSink:
    """AuditSink that collects events for test assertions."""

    events: list[AuditEvent] = field(default_factory=list)

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass

    @property
    def emitted_types(self) -> list[str]:
        return [e.event_type for e in self.events]
```

**Existing test double pattern to follow** (conftest.py:6-22):
```python
@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""

    value: int

    def count(self, text: str) -> int:
        return self.value

    def close(self) -> None:
        pass
```

---

## Shared Patterns

### Protocol Definition Pattern
**Source:** `src/relay/snapshot_protocol.py:16-86` + `src/relay/budget/token_counter.py:13-23`
**Apply to:** `AuditSink` Protocol in `audit/sink.py`

Convention: `@runtime_checkable`, extend `Closeable`, method signatures with docstrings, `...` (Ellipsis) as body. Return `None` for fire-and-forget emit.

### Optional Injection with Fallback
**Source:** `src/relay/core_pipeline.py:68-71` (field), `124-127` (post_init), `82-111` (factory)
**Apply to:** `CoreRelayPipeline.audit_sink` parameter

Three integration points:
1. `@dataclass` field: `audit_sink: AuditSink | None = None`
2. `__post_init__`: check `None`, build `JsonLogSink()`
3. `create()` factory: pass through parameter

### Fire-and-Forget Emit (D-06)
**Source:** No existing analog (new pattern). RESEARCH.md provides the design.
**Apply to:** `AuditSink.emit()`

`emit()` returns `None` (not `Result`). Exception caught and logged at ERROR level via `logging.getLogger(__name__).error(...)`. Pipeline never blocks on audit failures.

### Module Docstring (three-line)
**Source:** Every module in codebase. Example: `src/relay/snapshot.py:1-5`, `src/relay/envelope.py:1-8`
**Apply to:** All new files in `audit/` module

Format:
```python
"""Summary line.

Owns: comma-separated ownership list.
Does NOT: comma-separated exclusion list.
"""
```

### Frozen Dataclass Convention
**Source:** `AGENTS.md` + `src/relay/envelope.py:57` (ContextEnvelope), `src/relay/types.py:81` (SigningKey)
**Apply to:** All 17 event types in `audit/events.py`

Every event is `@dataclass(frozen=True)`. Use `field(default=...)` for constant defaults, `field(default_factory=...)` for computed defaults (timestamp), `field(init=False)` for computed-invariant fields (event_type).

### Test Doubles in conftest.py
**Source:** `tests/conftest.py:6-22` (`FixedCounter`)
**Apply to:** `FixedAuditSink` in `tests/conftest.py`

Simple `@dataclass` class with the same method signatures as the Protocol. `items: list[EventType] = field(default_factory=list)` to collect events. Always `close()` as no-op.

### Explicit `__all__` Export
**Source:** `src/relay/budget/__init__.py:10`, `src/relay/snapshot_protocol.py:89-92`, `src/relay/snapshot_in_memory.py:18`
**Apply to:** All new `audit/` module files and modified `__init__.py`

Every public module exports via `__all__: list[str] = [...]`.

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/relay/audit/sink.py` (emit fire-and-forget semantics) | contract | request-response | No existing fire-and-forget pattern; all current `Result`-returning functions propagate errors. D-06 mandates fire-and-forget. |

## Metadata

**Analog search scope:** `src/relay/` (all Python source), `tests/` (all test files)
**Files scanned:** `types.py`, `envelope.py`, `snapshot.py`, `snapshot_protocol.py`, `snapshot_in_memory.py`, `core_pipeline.py`, `__init__.py`, `budget/__init__.py`, `budget/token_counter.py`, `budget/enforcer.py`, `runners/protocol.py`, `parallel/join.py`, `slicer/packers.py`, `tests/conftest.py`, `tests/unit/test_snapshot.py`, `tests/unit/test_budget.py`
**Pattern extraction date:** 2026-05-17
