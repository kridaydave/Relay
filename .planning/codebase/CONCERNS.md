# Codebase Concerns

**Analysis Date:** 2026-05-17

## Tech Debt

### CRIT-01: No replay attack protection on envelope signatures

- **Issue:** Envelopes carry `step` and `timestamp` fields, but `verify_signature()` at `src/relay/envelope.py:160-183` only checks HMAC integrity — no nonce, no TTL/max-age check, no monotonic sequence counter. A captured signed envelope can be replayed indefinitely.
- **Files:** `src/relay/envelope.py:137-183`, `src/relay/snapshot.py:130-156`, `src/relay/pipeline_rollback.py:19-48`
- **Impact:** CRITICAL. An attacker with filesystem access to snapshots can replay or reorder envelopes. No mechanism to detect or reject duplicates.
- **Fix approach:** Add a `nonce` field and monotonic `sequence_number` to `ContextEnvelope`. Extend `verify_signature` to accept a `seen_nonces: set[str] | None` parameter and reject duplicates. Add `max_age_seconds` parameter to verify_signature with sensible default.
- **Severity:** CRITICAL

### CRIT-02: No signature verification on snapshot load

- **Issue:** `SnapshotStore.load_snapshot()` at `src/relay/snapshot.py:130-176` reads JSON from disk and deserialises to `ContextEnvelope` but **never calls `verify_signature()`**. The HMAC signature is deserialised from JSON as a string but never validated against the envelope contents. An attacker with write access to the snapshot store can inject arbitrarily fabricated envelopes.
- **Files:** `src/relay/snapshot.py:130-176`, `src/relay/pipeline_rollback.py:19-48`, `src/relay/core_pipeline.py:360-392`
- **Impact:** CRITICAL. Snapshot store integrity is entirely trust-on-first-read. Rollback from a compromised snapshot store returns attacker-controlled data.
- **Fix approach:** Add signature verification in `_dict_to_envelope()` (accept optional `secret` parameter). Or add a `SnapshotStore.verify_integrity()` method called by `RollbackHandler.restore_to_previous()`. At minimum: log warning on invalid signature.
- **Severity:** CRITICAL

### CRIT-03: Signing secret stored as plain Python `str` with no memory protection

- **Issue:** The HMAC signing secret is stored as a regular `str` in `ContextBroker.signing_secret` (`src/relay/context_broker.py:59`) and `CoreRelayPipeline.signing_secret` (`src/relay/core_pipeline.py:55`). Python strings are immutable, unzeroizable, and remain in memory until garbage collection. The secret is visible in `repr()` output, accessible via attribute traversal, and present in memory/core dumps.
- **Files:** `src/relay/context_broker.py:48-60`, `src/relay/core_pipeline.py:48-69`
- **Impact:** CRITICAL. Any process with debugger access or core dump analysis can extract the signing secret, which would allow forging arbitrary envelope signatures.
- **Fix approach:** Use `@dataclass(frozen=True, repr=False)` on `ContextBroker`. Add `__repr__`/`__str__` redaction. Consider a dedicated `SigningKey` wrapper class. At minimum: exclude from `__repr__` via field-level `repr=False`.
- **Severity:** CRITICAL

### HIGH-01: Budget enforcement checks input slice cost against token budget, but accounting tracks only output size

- **Issue:** `_check_budget()` in `src/relay/core_pipeline.py:237-286` and `HardCapEnforcer.check()` in `src/relay/budget/enforcer.py:23-41` use the *input* slice (what the agent reads) as the projected cost. But `token_budget_used` in every envelope accumulates only *output* sizes (via `estimate_tokens(agent_output)` in `create_next_envelope` at `src/relay/envelope.py:250`). These are different quantities that can diverge arbitrarily. An agent reading 30 tokens of input but producing 200 tokens of output silently exceeds the budget.
- **Files:** `src/relay/core_pipeline.py:237-286`, `src/relay/budget/enforcer.py:23-41`, `src/relay/envelope.py:227-265`
- **Impact:** HIGH. Budget enforcement is structurally incorrect — it measures the wrong quantity. Undermines the hard-cap guarantee from the design document.
- **Fix approach:** Change `_check_budget` to project output size based on `manifest.writes` (what the agent is expected to produce) rather than the input context it reads.
- **Severity:** HIGH

### HIGH-02: Budget enforcement is advisory under concurrent load (documented but problematic)

- **Issue:** In `execute_step_with_runner()` (`src/relay/core_pipeline.py:429-487`), the lock is released before `adapter.run()` (to avoid holding it during I/O). Another thread can advance the envelope between the budget check and execution. The docstring acknowledges this: "Note on concurrent budget enforcement: The budget check at step 3 is advisory under concurrent load." Combined with HIGH-01, budget enforcement has two independent correctness gaps.
- **Files:** `src/relay/core_pipeline.py:429-487`
- **Impact:** MEDIUM. Under concurrent access, budget limits can be exceeded without detection until post-hoc validation (which also uses the wrong metric).
- **Fix approach:** Either document as accepted risk more prominently, or implement a two-phase budget reservation system.
- **Severity:** MEDIUM

### HIGH-03: `CoreRelayPipeline.__post_init__` raises `ValueError` instead of returning `Failure`

- **Issue:** The factory method `CoreRelayPipeline.create()` returns `Result[CoreRelayPipeline]` and correctly propagates `Failure`. But `__post_init__()` (`src/relay/core_pipeline.py:105-117`) raises `ValueError` on validation failure. This creates two different error contracts for the same class. Direct construction (`CoreRelayPipeline(signing_secret="short")`) crashes instead of returning `Failure`.
- **Files:** `src/relay/core_pipeline.py:105-117`
- **Impact:** HIGH. Breaches the `Result`-type error handling pattern used everywhere else. Direct construction bypasses the factory and raises exceptions.
- **Fix approach:** Remove validation from `__post_init__()` entirely and trust the factory or caller, keeping the separate `create()` factory as the validated entry point.
- **Severity:** HIGH

### HIGH-04: No secret rotation mechanism

- **Issue:** Zero infrastructure for key rotation. No `key_id` field in `ContextEnvelope` (`src/relay/envelope.py:48-77`), no key history log, no support for multiple active keys. If the signing secret is compromised, all existing envelope signatures are trivially forgeable and rotating the secret invalidates ALL existing snapshots.
- **Files:** `src/relay/envelope.py:137-159`, `src/relay/context_broker.py:59`
- **Impact:** HIGH. Compromise of the single signing secret is unrecoverable without invalidating all stored data.
- **Fix approach:** Add `key_id: str` to `ContextEnvelope`. Introduce `SigningKey` data class with `id`, `secret`, `created_at`. Change `ContextBroker` to hold a `dict[str, SigningKey]` (key history).
- **Severity:** HIGH

### W1: Orphaned snapshot files on contradiction rollback

- **Issue:** In `_finalize_step()` (`src/relay/core_pipeline.py:288-324`), when a contradiction is detected at line 309, `current_envelope` is saved as a new snapshot before being pushed to history. This creates a second snapshot file for the same step. The previous snapshot file (from the original commit) becomes orphaned on disk — it exists but is no longer referenced by the index. Repeated rollbacks accumulate garbage.
- **Files:** `src/relay/core_pipeline.py:288-324`
- **Impact:** LOW-MEDIUM. No data loss or correctness issue, but unbounded disk waste in pipelines with frequent rollbacks. Should be prioritized before v1.0.
- **Fix approach:** Skip the redundant `save_snapshot` on rollback — the envelope was already snapshotted when committed. The current code (line 311-316) already has this partially addressed: it registers the new snapshot but the old file remains.
- **Severity:** MEDIUM

### W2: Redundant `create_context_broker()` call in factory

- **Issue:** `create()` factory at `src/relay/core_pipeline.py:74-103` creates a `ContextBroker` for secret validation, then discards it. `__post_init__()` at line 108 creates another one. Both calls validate the same secret. Unnecessary `ContextBroker` construction on every pipeline creation.
- **Files:** `src/relay/core_pipeline.py:74-117`
- **Impact:** LOW. Negligible performance impact (single object allocation), but redundant code that could confuse maintainers.
- **Fix approach:** Eliminate the redundant construction by passing the validated broker from `create()` to `__post_init__()` or by making the broker lazily constructed.
- **Severity:** LOW

### W3: `_finalize_step` and internal methods lack `_assert_lock_held()` enforcement

- **Issue:** `_finalize_step()` (`src/relay/core_pipeline.py:288-324`) documents "REQUIRES: caller holds self._state._lock via transaction() context manager" but never calls `_assert_lock_held()`. Same for `_check_budget`, `_apply_manifest`, `_slice_payload`, and `_do_rollback`. If future refactoring calls these methods outside a transaction, state corruption occurs silently.
- **Files:** `src/relay/core_pipeline.py:237-392`, `src/relay/pipeline_state.py:47-51`
- **Impact:** LOW (currently correct, fragile to future change).
- **Fix approach:** Add `self._state._assert_lock_held()` calls to all internal methods that document lock-required preconditions. `_finalize_step` should be the top priority since it directly mutates state.
- **Severity:** LOW

### W4: Dataset-creation `.pyc` files committed to git

- **Issue:** `__pycache__/` directories and `.pyc` files exist throughout `src/relay/` and `tests/`. While these may be untracked, their presence indicates the codebase runs Python compilation alongside version control. This is a hygiene concern.
- **Files:** `src/relay/**/__pycache__/*.pyc`, `tests/**/__pycache__/*.pyc`
- **Impact:** INFO. No direct bug, but indicates missing `.gitignore` entries or unclean build artifacts.
- **Fix approach:** Ensure `__pycache__/` is in `.gitignore`. Add a `git clean` step to build scripts.
- **Severity:** INFO

### W5: Typo in function name — `_combine` instead of `_combine`

- **Issue:** Helper function at `src/relay/core_pipeline.py:37` is named `_combine_manifest_hashes` — should be `_combine_manifest_hashes` (note: "combine" vs "combine"). This is a pre-existing naming issue that doesn't affect functionality but reduces readability.
- **Files:** `src/relay/core_pipeline.py:37-44`
- **Impact:** INFO. Cosmetic.
- **Fix approach:** Rename to `_combine_manifest_hashes` and update all call sites.
- **Severity:** INFO

### W6: `persist` typo in `snapshot.py` docstring

- **Issue:** Module docstring reads "persistence" instead of "persistence" (`src/relay/snapshot.py:2`).
- **Files:** `src/relay/snapshot.py:2`
- **Impact:** INFO. Cosmetic.
- **Severity:** INFO

## Known Bugs

### BUG-01: `text` key collision in `agent_output_to_payload()`

- **Symptoms:** `agent_output_to_payload()` at `src/relay/parallel/types.py:62-72` calls `raw["text"] = output.text` after `raw: JSONDict = dict(output.structured)`. If `output.structured` already contains a `"text"` key, it is silently overwritten by `output.text`. The docstring says "`output.text` always takes precedence" which is intentional, but the `structured` data loss is silent — no warning or error.
- **Files:** `src/relay/parallel/types.py:62-72`
- **Trigger:** Any parallel step where an adapter's `AgentOutput.structured` contains a `"text"` key.
- **Workaround:** Framework builders must ensure adapters never emit structured output with a `"text"` key.
- **Fix approach:** Either merge `output.text` into `structured` under a different key (e.g., `"_text"`), or warn when overwriting.
- **Severity:** MEDIUM

### BUG-02: `_check_budget` compares wrong projection against `manifest.max_tokens`

- **Symptoms:** Per-agent `max_tokens` check at `src/relay/core_pipeline.py:276-285` uses the same `projected` variable from `_slice_payload` — which is the *input* context size. But `max_tokens` on `AgentManifest` (`src/relay/slicer/manifest.py:31`) is documented as "Maximum tokens allowed for this agent's context" — semantically an output or total limit. Comparing an input projection against this limit is semantically wrong. An agent reading 500 tokens but producing 50 tokens of output is blocked if `max_tokens=100`. An agent reading 10 tokens but producing 5000 tokens passes the check and blows the limit.
- **Files:** `src/relay/core_pipeline.py:276-285`
- **Trigger:** Any pipeline step with an `AgentManifest` that has `max_tokens` set.
- **Workaround:** Set `max_tokens` high enough to accommodate both input and projected output.
- **Fix approach:** Replace `projected` (input size) with an estimate of output size based on `manifest.writes`.
- **Severity:** HIGH

### BUG-03: `apply_join_strategy` raises `ValueError` instead of returning `Failure` for invalid state

- **Symptoms:** The `apply_join_strategy()` function at `src/relay/parallel/join.py:157-178` raises a `ValueError` when `first_wins_coros is None` and strategy is `FIRST_WINS`. This converts a type-level programming error into a runtime exception instead of returning `Failure` — inconsistent with the rest of the codebase's `Result`-based error handling. Also, `_apply_union` and `_apply_vote` raise `ValueError` on invariant violations (`agent_output is None` but `success=True`).
- **Files:** `src/relay/parallel/join.py:157-178`, `src/relay/parallel/join.py:42-49`, `src/relay/parallel/join.py:86-94`
- **Trigger:** Programming error in framework builder code.
- **Workaround:** Always pass `first_wins_coros` when using `FIRST_WINS`.
- **Fix approach:** Return `Failure(ErrorCode.INVALID_STATE)` instead of raising `ValueError` for invalid-argument scenarios.
- **Severity:** MEDIUM

### BUG-04: `__post_init__` of `ContextEnvelope` raises `ValueError` on validation

- **Symptoms:** `ContextEnvelope.__post_init__()` at `src/relay/envelope.py:79-91` raises `ValueError` for invalid `step`, `token_budget_used`, or `token_budget_total` values. This is an exception in a `Result`-typed codebase. However, these are "can't happen" errors if factory functions are used correctly (`create_initial_envelope`, `create_next_envelope` both validate before construction), so this is a defense-in-depth gap rather than a regular-occurrence bug.
- **Files:** `src/relay/envelope.py:79-91`
- **Trigger:** Direct construction of `ContextEnvelope` with invalid values.
- **Workaround:** Always use `create_initial_envelope` or `create_next_envelope`.
- **Fix approach:** Accept as design intent — these are programmer-error assertions, not operational errors. Document this distinction clearly.
- **Severity:** LOW

## Security Considerations

### SSRF via `LocalModelAdapter.unvalidated base_url`

- **Risk:** `LocalModelAdapter.base_url` at `src/relay/runners/local_model.py:36` is a user-supplied string with zero URL validation. Used directly at line 76: `url = f"{self.base_url}/v1/chat/completions"`. An attacker who can configure the adapter can target internal network services (localhost, cloud metadata endpoints), exfiltrate payload contents, or exploit URL parsing differentials. No scheme, hostname, or path validation.
- **Files:** `src/relay/runners/local_model.py:22-113`
- **Current mitigation:** None. The `create()` factory strips trailing slashes only.
- **Recommendations:** Validate URL scheme (reject non-HTTP), reject private/loopback IPs (unless explicitly configured), add optional allowlist.
- **Severity:** HIGH

### Symlink following in `save_snapshot`

- **Risk:** `save_snapshot()` at `src/relay/snapshot.py:67-128` creates pipeline directories with `mkdir(parents=True, exist_ok=True)` at line 83. If an attacker has already placed a symlink at the pipeline directory path, subsequent snapshot writes follow the symlink. Windows `os.replace` follows reparse points. Currently mitigated at lines 84-94 with post-creation symlink checks, but there is a TOCTOU window between `mkdir()` and the check.
- **Files:** `src/relay/snapshot.py:67-128`
- **Current mitigation:** Checks `pipeline_path.is_symlink()` after `mkdir()` (lines 84, 90). TOCTOU window is small but present.
- **Recommendations:** Check before and after `mkdir()` (already partially done). Validate that `pipeline_path.resolve().parent` starts with `self._storage_path.resolve()`. Consider `follow_symlinks=False` where available.
- **Severity:** MEDIUM

### TOCTOU race in `_add_to_index` — read-modify-write not atomic

- **Risk:** `_add_to_index()` at `src/relay/snapshot.py:220-276` reads the index file from disk (line 223-246), modifies it in memory (line 249-258), and writes it back via `os.replace` (line 264). Between read and write, another concurrent `save_snapshot` call can read the same stale index — one of the two snapshot IDs is silently lost. The `PipelineState` lock protects in-memory state but NOT the filesystem index.
- **Files:** `src/relay/snapshot.py:220-276`
- **Current mitigation:** None for concurrent filesystem access.
- **Recommendations:** Use a per-pipeline lockfile (e.g., `pipeline_path / ".index.lock"`) or read-modify-write inside a retry loop with version check. Or document non-atomicity as an accepted limitation.
- **Severity:** MEDIUM

### No timestamp freshness validation in `verify_signature`

- **Risk:** `verify_signature()` at `src/relay/envelope.py:160-183` never checks the envelope timestamp against current time. A validly-signed envelope from any point in history can be verified successfully. The `max_age_seconds` parameter exists in the function signature but defaults to `None` (disabled) and is never called with a value from any caller.
- **Files:** `src/relay/envelope.py:160-183`
- **Current mitigation:** The `max_age_seconds` parameter is implemented but not used.
- **Recommendations:** Add a sensible default `max_age_seconds` (e.g., 86400 = 24 hours) or enforce at the pipeline level. Call `verify_signature` with a max-age in all load-and-verify paths.
- **Severity:** HIGH

### Public `create_next_envelope` bypasses budget enforcement

- **Risk:** `create_next_envelope()` at `src/relay/envelope.py:227-265` is a public function exported in `__all__`. Its docstring states: "Budget validation is performed by HardCapEnforcer before envelope creation. This function trusts that the budget check has already been done." Any caller can call this directly, bypassing all budget checks.
- **Files:** `src/relay/envelope.py:227-265`
- **Current mitigation:** Documented warning. In normal pipeline flow, called only after `_check_budget`.
- **Recommendations:** Move `create_next_envelope` to be an internal function, or add optional budget pre-validation.
- **Severity:** MEDIUM

### `_apply_manifest` overwrites invalid signatures without verification

- **Risk:** `_apply_manifest()` at `src/relay/core_pipeline.py:326-358` re-signs an envelope with a new manifest hash but never verifies the input envelope's signature first. If a tampered envelope reaches this method, the invalid HMAC is silently healed with a new valid signature. Currently mitigated by pipeline flow (envelopes are freshly constructed internally), but defense-in-depth is missing.
- **Files:** `src/relay/core_pipeline.py:326-358`
- **Current mitigation:** Pipeline flow ensures envelopes reaching this point are freshly constructed by trusted internal paths.
- **Recommendations:** Add `verify_signature()` call before re-signing. Returns `Failure(INVALID_SNAPSHOT)` on mismatch.
- **Severity:** MEDIUM

### No payload size limits — unbounded disk/memory consumption

- **Risk:** `save_snapshot()` (`src/relay/snapshot.py:67-128`) writes envelope payload to disk without any size limit. `load_snapshot()` (`src/relay/snapshot.py:130-176`) reads without limiting input size. An attacker who can influence the payload (via agent adapter or direct `execute_step` call) can cause disk fill, memory exhaustion, or CPU exhaustion. A `MAX_SNAPSHOT_BYTES = 100MB` constant is defined at line 22 but only enforced at save path (line 104) — load path checks file size (line 146-149).
- **Files:** `src/relay/snapshot.py:22, 67-128, 130-176`
- **Current mitigation:** `MAX_SNAPSHOT_BYTES = 100MB` is checked on save (line 104) and on load (line 146-149).
- **Recommendations:** Ensure the `MAX_SNAPSHOT_BYTES` check cannot be bypassed. Consider adding payload size validation at the `execute_step` entry point before envelope creation.
- **Severity:** HIGH (partially mitigated)

### No limit on entity extraction count — validator OOM on crafted payload

- **Risk:** `_extract_entities()` at `src/relay/validator.py:242-296` collects entity strings into a `set[str]` with `MAX_EXTRACTED_ENTITIES = 10000` limit defined at line 18 and checked at line 262. The limit exists but a payload with many unique entity-like strings near this cap consumes significant memory.
- **Files:** `src/relay/validator.py:18, 242-296`
- **Current mitigation:** `MAX_EXTRACTED_ENTITIES = 10000` cap is defined and enforced.
- **Recommendations:** Keep the limit. Consider adding a separate cap on `_compute_diff` key-scanning as well.
- **Severity:** LOW (mitigated)

## Performance Bottlenecks

### No timeout on `CrewAIAdapter` thread

- **Problem:** `CrewAIAdapter.run()` at `src/relay/runners/crewai.py:70-91` calls `asyncio.to_thread(task.execute_sync)` with no timeout. If the CrewAI task hangs indefinitely, the entire pipeline coroutine is blocked. Compare with `LocalModelAdapter` (`src/relay/runners/local_model.py:60` parameter `timeout_seconds: float = 60.0`) and `CrewAIAdapter` itself has `timeout_seconds` parameter at line 58 that defaults to 300.0 but is NOT passed to `asyncio.to_thread()`.
- **Files:** `src/relay/runners/crewai.py:70-91`
- **Cause:** The `timeout_seconds` field is defined but never applied to the `asyncio.to_thread` call.
- **Fix approach:** Use `asyncio.wait_for(asyncio.to_thread(...), timeout=self.timeout_seconds)` in `run()`.
- **Severity:** MEDIUM

### Heuristic token counting is approximate — budget can be bypassed ~3×

- **Problem:** `estimate_tokens()` at `src/relay/envelope.py:273-292` and `HeuristicCounter.count()` at `src/relay/budget/token_counter.py:33-34` use `len(text) // 3` as a BPE token approximation. Documented as "a coarse approximation" and "NOT for precise token counting." Real BPE tokenizers (cl100k_base) can produce ratios outside the 0.25-0.40 range for adversarial inputs. Budget enforcement based on this heuristic can be bypassed by approximately 3×.
- **Files:** `src/relay/envelope.py:273-292`, `src/relay/budget/token_counter.py:33-34`
- **Cause:** Heuristic nature of the counter (character-count-based).
- **Fix approach:** Use `tiktoken` in production (it's available as an optional dependency). The `AutoTokenCounter` at `src/relay/budget/token_counter.py:83-85` auto-selects `_TiktokenCounter` if `tiktoken` is installed. Document that production deployments should install `relay[tiktoken]`.
- **Severity:** LOW

## Fragile Areas

### `PipelineState.transaction()` lock discipline

- **Files:** `src/relay/pipeline_state.py:53-74`, `src/relay/core_pipeline.py:153-169, 429-487, 489-629`
- **Why fragile:** `PipelineState` uses a non-reentrant `threading.Lock` tracked by thread ID (`_lock_owner`). The lock is manually acquired and released via a context manager (`transaction()`). All public methods that mutate state (except `_finalize_step`) must be called inside a transaction. If any code path calls `transaction()` inside another transaction, it's a `RuntimeError`. If any code path forgets to hold the lock, state corruption occurs silently because only `register_snapshot`, `snapshot_ids`, and all state-access methods call `_assert_lock_held()`. The methods that actually mutate state (`_check_budget`, `_apply_manifest`, `_slice_payload`, `_do_rollback`) do NOT call `_assert_lock_held()`.
- **Safe modification:** Always add `_assert_lock_held()` to new state-mutating methods. Never call `transaction()` from within a method that documents "REQUIRES: caller holds lock." Use `with self._state.transaction()` only at the outermost public API methods that coordinate transactions.
- **Test coverage:** `test_pipeline_state.py` (139 lines) covers basic lock behavior. No stress-test for concurrent access patterns.

### `_do_rollback` fragile against `RollbackHandler` returning non-`RollbackSuccess`

- **Files:** `src/relay/core_pipeline.py:360-392`
- **Why fragile:** The type dispatch at line 380 uses `isinstance(result, RollbackSuccess)`. Currently `restore_to_previous()` returns `RollbackSuccess | Failure` (never `Success`). If a future refactor introduces a `Success` return path, the guard at line 380 silently skips the state mutation (`set_current` is never called) — the failure is returned to the caller but pipeline state is left inconsistent.
- **Safe modification:** Replace the isinstance guard with a pattern that handles all `Result` variants explicitly: `isinstance(result, Failure) -> return result; # must be RollbackSuccess`.
- **Test coverage:** `test_pipeline_rollback.py` (66 lines) — minimal.

### `AutoGenAdapter` accepts unvalidated `agent` object

- **Files:** `src/relay/runners/autogen.py:34-55`
- **Why fragile:** `self.agent: object` is stored without structural validation at construction. `__post_init__` only checks for `initiate_chat` and `chat_messages` attributes (added as a fix, but this is a late addition). The `run()` at line 73 uses `_make_user_proxy_with_chat(proxy_obj).initiate_chat()` — if the agent doesn't satisfy the expected protocol, the error surfaces as an obtuse `AttributeError` inside `asyncio.to_thread`, obscuring the traceback.
- **Safe modification:** Validate the agent structurally in `__post_init__` (already done — check exists). Consider using `isinstance(agent, Protocol)` for `@runtime_checkable`.
- **Test coverage:** `test_autogen.py` (79 lines) — covers basic cases.

### `run_single_fork` uses `replace(..., payload=filtered)` for scoped envelope

- **Files:** `src/relay/parallel/fork_runner.py:82`
- **Why fragile:** `replace(pre_fork_envelope, payload=filtered_payload)` creates a new envelope with filtered payload for validation. Since `ContextEnvelope` is frozen, `replace` creates a shallow copy. The payload dict is filtered (new dict), so the original is preserved. But the `replace` call is heavy — it copies all envelope fields including `signature`. The signature on the filtered envelope is now incorrect (HMAC covers the original full payload). While this envelope is never persisted, it's a copy of a signed object with a now-invalid HMAC, which could confuse debugging.
- **Safe modification:** Accept as-is — the scoped envelope is used only for validation and discarded. The incorrect signature has no runtime impact.
- **Test coverage:** `test_fork_runner.py` (216 lines) — covers fork execution.

## Scaling Limits

### `MAX_EXTRACTION_DEPTH` and `MAX_EXTRACTED_ENTITIES` in validator

- **Current capacity:** `MAX_EXTRACTION_DEPTH = 50` at `src/relay/validator.py:17`, `MAX_EXTRACTED_ENTITIES = 10000` at line 18.
- **Limit:** A payload with 10,000+ unique entity-like strings at depth 1 passes the depth check and fills memory with 10,000 strings. The diff computation (`_compute_diff`) also operates on key sets without size limits, but dict key count is bounded by Python's hash table.
- **Scaling path:** These limits are already in place and reasonable for current use cases. Monitor for OOM in production if payload sizes grow.
- **Severity:** LOW

### `MAX_SNAPSHOT_BYTES` limit

- **Current capacity:** `MAX_SNAPSHOT_BYTES = 100MB` at `src/relay/snapshot.py:22`. Enforced on save (line 104) and load (line 146-149).
- **Limit:** Payloads over 100MB are rejected. This is reasonable for current use cases.
- **Scaling path:** Expose as configurable parameter on `SnapshotStore`.
- **Severity:** LOW

## Dependencies at Risk

### `tiktoken` — optional but recommended

- **Risk:** Optional dependency (`pip install relay[tiktoken]`). If not installed, `AutoTokenCounter` falls back to `HeuristicCounter` which uses character-count-based estimation. The 0.25-0.40 token/char ratio is approximate and can be wrong by 3× for adversarial payloads.
- **Impact:** Budget enforcement accuracy degrades significantly without `tiktoken`. The `HeuristicCounter` is a fallback for development only.
- **Migration plan:** None needed — `tiktoken` is available as `relay[tiktoken]`. Document that production requires this optional dependency.
- **Severity:** LOW

### Framework adapters (`langchain-core`, `crewai`, `pyautogen`, `httpx`)

- **Risk:** All lazy-imported (`src/relay/runners/__init__.py:30-43`, plus lazy import within each adapter's `run()` method). If these packages are installed via dependency confusion or supply-chain attack, the lazy import brings in attacker-controlled code. This is a general Python supply chain risk.
- **Impact:** Supply-chain compromise of any adapter dependency.
- **Migration plan:** Document dependency verification (hashes, pinned versions) for production deployments. Not specific to Relay.
- **Severity:** INFO (general Python supply-chain risk)

## Missing Critical Features

### No snapshot cleanup mechanism

- **Problem:** Once snapshots are created, there is no API to delete old snapshots, prune history, or compact the snapshot store. The `SnapshotStore` at `src/relay/snapshot.py:55-65` has `save_snapshot`, `load_snapshot`, `get_latest_snapshot`, and `list_snapshots` — but no `delete_snapshot` or `purge_old_snapshots`. Orphaned files from rollbacks (see W1) accumulate indefinitely.
- **Blocks:** Long-running pipelines with frequent rollbacks will accumulate unbounded disk usage. There is no way to clean up old state programmatically.
- **Severity:** MEDIUM

### No snapshot CLI or management tooling

- **Problem:** Snapshots are stored as JSON files in the filesystem (`relay_data/snapshots/<pipeline_id>/`). There is no command-line tool, management UI, or API for inspecting, exporting, or repairing snapshot data. Debugging requires manual filesystem inspection.
- **Blocks:** Operational debugging, data recovery, and manual intervention in production scenarios.
- **Severity:** MEDIUM

### No concurrent throughput testing

- **Problem:** The documentation acknowledges budget enforcement as "advisory under concurrent load" but there are no concurrent integration tests that verify thread-safety under real contention patterns. The lock discipline relies on programmer discipline (documenting "REQUIRES: caller holds lock").
- **Blocks:** Confidence in concurrent correctness.
- **Severity:** MEDIUM

## Test Coverage Gaps

### No tests for `SnapshotStore.delete_snapshot()` (feature doesn't exist)

- **What's not tested:** The ability to delete or prune snapshots. There is no such API. If added, would need tests for cascading index updates.
- **Files:** `src/relay/snapshot.py`
- **Risk:** Cannot clean up orphaned snapshots.
- **Priority:** Medium

### Minimal rollback handler tests

- **What's not tested:** `RollbackHandler` at `src/relay/pipeline_rollback.py` has only one test file (`test_pipeline_rollback.py` at 66 lines) that tests basic restore-to-previous behavior. No tests for edge cases like: snapshot missing for requested step, corrupted snapshot file, concurrent rollback calls, rollback on empty pipeline.
- **Files:** `src/relay/pipeline_rollback.py`, `tests/unit/test_pipeline_rollback.py`
- **Risk:** Rollback failures may go undetected until production.
- **Priority:** Medium

### No Failure-code-exhaustive tests for many modules

- **What's not tested:** The AGENTS.md requires "Every `Result`-returning function needs tests for every distinct `Failure` code" but:
  - `_do_rollback()` has two Failure paths (NO_ROLLBACK_AVAILABLE, INVALID_STATE) — not all are independently tested.
  - `_apply_manifest()` has `MANIFEST_BOUNDARY_VIOLATION`, `INVALID_SNAPSHOT` paths — not clearly tested individually.
  - `_check_budget()` has `BUDGET_EXCEEDED`, `TOKEN_BUDGET_EXCEEDED` paths — budget tests are basic.
  - Fork join strategies have `MERGE_CONFLICT` and `ALL_FORKS_FAILED` paths but the `INVALID_JOIN_STRATEGY` path is only tested via integration.
- **Files:** Various
- **Risk:** Regression risk when modifying Result-returning functions.
- **Priority:** High

### No mypy type-checking on test files

- **What's not tested:** Tests are exempted from `mypy --strict` with `disallow_any_expr = False` and `disallow_any_decorated = False` in `mypy.ini:21-23`. This means test files can use `Any`, ignore types, and have untyped definitions without CI catching them. Test quality degrades silently.
- **Files:** `mypy.ini:21-23`, all `tests/` files
- **Risk:** Test type errors mask real type errors. Test maintenance burden increases.
- **Priority:** Medium

---

*Concerns audit: 2026-05-17*
