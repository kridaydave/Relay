---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "tech"
---

# INTEGRATIONS.md — External Integrations

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## LLM Framework Adapters

Relay provides a universal adapter layer (`src/relay/runners/`) that wraps external LLM agent frameworks behind a common `AgentRunner` protocol.

### Adapter Protocol (`src/relay/runners/protocol.py`)

```python
class AgentRunner(Protocol):
    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput: ...
```

All adapters implement this async interface. The pipeline calls `adapter.run(slice, manifest)`.

### Bundled Adapters

| Adapter | Module | Framework | Install Extra | Import Safety |
|---------|--------|-----------|---------------|---------------|
| `RawSDKAdapter` | `src/relay/runners/raw_sdk.py` | Direct HTTP (httpx) | `local` | Eager — stdlib + httpx only |
| `LangChainAdapter` | `src/relay/runners/langchain.py` | LangChain | `langchain` | Lazy via `__getattr__` |
| `CrewAIAdapter` | `src/relay/runners/crewai.py` | CrewAI | `crewai` | Lazy via `__getattr__` |
| `AutoGenAdapter` | `src/relay/runners/autogen.py` | AutoGen | `autogen` | Lazy via `__getattr__` |
| `LocalModelAdapter` | `src/relay/runners/local_model.py` | Local HTTP model | `local` | Lazy via `__getattr__` |

### Lazy Import Pattern

`src/relay/runners/__init__.py` uses `__getattr__` to lazy-import framework adapters:

```python
_LAZY_ADAPTERS: dict[str, str] = {
    "LangChainAdapter": "relay.runners.langchain",
    "CrewAIAdapter": "relay.runners.crewai",
    "AutoGenAdapter": "relay.runners.autogen",
    "LocalModelAdapter": "relay.runners.local_model",
}
```

This ensures `import relay.runners` does NOT require langchain/crewai/autogen/httpx to be installed.

### AdapterRegistry (`src/relay/runners/registry.py`)

Central registry for managing adapter instances:
- `register(name, adapter)` — add an adapter
- `get(name)` → `Result[AgentRunner]` — lookup by name
- `list_names()` → `list[str]` — list registered adapters

## Token Counting

| Implementation | Module | Dependency | Fallback |
|---------------|--------|------------|----------|
| `_TiktokenCounter` | `src/relay/budget/token_counter.py` | `tiktoken` (optional) | `HeuristicCounter` |
| `HeuristicCounter` | `src/relay/budget/token_counter.py` | None (stdlib) | Always available |

Auto-selection in `token_counter.py`:
```python
try:
    import tiktoken
    AutoTokenCounter = _TiktokenCounter
except ImportError:
    AutoTokenCounter = HeuristicCounter
```

Heuristic: `max(1, len(text) // 3)` — approximately 0.33 tokens/char, within 0.25-0.40 range of real BPE tokenizers (cl100k_base).

## Snapshot Storage

| Implementation | Module | Storage | Protocol |
|---------------|--------|---------|----------|
| `LocalFileSnapshotStore` | `src/relay/snapshot.py` | Local filesystem (JSON files) | `SnapshotStore` |
| `InMemorySnapshotStore` | `src/relay/snapshot_in_memory.py` | In-memory dict | `SnapshotStore` |

Protocol (`src/relay/snapshot_protocol.py`):
```python
class SnapshotStore(Protocol):
    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]: ...
    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]: ...
    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]: ...
    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]: ...
    def delete_snapshot(self, snapshot_id: str) -> Result[None]: ...
    def close(self) -> None: ...
```

Filesystem storage details:
- Path pattern: `{storage_path}/{pipeline_id}/{snapshot_id}.json`
- Index file: `{storage_path}/{pipeline_id}/index.json`
- Atomic writes: `os.O_CREAT | os.O_EXCL | os.O_WRONLY | O_NOFOLLOW` → `os.replace()`
- Max size: 100 MB per snapshot
- Symlink defense: checks before and after directory creation

## Audit Logging

| Component | Module | Destination |
|-----------|--------|-------------|
| `JsonLogSink` | `src/relay/audit/sink.py` | `relay_audit.log` (JSON lines) |
| `PayloadRedactor` | `src/relay/audit/redactor.py` | Redacts sensitive fields |

Sink protocol:
```python
class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...
    def close(self) -> None: ...
```

Fire-and-forget semantics (D-06): errors are logged by the sink, never propagated.

## External Dependencies Summary

| Category | Packages | Required? |
|----------|----------|-----------|
| Core runtime | None | No — zero deps |
| Token counting | `tiktoken` | Optional |
| Agent frameworks | `langchain-core`, `crewai`, `pyautogen` | Optional (pick one or more) |
| HTTP client | `httpx` | Optional (for local model adapter) |
| Dev tooling | `pytest`, `mypy`, `coverage`, `pytest-asyncio`, `anyio` | Dev only |

No external databases, message queues, auth providers, or webhook integrations. Relay is a pure library — all state is in-memory or local filesystem.
