---
phase: 1
reviewers: [gemini]
reviewed_at: 2026-05-17T18:00:00Z
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 1

## Gemini Review

## Overall Assessment

The provided plans form a cohesive and logical roadmap for extracting the `SnapshotStore` into a protocol and introducing a pluggable architecture. The decomposition into three distinct plans (Protocol Extraction, In-Memory Store, Pipeline Wiring) perfectly isolates the refactoring steps, ensuring testability at each boundary.

However, given the project's requirements for parallel execution (PAR-01) and strict error handling (Result[T]), there are a few edge cases—specifically regarding thread safety, memory isolation, and dependency lifecycles—that need to be addressed before execution.

---

## Plan 01-01: Extract SnapshotStore Protocol + Rename to LocalFileSnapshotStore

### Summary
A foundational refactoring plan that safely extracts the interface into a structural type (Protocol) while renaming the concrete implementation. It correctly identifies the need for a close() method to satisfy a Closeable interface.

### Strengths
- Architectural clarity: separating protocol into its own file prevents circular dependencies
- Explicit interface: mandating close() ensures proper resource cleanup across future implementations
- Verification: Protocol acceptance test guarantees strict adherence to the defined interface

### Concerns
- HIGH: Backwards compatibility — renaming SnapshotStore to LocalFileSnapshotStore is a breaking change for external consumers
- MEDIUM: Error type signatures — Protocol must define Result[T] return types generically enough for all subtypes

### Suggestions
- Leave a deprecation alias (SnapshotStore = LocalFileSnapshotStore) with DeprecationWarning for one minor version
- Ensure snapshot_protocol.py exports via __all__ so external users can implement it

---

## Plan 01-02: Create InMemorySnapshotStore

### Summary
A straightforward plan to implement a test double for the new protocol. Significantly speeds up testing by eliminating disk I/O.

### Strengths
- Simplicity: dict-based storage is lightweight and perfectly suited for an in-memory double
- Contract adherence: respecting existing error codes ensures behavior parity with real implementation

### Concerns
- HIGH: Thread safety — native Python dict is not thread-safe for concurrent fork-join execution (PAR-01)
- MEDIUM: State leakage — storing references to envelopes means mutations retroactively modify saved snapshots

### Suggestions
- Wrap dict access in threading.Lock to satisfy the non-reentrant lock constraint
- Use copy.deepcopy() on save_snapshot and load_snapshot for memory isolation

---

## Plan 01-03: Wire SnapshotStore Protocol into CoreRelayPipeline

### Summary
Final integration step updating the core engine to accept any protocol-compliant store via dependency injection, matching established patterns.

### Strengths
- Consistency: reuses the established injection pattern (token_counter, slice_packer) for uniform API surface
- Scope: limiting to wiring + wiring tests prevents scope creep

### Concerns
- MEDIUM: Lifecycle ownership — if user injects a custom store, who calls close()? Pipeline might close a store the user reuses across pipelines
- LOW: Default instantiation — must default to LocalFileSnapshotStore cleanly without unexpected file path requirements

### Suggestions
- Define ownership model: pipeline only calls close() if it created the store; user is responsible for injected stores
- Ensure __init__ type hints use the Protocol type (not concrete class) for mypy compliance

---

## Risk Assessment

**Risk Level: MEDIUM**

The architectural direction is excellent. Risk elevated to MEDIUM due to threading and mutability concerns in InMemorySnapshotStore (Plan 01-02). Because Relay guarantees cryptographic integrity and state safety, an in-memory store that leaks state references or crashes under parallel execution violates core invariants. Deep copying and locking in the in-memory store, plus a deprecation alias for the rename, mitigates to LOW.

---

## Consensus Summary

### Agreed Strengths
- Clean decomposition into 3 plans with clear dependency ordering
- Following established injection patterns (token_counter, slice_packer)
- Protocol acceptance test verifying isinstance checks

### Agreed Concerns
- Backwards compatibility of SnapshotStore rename (deprecation alias recommended)
- Thread safety in InMemorySnapshotStore under parallel execution
- Lifecycle ownership of injected snapshot_store close() responsibility

### Divergent Views
- N/A — single reviewer
