---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "quality"
---

# CONVENTIONS.md — Coding Conventions

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## Module Docstrings (Rule 8.3)

Every module uses a three-line docstring format:

```python
"""Summary of what this module owns.

Owns: specific responsibilities, comma-separated.
Does NOT: things this module explicitly does not do.
"""
```

Example from `src/relay/core_pipeline.py`:
```python
"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""
```

## Type Safety (Rule 2.1)

- **`mypy --strict` with zero suppressions** — no `# type: ignore` anywhere in source
- **No bare `Any`** — all types must be explicit
- **PEP 695 type syntax** used where available: `type Result[T] = Success[T] | RollbackSuccess[T] | Failure`
- **`cast()`** used when type system needs help (e.g., JSON deserialization)
- **`Protocol`** for interface contracts (e.g., `TokenCounter`, `SnapshotStore`, `AgentRunner`)
- **`TYPE_CHECKING` guard** for circular import avoidance (e.g., `AgentManifest` import in `validator.py`)

## Domain Value Types

- **All domain value types are `@dataclass(frozen=True)`** — immutable by default
- Use `dataclasses.replace()` or `with_*` methods for copies
- Example: `envelope.with_manifest_hash(hash)`, `envelope.with_signature(sig)`

## Error Handling

- **`Result[T]` return type** for all operations that can fail — never exceptions for operational errors
- **`ErrorCode` enum** for typed error codes — exhaustive pattern matching
- **Exceptions only for programmer errors**: `RuntimeError` for lock violations, `ValueError` for invariant violations
- **No `assert` statements in production code** — CI enforces this

## Factory Pattern

- Use factory functions for validated construction:
  - `CoreRelayPipeline.create()` → `Result[CoreRelayPipeline]`
  - `create_context_broker()` → `Result[ContextBroker]`
- Direct construction bypasses validation (for internal use with pre-validated inputs)
- Document this in docstrings: "Use X() factory to construct instances with validation."

## Lock Discipline

- `PipelineState` uses non-reentrant `threading.Lock` via `transaction()` context manager
- **Never call `transaction()` inside another transaction** — raises `RuntimeError`
- All state mutations require lock: `self._assert_lock_held()` at entry of each method
- Lock is released before I/O operations (e.g., `adapter.run()`)
- Document lock requirements in docstrings: "REQUIRES: caller holds self._state._lock via transaction() context manager."

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case.py` | `pipeline_state.py` |
| Classes | `PascalCase` | `CoreRelayPipeline` |
| Protocols | `PascalCase` | `TokenCounter`, `SnapshotStore` |
| Functions | `snake_case` | `create_context_broker` |
| Private helpers | `_snake_case` | `_sign_envelope`, `_compute_diff` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_SNAPSHOT_BYTES`, `_MIN_SECRET_LENGTH` |
| Error codes | `UPPER_SNAKE_CASE` | `INVALID_PIPELINE_ID` |
| Type vars | Single uppercase | `T`, `U` |
| Test functions | Sentence in snake_case | `test_envelope_signature_is_hmac_sha256` |

## Import Organization

Standard library first, then third-party, then local:

```python
import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from relay.types import ErrorCode, Failure, Result, Success
```

- **Lazy imports** for optional dependencies (framework adapters)
- **`from __future__ import annotations`** for forward references
- **`__all__`** explicitly lists public exports

## Security Patterns

- **HMAC signing**: `hmac.compare_digest()` for constant-time comparison — never `==`
- **Secret validation**: minimum 32 characters at `ContextBroker` construction
- **Pipeline ID validation**: regex `^[a-zA-Z0-9_-]{1,128}$` before filesystem use (path traversal prevention)
- **Symlink defense**: checks before and after directory creation in snapshot store
- **Atomic file writes**: `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW` + `os.replace()`
- **SigningKey repr redaction**: hides secret value from logs/debug output

## Async Conventions

- Async methods use `async def` and `await`
- `asyncio.gather()` for parallel fork execution
- `pytest-asyncio` with `asyncio_mode = "auto"` — no manual `@pytest.mark.asyncio` needed
- `asyncio_default_fixture_loop_scope = "function"` for fixture isolation

## Code Style

- **4-space indentation** (Python standard)
- **Line length**: not explicitly enforced by config, but code stays reasonable
- **String formatting**: f-strings for interpolation
- **Type annotations**: full annotations on all public APIs
- **Docstrings**: Google-style with Args/Returns sections for public methods
