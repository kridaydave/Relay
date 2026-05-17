# External Integrations

**Analysis Date:** 2026-05-17

## APIs & External Services

**LLM Provider Adapters (optional, lazy-imported):**
- **Local model REST API** — OpenAI-compatible `/v1/chat/completions` endpoints
  - Adapter: `LocalModelAdapter` in `src/relay/runners/local_model.py`
  - Compatible servers: Ollama >=0.1.14, vLLM >=0.4.0, any OpenAI-compatible API
  - Connection: `base_url` (e.g., `http://localhost:11434`) + `model` name
  - SDK/Client: `httpx` (lazy-imported, optional dependency `[local]`)
  - No streaming in v0.3/v0.4 — blocking POST requests

- **LangChain Runnables** — Any LangChain `Runnable` (LCEL chain, chat model, etc.)
  - Adapter: `LangChainAdapter` in `src/relay/runners/langchain.py`
  - SDK/Client: `langchain-core>=0.1` (optional dependency `[langchain]`)
  - Constraint: Agent must be stateless (no `ConversationBufferMemory` etc.)

- **CrewAI Agents** — CrewAI `Agent` with `memory=False`
  - Adapter: `CrewAIAdapter` in `src/relay/runners/crewai.py`
  - SDK/Client: `crewai>=0.30` (optional dependency `[crewai]`)
  - Constraint: `memory=True` detected at construction — hard failure (ValueError)

- **AutoGen AssistantAgents** — AutoGen single-turn execution
  - Adapter: `AutoGenAdapter` in `src/relay/runners/autogen.py`
  - SDK/Client: `pyautogen>=0.2` (optional dependency `[autogen]`)
  - A fresh `UserProxyAgent` is created per `run()` call — no history accumulation

- **Raw SDK/Arbitrary Callables** — Any Python callable, sync or async
  - Adapter: `RawSDKAdapter` in `src/relay/runners/raw_sdk.py`
  - Dependencies: stdlib only (no optional packages required)
  - Signature: `(messages: list[dict[str, str]]) -> str` or `async -> str`
  - Wrap pattern: `RawSDKAdapter(fn=openai_callable)`

**No direct LLM API SDK imports** — The codebase itself does not import `openai`, `anthropic`, or any other provider SDK. All provider integration is through the adapter pattern — the user provides the integration code.

## Data Storage

**Databases:**
- Not used — no database dependency detected

**File Storage:**
- Local filesystem only — JSON snapshot persistence
  - Location: `./relay_data/snapshots/` (configurable via `CoreRelayPipeline(storage_path=...)`)
  - Format: JSON files per snapshot, `index.json` per pipeline
  - Pattern: `{pipeline_id}@{step}_{uuid}.json`
  - Index: `{pipeline_id}/index.json` — ordered list of snapshot IDs
  - Max size: 100 MB per snapshot file (`MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024`)
  - Write strategy: Atomic via `os.replace` (write to `.tmp` then rename)
  - Security: Pipeline ID validated against `^[a-zA-Z0-9_-]{1,128}$` before filesystem use
  - Symlink protection: Refuses to write if pipeline path is a symlink
  - Module: `src/relay/snapshot.py`

**Caching:**
- None detected — no caching layer or service

## Authentication & Identity

**Auth Provider:**
- Custom HMAC-SHA256 signing — no external auth provider
  - Implementation: `src/relay/envelope.py` — `compute_signature()` / `verify_signature()`
  - Algorithm: `hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()`
  - Comparison: `hmac.compare_digest()` (constant-time, never `==`)
  - Envelope fields covered: `relay_version|pipeline_id|step|timestamp|token_budget_used|token_budget_total|manifest_hash|payload_json`
  - Secret strength: Must be ≥32 characters (validated at `ContextBroker` construction in `src/relay/context_broker.py`)
  - Optional staleness check: `max_age_seconds` parameter on `verify_signature()`

**Identity:**
- Agent manifests define identity via `agent_id` field (`AgentManifest` in `src/relay/slicer/manifest.py`)
- Agent manifest hash (`SHA-256`) is embedded in each `ContextEnvelope`
- Pipeline IDs are auto-generated via `uuid.uuid4().hex`

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, or similar integration
- Errors returned as `Result[T] = Success[T] | RollbackSuccess[T] | Failure` (no exceptions for operational errors)
- 61 distinct `ErrorCode` values defined in `src/relay/types.py`

**Logging:**
- Python `logging` module — minimal usage
  - `src/relay/snapshot.py` — warnings for temp file/index cleanup failures
  - `src/relay/parallel/join.py` — warnings for unexpected fork exceptions
- No structured logging, no log aggregation, no metrics

**Observability Properties:**
- Pipeline exposes read-only properties: `history`, `snapshot_index`, `current_envelope`
- Module: `src/relay/core_pipeline.py`

## CI/CD & Deployment

**Hosting:**
- Not applicable — pure Python library distributed via PyPI
- Package name: `relay-middleware` (version `0.4.2`)
- GitHub repository: `https://github.com/kridaydave/relay`

**CI Pipeline:**
- GitHub Actions — `.github/workflows/ci.yml`
  - Runs on: `ubuntu-latest`
  - Python version: `3.12`
  - Triggers: push/PR to `main`
  - Steps:
    1. Checkout + Python setup
    2. `pip install -e .[dev]`
    3. Verify `py.typed` marker exists (PEP 561 compliance)
    4. `mypy --strict src/` — type check with zero suppressions
    5. `scripts/check_test_names.py` — enforce test naming convention
    6. `pytest tests/ -v` — full test suite

**No deployment pipeline detected** — no PyPI publish workflow, no Docker build, no CD

## Environment Configuration

**Required env vars:**
- None — all configuration is programmatic (constructor parameters)

**Secrets location:**
- `signing_secret` passed directly to `CoreRelayPipeline.create()` or `ContextBroker`
- No env-file loading, no secret manager integration
- `.env` file is git-ignored but none present currently

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP server, no webhook endpoints

**Outgoing:**
- None — no callback registration mechanism

**Note:** The adapter pattern allows users to create callbacks via `RawSDKAdapter` wrapping any callable, but this is user-provided code, not a built-in integration.

---

*Integration audit: 2026-05-17*
