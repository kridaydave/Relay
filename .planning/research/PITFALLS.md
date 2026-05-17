# Domain Pitfalls — Observability, Tooling, Storage & Hardening

**Domain:** AI agent context-passing middleware (Python library)
**Researched:** 2026-05-17
**Overall confidence:** MEDIUM (pitfalls verified from real incidents and Relay-specific projections)

---

## Critical Pitfalls

### PITFALL-1: Audit log dumps envelope payloads verbatim, leaking agent secrets

**What goes wrong:** The structured audit log logs full envelope payloads on every step event. Envelope payloads contain agent outputs — API keys returned by LLM tool calls, PII from conversation history, internal service URLs, database credentials. Once written to `relay.audit`, this data persists in log storage (stdout, Datadog, Loki) with weaker access controls than the pipeline.

**Why it happens:**
- Natural approach: `logger.info(json.dumps(envelope.payload))` in the audit handler
- "Log everything to debug" mindset
- No payload schema awareness — library doesn't know which fields are sensitive
- Agent outputs are inherently untrusted (agents hallucinate)

**Real-world incidents:**
- Supabase Python client leaked tokens/JWTs in httpx debug logs — custom filter workaround required (supabase/supabase-py#1025, HIGH confidence)
- IntelOwl leaked API keys marked `is_secret=True` via `logger.debug(f"Adding param {name} with value {value}")` (intelowlproject/IntelOwl#3465, HIGH confidence)
- Paperclip logged plaintext passwords in req.body on every failed login — pino-http `customProps` attached full body without redaction (paperclipai/paperclip#4759, HIGH confidence)
- Sentry Python SDK leaked auth tokens via `repr()` of exception objects instead of `str()` (getsentry/sentry-python#2417, HIGH confidence)

**Consequences:** Compliance violations (GDPR Art. 32, PCI-DSS), credential theft from log storage, secret rotation for anything that touched logs, legal liability for PII.

**Prevention:**
- **Never log payloads by default.** Audit events log metadata (step, pipeline_id, outcome, latency, diff key-names) but NOT payload values.
- Add `redact_keys: set[str]` parameter to audit emitter. Default: all keys redacted unless explicitly allowlisted.
- For debug tracing: `log_payloads: bool = False` flag that defaults off and emits a warning when enabled.
- Use structural pattern matching on event type (e.g., `handoff_validator.failed` logs diff *keys* not diff *values*).
- Implement a `SensitiveDataFilter` (like Supabase's workaround) that regex-matches known secret patterns.

**Detection:** Code review flag any `logging.*` call that includes `.payload`, `envelope`, or `agent_output`. Runtime check via `SensitiveDataFilter`.

**Phase:** v0.5 (audit log feature)

---

### PITFALL-2: Audit log volume explosion in production

**What goes wrong:** Every pipeline step emits multiple audit events (budget check, slice build, adapter start/complete, validation, snapshot save, state advance). With parallel forks, each fork emits its own events. A 10-step × 5-fork pipeline produces 50+ events per run. At 1000 runs/min = 50,000 events/min. DEBUG-level additionally emits per-attribute OTEL spans, ballooning 10-100×.

**Why it happens:**
- "Let's instrument everything" — events for every internal transition
- No sampling strategy
- Debug-level events shipped alongside production events with no level separation

**Real-world incidents:**
- OpenTelemetry default `parentbased_always_on` sampler samples 100% — one team saw CPU 13% → 30% just by enabling tracing (opentelemetry-python#3474, HIGH confidence)
- ConsoleSpanExporter in production writes every telemetry item to stdout — fills disk (OTEL troubleshooting docs, HIGH confidence)

**Consequences:** Log storage cost ballooning, noise buries signals, pipeline latency from JSON serialization, disk exhaustion on self-hosted deployments.

**Prevention:**
- **Define three severity tiers:**
  - `AUDIT` (always on): step ID, outcome, latency, budget remaining. NOT payload.
  - `INFO` (on by default): diff summary, adapter used, join strategy, validation scores.
  - `TRACE` (opt-in): full payloads, internal transitions, per-fork telemetry.
- Rate-limited logger: drop events beyond `max_events_per_second` with a counter.
- Use Python `logging` level filtering — don't reinvent.
- **Ship `relay.audit` logger at `WARNING` by default** — don't make users opt out of noise.
- Pre-release: benchmark events/second with a worst-case pipeline. CI gate: reject PRs adding audit events without benchmark update.

**Phase:** v0.5 (audit log feature)

---

### PITFALL-3: OTEL span-per-step creates unacceptable overhead in hot paths

**What goes wrong:** OpenTelemetry Python span creation costs ~30-45μs per span (OneUptime benchmark, 2026, MEDIUM confidence). A pipeline with 10 steps × 5 forks × 3 internal sub-spans (adapter, validate, snapshot) = 150 spans × 45μs = 6.75ms OTEL overhead per pipeline — a significant fraction of the v1.0 <50ms per-step performance gate.

**Why it happens:**
- "One span per semantic operation" is standard OTEL practice
- No distinction between hot-path spans (must be cheap) and diagnostic spans (can be expensive)
- Default `BatchSpanProcessor` config not optimized

**Real-world evidence:**
- Span creation: 30-45μs/span in Python. Nested spans multiply linearly. Attributes add 10-20% overhead (OneUptime, HIGH confidence).
- Default `parentbased_always_on` sampler causes 2-3× CPU increase in production (opentelemetry-python#3474, HIGH confidence).
- Pre-fork servers: `PeriodicExportingMetricReader` deadlocks after `os.fork()` because background thread state is inconsistent (OTEL troubleshooting docs, HIGH confidence).

**Prevention:**
- **Not every method needs a span.** Instrument at adapter boundary (`run()`) and validation boundary (`validate_handoff()`), not internal helpers.
- One span per pipeline step with key attributes, not nested child spans per operation.
- Lazy span creation: zero overhead if tracer is not configured. `_tracer.start_as_current_span` only when `_tracer and _tracer.is_enabled()`.
- Default sampling: recommend `parentbased_traceidratio` at 10% in production docs.
- Configure `BatchSpanProcessor`: `max_queue_size=2048`, `scheduled_delay_millis=5000`.
- **Ship OTEL as `relay[otel]` extra with lazy import** — `import relay` without the extra adds zero OTEL overhead.

**Detection:** Performance benchmark measuring span creation overhead per step. CI gate: total observability overhead <10ms per step.

**Phase:** v0.5 (OpenTelemetry feature)

---

### PITFALL-4: OTEL context propagation breaks with async/threaded adapters

**What goes wrong:** OpenTelemetry `contextvars` propagate through `asyncio` tasks but NOT through `threading.Thread` or `asyncio.to_thread()`. When a span is created in the async pipeline coroutine but the adapter (`CrewAIAdapter.LocalModelAdapter`) runs in a thread, child spans created inside the `to_thread` call are orphaned — no parent trace.

**Why it happens:**
- `contextvars` bind to the current thread — `to_thread()` creates a new thread with a fresh context
- `asyncio.to_thread()` doesn't propagate `contextvars` automatically
- Adapters use `asyncio.to_thread()` for sync framework code (CrewAI, AutoGen run methods)
- The natural `with tracer.start_as_current_span("run")` in the pipeline code doesn't extend into the thread

**Consequences:** Broken trace hierarchy — adapter execution spans are orphaned, not connected to pipeline trace. Lost attribution for adapter errors. Misleading waterfall charts.

**Prevention:**
- **Wrap the adapter call in a span that covers the full duration including thread execution:**
  ```python
  with tracer.start_as_current_span("adapter_run") as span:
      result = await asyncio.to_thread(adapter.run_sync, slice_, manifest)
      # Span captures adapter latency even if internal OTEL context is lost
  ```
- For adapters that need their own OTEL instrumentation: explicitly pass the parent context as an argument:
  ```python
  ctx = trace.get_current_span().get_span_context()
  await asyncio.to_thread(adapter.run_with_context, slice_, manifest, ctx)
  ```
- Document: "Relay's OTEL spans cover pipeline orchestration. Adapter-internal tracing requires each adapter to implement its own instrumentation."

**Detection:** Unit test with `FixedAgentRunner`: create a trace, run adapter via `to_thread`, verify adapter span is parented correctly. Integration test with real async adapter.

**Phase:** v0.5 (OpenTelemetry feature)

---

### PITFALL-5: CLI tightly coupled to internal API — breaks when internals change

**What goes wrong:** The CLI (`relay inspect`, `relay diff`, `relay rollback`) directly imports `SnapshotStore`, constructs `ContextEnvelope`, calls `RollbackHandler`. Every internal refactor (changing `SnapshotStore.save_snapshot()` signature, modifying `ContextEnvelope` fields) breaks the CLI. The CLI bypasses `CoreRelayPipeline.create()` validation.

**Why it happens:**
- "Just reading the same snapshot files" — path of least resistance
- No formal CLI API boundary
- Code re-use temptation: "SnapshotStore already has `load_snapshot`, just call it"

**Consequences:** Internal refactors randomly break CLI. CLI users bypass security checks (signing_secret validation, budget enforcement). CLI and library must be versioned in lockstep.

**Prevention:**
- **Define a `relay.cli.api` module with stable read-only operations:** `get_snapshot(pipeline_id, step)`, `diff_snapshots(from_step, to_step)`, `list_snapshots(pipeline_id)`.
- This module is part of the **public CLI contract** — versioned separately from internal APIs.
- Internals (`SnapshotStore`, `RollbackHandler`, `ContextEnvelope`) are NOT imported by CLI code directly.
- For `relay rollback`: CLI calls `CoreRelayPipeline.create().rollback()` — NOT `RollbackHandler.restore_to_previous()`.
- Consider: make CLI a separate install extra (`relay[cli]`) to force clean API boundary.

**Detection:** Code review: flag any CLI code importing from `relay.pipeline_rollback`, `relay.snapshot`, `relay.envelope` directly (except the stable CLI API module).

**Phase:** v0.5 (CLI feature)

---

### PITFALL-6: `relay rollback` CLI command is a security backdoor

**What goes wrong:** The CLI `relay rollback` bypasses signature verification (CONCERNS.md CRIT-02: `load_snapshot()` never calls `verify_signature()`). An attacker with filesystem access can inject a fabricated snapshot and run `relay rollback` to load attacker-controlled data into the pipeline.

**Why it happens:**
- CRIT-02 already identified: `SnapshotStore.load_snapshot()` deserializes JSON without signature check
- CLI trusts filesystem because "it's on the same machine"
- Rollback is inherently powerful — no additional authentication in the CLI path

**Additional risks:**
- No `--confirm` prompt before destructive rollback
- No audit trail for CLI rollbacks (bypasses pipeline audit events)
- Any user who can run the CLI can rollback any pipeline

**Prevention:**
- **Fix CRIT-02 first** — add signature verification to all snapshot load paths. This is foundational.
- Add mandatory `verify_signature()` call in the CLI rollback path.
- Require `--confirm` or interactive `y/N` before executing rollback.
- Add a separate audit event for CLI-initiated rollbacks.
- Consider: CLI requires the signing secret to authorize rollback: `relay rollback --signing-secret <secret>`.
- The rollback CLI command must NOT succeed unless `_TARGET.signing_secret` is provided and envelope signatures verify.

**Detection:** Check CONCERNS.md CRIT-02 status. If unfixed, CLI rollback is inherently unsafe. Integration test: inject tampered snapshot, verify `relay rollback` fails with signature error.

**Phase:** v0.5 (CLI feature), requires v1.0 security hardening (CRIT-02 fix) to be safe

---

### PITFALL-7: pytest plugin fixture isolation failure — tests pollute each other

**What goes wrong:** The `relay_pipeline` fixture, if scoped `module` or `session` for performance, causes tests to share `PipelineState` and in-memory `SnapshotStore`. One test writes a snapshot that another test reads. Budget state, step counters, or signed envelopes leak between tests.

**Why it happens:**
- Natural optimization: "create pipeline once per module to save time"
- `PipelineState` is a mutable singleton-like object — sharing it is state corruption
- In-memory `SnapshotStore` stores envelopes in a shared dict
- pytest-xdist parallel execution magnifies the problem

**Real-world evidence:**
- Pytest session-scoped parametrized fixtures are re-initialized unexpectedly — calling `heavy_fixture` multiple times for the same params due to test ordering algorithm (pytest#13755, HIGH confidence).
- Global mutable state in test modules causes ordering-dependent failures — tests pass in isolation, fail in suite (StackOverflow, HIGH confidence).

**Prevention:**
- **Default `relay_pipeline` to `function` scope.** Users who need wider scope explicitly opt in.
- Each fixture call creates FRESH `PipelineState`, `SnapshotStore`, and `CoreRelayPipeline`.
- Use `tmp_path` fixture for filesystem storage — each test gets its own directory.
- Provide a `TmpSnapshotStore` test double (stores in `dict[str, dict]` keyed by `pipeline_id + step`).
- For wider scope: provide `relay_pipeline_session` using `tmp_path_factory`, documented as "tests MUST NOT share pipeline_ids."
- Run `pytest --random-order` in CI to expose ordering dependencies.

**Phase:** v0.5 (pytest plugin)

---

### PITFALL-8: pytest plugin slows test collection due to heavy imports

**What goes wrong:** The plugin's conftest imports `CoreRelayPipeline`, `SnapshotStore` at module level. pytest auto-loads all installed plugins during collection — even for tests that don't use Relay. A suite with 1000 tests where 10 use Relay pays the full import cost for all 1000.

**Why it happens:**
- pytest auto-discovers and loads all installed plugins at session start
- Plugin's `conftest.py` or `__init__.py` eagerly imports Relay at module level
- Heavy optional deps (tiktoken, httpx) imported during collection if not lazy-loaded

**Real-world evidence:**
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD` reduces pytest startup ~40% by preventing auto-load of unused plugins (Giampaolo Rodolà, HIGH confidence).
- pytest-asyncio's `iscoroutinefunction` check on every fixture caused 2.5 min collection overhead for large suites (pytest-asyncio#720, HIGH confidence).
- Heavy libraries imported at collection time cause 4-10× startup delay vs test runners that don't import test files (pytest#12722, HIGH confidence).

**Prevention:**
- **Deferred imports in the plugin.** All Relay-specific imports inside fixture factory functions:
  ```python
  @pytest.fixture
  def relay_pipeline():
      from relay import CoreRelayPipeline  # imported only when fixture is used
      ...
  ```
- Plugin entry point (`pytest11` or `entry_points`) only registers hooks, never imports Relay.
- Consider: ship plugin as separate `relay-pytest` package with its own `pyproject.toml`. Users who don't need it don't install it.
- Use `importlib.import_module()` lazily for all Relay modules in plugin code.
- Measure: `time pytest --collect-only` with and without the plugin.

**Phase:** v0.5 (pytest plugin)

---

### PITFALL-9: Async/sync mismatch in pluggable backends — event loop cross-contamination

**What goes wrong:** `SnapshotStore` is currently synchronous. Redis/Postgres/S3 backends require async I/O (native async clients). If the interface stays synchronous but backends use `asyncio.run()` internally, event loop mismatch causes `RuntimeError: Task got Future attached to a different loop`, connection pool deadlocks, and thread-safety violations.

**Why it happens:**
- Existing `SnapshotStore` interface is synchronous (returns `None`, not coroutines)
- Async backends need an event loop but the caller may already be running one
- `asyncio.run()` cannot nest inside another running loop
- `asyncio.to_thread()` bridge creates new threads with new event loops, breaking connection pooling

**Real-world incidents:**
- psycopg3 `AsyncConnectionPool` hangs when opened on loop A but used on loop B — `asyncio.Queue` is loop-bound (psycopg/psycopg#737, HIGH confidence).
- s3fs throws `RuntimeError: Task got Future attached to a different loop` when mixing sync/async calls — `aiohttp.TCPConnector` bound to creation loop (fsspec/s3fs#842, HIGH confidence).
- redis-py Sentinel used sync `SentinelConnectionPool` for async clients — missing `aconnect()`, runtime failures (redis/redis-vl-python#465, HIGH confidence).
- asyncpg-based repository failed from sync context: `InterfaceError: another operation is in progress` (nlp2sql#35, HIGH confidence).

**Consequences:** Complete failure of Redis/Postgres/S3 backends in async pipeline contexts. Intermittent failures dependent on event loop state. Connection pool corruption under concurrent load.

**Prevention:**
- **Make `SnapshotStore` an async Protocol from day one:** `async def save(...)`, `async def load(...)`, `async def list(...)`, `async def delete(...)`.
- Each backend owns its event loop strategy:
  - `RedisStore`: uses `redis.asyncio` natively
  - `PostgresStore`: uses `asyncpg` — open connection on caller's loop
  - `S3Store`: uses `aiobotocore` or s3fs with `asynchronous=True`
  - `LocalFileStore`: sync I/O wrapped in `asyncio.to_thread()`
- Add `async def ping() -> bool` for health checks.
- The Protocol must use `AsyncContextManager` for connection lifecycle.
- Do NOT provide a sync-only interface and force async backends to bridge.

**Phase:** v0.6 (pluggable backends)

---

### PITFALL-10: Pluggable backends have different atomicity and transaction guarantees

**What goes wrong:** Local filesystem uses `os.replace()` for atomic writes. Redis has `HSET` but no native compare-and-swap for the index. S3's `PutObject` is eventually consistent. Postgres has full transactions. If the abstraction doesn't account for these differences, data corruption occurs silently.

**Why it happens:**
- `SnapshotStore` interface assumes atomic save + atomic index update
- `_add_to_index()` has a TOCTOU race (CONCERNS.md) — benign on local filesystem, catastrophic on distributed backends
- Backend consistency models differ radically:
  - Local file: `os.replace()` is atomic per write; index has TOCTOU
  - Redis: `HSET` + `SADD` atomic per command, no multi-key transaction without `WATCH`
  - S3: `PutObject` atomic but read-after-write not guaranteed for all regions
  - Postgres: fully transactional via `BEGIN`/`COMMIT`

**Consequences:** Snapshot index corruption — pipeline state desyncs from stored snapshots. Lost snapshots under concurrent access. Inability to roll back to specific step.

**Prevention:**
- **Define `ConsistencyLevel` enum for backends:**
  - `ATOMIC_SAVE_AND_INDEX` — Postgres (transaction wraps save + index update)
  - `ATOMIC_SAVE_ONLY` — Local file (save is atomic, index has TOCTOU)
  - `COMMAND_ATOMIC` — Redis (each command atomic, no cross-command tx without WATCH)
  - `EVENTUAL_SAVE` — S3 (save may not immediately visible)
- Pipeline adapts behavior based on backend consistency:
  - `ATOMIC_SAVE_AND_INDEX`: single transaction for save + index update
  - Lower levels: add retry logic, read-after-write delays, or documented limitations
- Implement WAL pattern for non-atomic backends: write snapshot → write commit marker → on recovery, reconcile.
- For S3: use `PutObject` with `If-None-Match`, `GetObject` with `If-Match`.
- For Redis: use `WATCH`/`MULTI`/`EXEC` around index read-modify-write, or a Lua script.

**Phase:** v0.6 (pluggable backends)

---

### PITFALL-11: Connection pool leak or exhaustion in Redis/Postgres backends

**What goes wrong:** Each `CoreRelayPipeline` instance creates its own connection pool. Users creating one pipeline per web request accumulate pools and exhaust database connections. Conversely, a single global pool creates cross-tenant state leakage.

**Why it happens:**
- Natural design: "create pool when backend is constructed"
- No lifecycle management — pipelines GC'd but connection pools are not closed
- Web frameworks create pipeline per request — each gets its own pool

**Consequences:** Redis `maxclients` reached. Postgres `max_connections` exhausted. Resource exhaustion under load.

**Prevention:**
- **Connection pool registry** (like `oj-persistence`'s `_BackendRegistry`): deduplicate by connection string. Two `RedisStore(url="redis://...")` instances share one pool.
- Add `async def close() -> None` to backend Protocol. `CoreRelayPipeline.__aexit__` calls `backend.close()`.
- Provide `create_pipeline()` factory managing lifecycle: create → use → close.
- Document: one pipeline instance per process, not per request.
- Provide FastAPI/Django lifespan integration example.

**Phase:** v0.6 (pluggable backends)

---

### PITFALL-12: Rolling signing keys invalidates existing snapshots

**What goes wrong:** Rotating the signing secret invalidates all existing envelope signatures. `verify_signature()` with the new key fails on all historical snapshots — breaking rollback, CLI inspection, and any operation loading old envelopes.

**Why it happens:**
- `ContextEnvelope` has no `key_id` field — implicit single key
- `verify_signature()` uses current secret — old secrets discarded
- No key history log (CONCERNS.md HIGH-04)
- Natural rotation: "change secret and redeploy" — immediately breaks everything

**Consequences:** All historical snapshots unverifiable after key rotation. Rollback to pre-rotation snapshots fails. Users choose between "keep old key forever" or "lose history."

**Prevention:**
- **Add `key_id: str` to `ContextEnvelope`** (proposed in HIGH-04).
- Introduce `SigningKey` data class: `key_id: str; secret: str; created_at: datetime`.
- `ContextBroker` holds `keys: dict[str, SigningKey]` — key history.
- `verify_signature()` looks up key by `envelope.key_id`.
- **Dual signing rotation window:**
  1. Add new key as "active" for signing, keep old key as "accepted" for verification
  2. Grace period: new envelopes signed with new key, old envelopes verify with old key
  3. After period expires, decommission old key only when confident no valuable snapshots exist under it
- Document: "Key rotation is coordinated. Old-keys-in-history = old-snapshots-verifiable. Purging a key permanently invalidates its snapshots."

**Phase:** v1.0 (security hardening)

---

### PITFALL-13: API stability promise made too early — prevents refactoring

**What goes wrong:** v1.0 declares the public API stable. But the exported surface includes `ContextEnvelope`, `create_next_envelope()`, `SnapshotStore`, `estimate_tokens()` — internals that need refactoring for pluggable backends (v0.6) and security (v1.0). Every refactor becomes a breaking change.

**Why it happens:**
- Desire to signal maturity overrides careful API surface analysis
- Python `__all__` in `__init__.py` easily exports too much
- Users start depending on things they shouldn't ("inner platform" anti-pattern)

**Real-world incidents:**
- PyJWT CVE-2025-45768: minimum key length enforcement was a breaking change — had to add configurable enforcement with deprecation warnings (jpadilla/pyjwt#1085, HIGH confidence).
- CPython PGP→Sigstore transition: maintaining both signatures concurrently created "Gordian knot" — verifiers wouldn't migrate (PEP 761, HIGH confidence).

**Prevention:**
- **Define public API surface explicitly BEFORE v1.0.** Document exactly what is exported.
- **Stable API only:**
  - `CoreRelayPipeline.create()` / `execute_step()` / `execute_parallel_step()` / `rollback()`
  - `AgentManifest`, `ForkSpec`, `JoinStrategy` (configuration types)
  - `AgentRunner` Protocol (for adapter implementers)
  - pytest plugin fixtures
  - CLI entry points
- **Internal / subject to change:**
  - `ContextEnvelope`, `SnapshotStore`, `RollbackHandler`, `HandoffValidator`
  - `create_next_envelope()`, `estimate_tokens()`, `compute_signature()`
  - All `_`-prefixed functions
- Use `__all__` only for stable API. Internal modules in `_internal/` subpackage.
- CI test: `import relay; assert set(dir(relay)) == set(STABLE_API_NAMES)`.

**Phase:** v0.5 (pre-stability audit), enforced at v1.0

---

## Moderate Pitfalls

### PITFALL-14: Performance regression from additional validation in audit/OTEL paths

**What goes wrong:** Audit events compute diff summaries, format latency strings, allocate dicts for OTEL attributes — even when the event is below configured log level. In hot paths (adapter `run()`), microsecond overhead accumulates.

**Why it happens:**
- f-strings in logging evaluate eagerly: `logger.debug(f"payload: {expensive()}")` — `expensive()` runs even if debug disabled
- OTEL span creation always allocates, even if span never exported
- Diff computation runs before checking if event level is enabled

**Prevention:**
- Use `%s`-style lazy format strings in logging: `logger.debug("payload: %s", json.dumps(payload))` — Python logging only formats at/above level. The f-string variant `logger.debug(f"payload: {json.dumps(payload)}")` evaluates eagerly — BAN f-strings in logging.
- Guard expensive ops: `if logger.isEnabledFor(logging.DEBUG): expensive_call()`.
- OTEL: wrap span creation in no-op guard: `if _tracer and _tracer.is_enabled(): with _tracer.start_as_current_span(...)`.
- Performance benchmark: measure overhead per step (baseline, audit WARNING, audit+OTEL 10%, audit+OTEL 100%).
- Budget: total observability overhead <10ms per step.

**Phase:** v0.5 (observability)

---

### PITFALL-15: Optional dependency management — broken imports, accidental mandatory deps

**What goes wrong:** If new optional dependencies (`opentelemetry-api`, `redis`, `asyncpg`, `boto3`) are imported at module level anywhere, installing base `relay` fails. Naive `try/except ImportError` eats errors but sets `None`, causing `AttributeError: 'NoneType' object has no attribute 'X'` on first use.

**Why it happens:**
- Module-level imports of optional deps cause unconditional failure
- `try/except ImportError: dep = None` pattern causes confusing runtime errors
- Entry points referencing optional code break on minimal installs
- setuptools extras can't be checked programmatically from entry points

**Real-world incidents:**
- pymap#159: optional dependencies became mandatory because entry points couldn't declare extras — `from redis.asyncio import Redis` at module level crashed on minimal install (HIGH confidence).

**Prevention:**
- **Replicate the existing lazy-import pattern from `runners/__init__.py`** for ALL optional features:
  ```python
  # relay/__init__.py
  _LAZY_MODULES = {"otel": "relay.observability._otel"}
  def __getattr__(name):
      if name in _LAZY_MODULES:
          return importlib.import_module(_LAZY_MODULES[name])
      raise AttributeError(...)
  ```
- For backend extras: each store imports its dependency only in `connect()` or `__init__`.
- Add an `_optional_dependency(name, extra)` utility:
  ```python
  def _check_dep(name, extra):
      try:
          return importlib.import_module(name)
      except ImportError:
          raise ImportError(f"Install: pip install relay[{extra}]") from None
  ```
- CI matrix: test base install (no extras) + each extra individually. Verify clear error messages.

**Phase:** v0.5 (OTEL extra), v0.6 (backends extra)

---

### PITFALL-16: Export surface accidentally expands through `__all__` and `__init__.py`

**What goes wrong:** Developers add new exports to `relay/__init__.py` `__all__` without considering whether they should be public. Over time, `__all__` grows from 18 names (current) to 50+ — including internal helpers, experimental backends, and types not ready for stable API commitment.

**Prevention:**
- **API review gate in the development process.** Every addition to `__all__` requires justification.
- Categorize exports:
  - `STABLE_API`: semver-governed (breaking = major version bump)
  - `EXPERIMENTAL`: may change without major version (new backends, adapters)
  - `INTERNAL`: explicitly private, can change at any time
- `__all__` only for `STABLE_API`. Experimental in `relay.experimental.*`.
- Use `@typing.final` on classes that should not be subclassed.
- CI check: compare `__all__` against baseline. New exports trigger review comment.

**Phase:** v0.5 (ongoing), enforced at v1.0

---

### PITFALL-17: Import time increases from new dependencies block CI and CLI startup

**What goes wrong:** Even optional dependencies increase baseline import time if `__init__.py` imports too many submodules eagerly. `import relay` can become >100ms, slowing CLI startup, CI runs, and developer workflows.

**Real-world evidence:**
- PEP 810 (lazy imports, Python 3.15) reports 50-80% startup improvement for CLI tools. Scientific Python's `lazy_loader` addresses this exact problem (HIGH confidence).
- pluggy: import time dropped from 0.69s to 0.004s by deferring stdlib imports (pytest-dev/pluggy#445, HIGH confidence).

**Prevention:**
- **Keep `relay/__init__.py` minimal.** Import only core types (`Result`, `Success`, `Failure`, `CoreRelayPipeline`).
- Use `__getattr__` at module level for submodules (already in `runners/__init__`, replicate everywhere).
- CLI entry point imports `relay.cli` (minimal imports), NOT `import relay`.
- Pytest plugin: no `import relay` at module level — only inside fixtures.
- Consider `lazy_loader` (scientific-python/lazy-loader) for deferred subpackage imports.
- **Set performance budget: `import relay` <50ms.** CI gate measures this.

**Phase:** v0.5 (ongoing), validated before v1.0

---

### PITFALL-18: pytest plugin conftest has import-time side effects

**What goes wrong:** If the plugin's conftest executes I/O, connects to databases, or modifies global state at module level, side effects happen during test collection — before any test runs. This can start HTTP servers, create files, or crash collection entirely.

**Real-world incidents:**
- Project with `from src.server import API; API.start()` at module level started an HTTP server during collection — port conflicts when running full suite (Medium article, HIGH confidence).
- Lazy-loading `from arcgis import GIS` (moving into a function) fixed 20-second collection stalls (pytest#12722, HIGH confidence).

**Prevention:**
- **Zero side effects at import time.** Plugin's conftest only registers hook implementations (functions), never executes them.
- No `SnapshotStore` construction at module level. No `CoreRelayPipeline` construction. No filesystem access.
- All state creation inside `@pytest.fixture(scope="function")` factories.
- Static analysis: flag any conftest code doing I/O at module level.

**Phase:** v0.5 (pytest plugin)

---

### PITFALL-19: CLI output format changes break automated consumption

**What goes wrong:** `relay inspect` outputs JSON. As snapshot schema evolves (adding `key_id`, `nonce`, etc.), output format changes. Users piping into `jq` or scripts break silently.

**Prevention:**
- Schema-formatted JSON output: define `RelayCLISnapshot` type that maps internal fields.
- `--format json` (default, machine-readable) vs `--format pretty` (human-readable).
- Document CLI output schema as part of public API.
- Versioned output: `--output-version 1` for stable machine-readable format.

**Phase:** v0.5 (CLI)

---

### PITFALL-20: Postgres/Redis schema migration when envelope schema changes

**What goes wrong:** Postgres stores snapshots as JSONB. When `ContextEnvelope` adds new fields, existing rows have missing keys. If deserialization code uses `@dataclass` with required fields, loading old snapshots fails with `TypeError`.

**Prevention:**
- Include `snapshot_schema_version: int` in stored records.
- `load()` calls `migrate_v1_to_v2(raw: dict) -> dict` before constructing `ContextEnvelope`.
- `ContextEnvelope.from_dict()` uses `.get()` with defaults for optional fields.
- Backwards compatibility test: create snapshots with v1 schema, load with v2 code.

**Phase:** v0.6 (backends)

---

### PITFALL-21: No snapshot cleanup leads to unbounded storage growth

**What goes wrong:** Missing `delete_snapshot()` / `purge_before()` APIs (CONCERNS.md). Pipeline with 1000 steps × frequent rollbacks = unbounded disk growth. Redis with TTL mitigates this, but Postgres/S3 have no auto-expiry.

**Prevention:**
- Add `delete_snapshot(pipeline_id, step)` and `purge_before(pipeline_id, step)` to backend Protocol.
- `SnapshotRetention` parameter: `KeepAll`, `KeepLastN(n)`, `KeepByAge(timedelta)`.
- Background compaction or compaction on pipeline close.
- TTL support for Redis backend (native Redis TTL).

**Phase:** v0.6 (backends)

---

### PITFALL-22: `relay diff` output is semantically meaningless noise

**What goes wrong:** Raw JSON diff between snapshots shows key ordering changes, whitespace differences, timestamp fields, non-deterministic token counts — not what changed meaningfully in agent outputs.

**Prevention:**
- Normalize before diffing: sort keys, strip whitespace, ignore `timestamp`, `latency_ms`.
- Highlight fields changed in `manifest.writes` vs fields changed outside (contradiction signal).
- Structured field-level diff, not raw JSON characters.
- Optional: use `deepdiff` library (optional dep) for semantic diffing.

**Phase:** v0.5 (CLI)

---

### PITFALL-23: OTEL `service.name` not configured — traces show "unknown_service"

**Prevention:** In OTEL setup guide, explicitly document setting `OTEL_SERVICE_NAME` or `Resource(service.name=...)`. Add warning if `service.name` is default.

**Phase:** v0.5

---

### PITFALL-24: PyPI naming collision for pytest plugin

**Prevention:** Check if `pytest-relay` exists before releasing. Use `relay-pytest` and register `pytest11` entry point with unique name.

**Phase:** v0.5

---

### PITFALL-25: S3 backend costs from excessive ListObjects calls

**Prevention:** Cache snapshot listing in memory with TTL. Use `ListObjectsV2` with pagination. `load_snapshot` by step ID uses direct `GetObject` by key, not list+filter.

**Phase:** v0.6

---

## Phase-Specific Warning Table

| Phase | Topic | Top Pitfall | Mitigation |
|-------|-------|-------------|------------|
| v0.5 | Audit log | PITFALL-1: Payload secrets leaked | Redact payloads by default; log only metadata |
| v0.5 | Audit log | PITFALL-2: Volume explosion | Three-tier severity (AUDIT/INFO/TRACE); rate limiting |
| v0.5 | OTEL | PITFALL-3: Span overhead | Span budget; 10% default sampling; guard with is_enabled() |
| v0.5 | OTEL | PITFALL-4: Thread context loss | Wrap adapter run in outer span; explicit context passing |
| v0.5 | OTEL | PITFALL-14: Perf regression | Lazy format strings (%s not f-strings); guard expensive ops |
| v0.5 | CLI | PITFALL-5: Internal API coupling | Stable CLI API module; no direct internal imports |
| v0.5 | CLI | PITFALL-6: Rollback backdoor | Fix CRIT-02 first; require signing secret for rollback |
| v0.5 | CLI | PITFALL-19: Output format instability | Versioned JSON output schema |
| v0.5 | CLI | PITFALL-22: Meaningless diffs | Normalize before diff; focus on manifest writes |
| v0.5 | pytest | PITFALL-7: Fixture pollution | function-scoped fixtures; fresh state per test |
| v0.5 | pytest | PITFALL-8: Slow collection | Deferred imports; separate package if needed |
| v0.5 | pytest | PITFALL-18: Import-time side effects | Zero I/O at import time |
| v0.5 | General | PITFALL-15: Optional deps broken | Lazy import pattern (like runners/) everywhere |
| v0.5 | General | PITFALL-16: Export bloat | API review gate; categorize STABLE/EXPERIMENTAL |
| v0.5 | General | PITFALL-17: Import time creep | Budget <50ms; CI gate; minimal __init__.py |
| v0.5 | General | PITFALL-13: Premature API promise | Define public API surface before v1.0 |
| v0.6 | Backends | PITFALL-9: Async/sync mismatch | Async Protocol from day one |
| v0.6 | Backends | PITFALL-10: Consistency mismatch | ConsistencyLevel enum; adaptive pipeline |
| v0.6 | Backends | PITFALL-11: Pool leaks | Pool registry; close() lifecycle |
| v0.6 | Backends | PITFALL-20: Schema migration | Versioned snapshots; migration functions |
| v0.6 | Backends | PITFALL-21: No cleanup | Retention policy; delete API |
| v1.0 | Security | PITFALL-12: Key rotation breaks snapshots | key_id field; key history; dual signing window |
| v1.0 | API | PITFALL-13: API stability | Stabilize only public API; internals stay private |

---

## Sources

- open-telemetry/opentelemetry-python#3474 — CPU overhead from always_on sampler (HIGH)
- open-telemetry/opentelemetry.io — OTEL troubleshooting (fork/deadlock issues) (HIGH)
- OneUptime OTEL benchmarking — span creation costs by language (MEDIUM)
- supabase/supabase-py#1025 — sensitive data in debug logs (HIGH)
- intelowlproject/IntelOwl#3465 — API key leakage in debug logs (HIGH)
- paperclipai/paperclip#4759 — plaintext passwords in log output (HIGH)
- getsentry/sentry-python#2417 — repr() leaks auth tokens in exception logs (HIGH)
- psycopg/psycopg#737 — async pool event loop mismatch hang (HIGH)
- fsspec/s3fs#842 — sync/async mixed event loop error on S3 filesystem (HIGH)
- redis/redis-vl-python#465 — sync pool for async Redis Sentinel connections (HIGH)
- nlp2sql#35 — asyncpg breaks from sync context (HIGH)
- pytest-dev/pytest#12722 — slow collection from expensive imports (HIGH)
- pytest-dev/pytest-asyncio#720 — iscoroutinefunction overhead in collection (HIGH)
- pytest-dev/pytest#13755 — session-scoped fixture re-initialization (HIGH)
- pytest-dev/pluggy#445 — lazy import optimization, 0.69s→0.004s (HIGH)
- Giampaolo Rodolà — pytest startup optimization via PYTEST_DISABLE_PLUGIN_AUTOLOAD (HIGH)
- jpadilla/pyjwt#1085 — breaking change from key length enforcement (HIGH)
- icgood/pymap#159 — optional deps became mandatory via entry points (HIGH)
- PEP 761 — CPython PGP→Sigstore transition complexity (MEDIUM)
- PEP 810 — Python 3.15 lazy imports, 50-80% CLI startup improvement (HIGH)
- scientific-python/lazy-loader — library for deferred subpackage imports (HIGH)
- AuditBuffet pattern catalog — secrets in logs compliance guidance (MEDIUM)
- OneUptime — OTEL context propagation with baggage across async boundaries (MEDIUM)
- `oj-persistence` — pluggable backends with capability system and pool registry (MEDIUM)
- Relay CONCERNS.md — CRIT-02, HIGH-04, W1, BUG-02 (HIGH)
- Relay Design Document — architecture constraints, phase roadmap (HIGH)
