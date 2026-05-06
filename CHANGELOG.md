# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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