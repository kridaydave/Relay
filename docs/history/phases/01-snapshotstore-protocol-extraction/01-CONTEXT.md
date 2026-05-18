# Phase 1: SnapshotStore Protocol Extraction - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor the existing `SnapshotStore` class into a `@runtime_checkable` Protocol, rename the file-based implementation to `LocalFileSnapshotStore`, create an `InMemorySnapshotStore` test double, and wire the Protocol into `CoreRelayPipeline`. This enables test doubles and pluggable backends without changing pipeline behavior.

**Requirements:** STO-01, STO-02, STO-03, STO-04
**Success criteria:**
1. `SnapshotStore` exists as `@runtime_checkable` Protocol in its own file
2. Existing `SnapshotStore` renamed to `LocalFileSnapshotStore` with all tests passing
3. `InMemorySnapshotStore` exists and satisfies the Protocol
4. `CoreRelayPipeline` accepts any Protocol-compatible store
5. All existing unit and integration tests pass

</domain>

<decisions>
## Implementation Decisions

### Protocol Surface (Methods)
- **D-01:** `SnapshotStore` Protocol includes 5 methods: `save_snapshot()`, `load_snapshot()`, `get_latest_snapshot()`, `list_snapshots()`, and `close()`. This covers all public methods of the current class plus resource cleanup.

### File Organization
- **D-02:** The `SnapshotStore` Protocol lives in its own file (`src/relay/snapshot_protocol.py`), following the `AgentRunner` pattern in `runners/protocol.py`.
- **D-03:** The existing file-based implementation stays in `src/relay/snapshot.py`, renamed from `SnapshotStore` to `LocalFileSnapshotStore`.

### Pipeline Wiring
- **D-04:** `CoreRelayPipeline` gets an optional `snapshot_store: SnapshotStore | None = None` field parameter (same pattern as `token_counter`, `slice_packer`, `registry`). When `None`, `LocalFileSnapshotStore(storage_path)` is constructed as default.

### InMemorySnapshotStore Location
- **D-05:** `InMemorySnapshotStore` lives in the main package (`src/relay/snapshot_in_memory.py`) so Relay users can use it in their own tests.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Protocol patterns (existing codebase)
- `src/relay/runners/protocol.py` — `AgentRunner` Protocol pattern to follow (same structure)
- `src/relay/budget/token_counter.py` — `TokenCounter` Protocol pattern for reference

### Existing stores to refactor
- `src/relay/snapshot.py` — Current `SnapshotStore` class to extract Protocol from
- `src/relay/core_pipeline.py` — Where `SnapshotStore` is used and needs wiring changes
- `src/relay/pipeline_rollback.py` — `RollbackHandler.restore_to_previous()` takes `SnapshotStore` parameter

### Test fixtures
- `tests/conftest.py` — Existing test doubles pattern (`FixedCounter`, `FixedEmbeddingProvider`)

### Requirements
- `docs/REQUIREMENTS.md` — STO-01 through STO-04 with traceability

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`@runtime_checkable` Protocol pattern**: Established by `AgentRunner` (runners/protocol.py) and `TokenCounter` (budget/token_counter.py). Follow the same method-signature-with-docstring pattern.
- **Existing Protocol-only file**: `src/relay/runners/protocol.py` shows the convention for standalone Protocol files.

### Established Patterns
- **Optional injection with fallback**: `token_counter`, `slice_packer`, and `registry` all use the pattern: `field: Type | None = None`, check in `__post_init__`, construct default if None.
- **Module docstrings**: Three-line format (summary, Owns, Does NOT) required for all new modules.
- **Explicit `__all__`**: Every public module exports via `__all__` list.
- **Protocols skip `@dataclass`**: Protocols use `class SnapshotStore(Protocol)`, not dataclass.

### Integration Points
- `CoreRelayPipeline.__post_init__` (line 112): `self._snapshot_store = SnapshotStore(...)` — needs updating to use new injection
- `CoreRelayPipeline.create()` factory (line 74-103): Add `snapshot_store` parameter
- `src/relay/__init__.py` (line 15, 37): Update import — keep `SnapshotStore` name for Protocol, add `LocalFileSnapshotStore` and `InMemorySnapshotStore`
- `RollbackHandler.restore_to_previous()` (line 19-48): Accepts `SnapshotStore` parameter — typing updates only

### Import Map (all break after Protocol moves to snapshot_protocol.py)

| File | Current import | Required change |
|------|---------------|-----------------|
| `src/relay/core_pipeline.py:29` | `from relay.snapshot import SnapshotStore` | `from relay.snapshot_protocol import SnapshotStore` |
| `src/relay/pipeline_rollback.py:8` | `from relay.snapshot import SnapshotStore` | `from relay.snapshot_protocol import SnapshotStore` |
| `tests/unit/test_snapshot.py:14` | `from relay.snapshot import ... SnapshotStore` | replace with `LocalFileSnapshotStore` |
| `src/relay/__init__.py:15` | `from relay.snapshot import SnapshotStore` | import Protocol from `snapshot_protocol`; add `LocalFileSnapshotStore`, `InMemorySnapshotStore` |

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following established codebase patterns.

</specifics>

<review_findings>
## Review Findings (2026-05-17)

### Gap 1 — `SnapshotStore` Protocol should extend `Closeable`
`Closeable` Protocol exists at `src/relay/types.py:19` (added in commit c9dd818). Use `class SnapshotStore(Closeable, Protocol)` so `isinstance(store, Closeable)` works and intent is explicit.

### Gap 2 — `LocalFileSnapshotStore.close()` must be added
Current `SnapshotStore` has no `close()` method. Rename alone won't satisfy the Protocol. Add `close(self) -> None: ...` as a no-op to `LocalFileSnapshotStore`. Same for `InMemorySnapshotStore`.

### Gap 3 — Import map (see Integration Points above)
Three source files and `__init__.py` import `SnapshotStore` from `relay.snapshot`. All break when Protocol moves. See Import Map table above.

### Gap 4 — `create()` factory also needs `snapshot_store` param
D-04 mentions field parameter injection, but `CoreRelayPipeline.create()` (lines 74-103) must also accept `snapshot_store: SnapshotStore | None = None` and pass it through to the constructor.

### Minor notes
- `storage_path` field: becomes ignored when `snapshot_store` is provided. Note this in docstring.
- `_snapshot_store: SnapshotStore` annotation on line 70 of `core_pipeline.py` will refer to Protocol after refactor — correct under structural subtyping, but verify mypy --strict passes.

</review_findings>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-SnapshotStore Protocol Extraction*
*Context gathered: 2026-05-17*
