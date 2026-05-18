# Relay Security Audit — v0.4.2

**Audit Date:** 17 May 2026
**Codebase:** 28 source files, ~3,576 lines
**Branch:** main @ fc03a66
**Previous Audits Reviewed:** 7 prior audits (6 May – 16 May 2026), V0.4-Audit.md (15 May 2026)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Threat Model](#threat-model)
3. [Finding Inventory](#finding-inventory)
   - [CRITICAL](#critical-findings)
   - [HIGH](#high-findings)
   - [MEDIUM](#medium-findings)
   - [LOW](#low-findings)
   - [INFO](#info)
4. [v1.0 Security Roadmap Status](#v10-security-roadmap-status)
5. [Previously Reported Status](#previously-reported-findings)
6. [Accepted Risks](#accepted-risks)

---

## Executive Summary

Relay takes security seriously — `hmac.compare_digest` is used for signature verification, pipeline_id is regex-validated before filesystem use, signing secrets must be ≥32 characters, and the Result pattern prevents uncaught exceptions. These are real strengths.

However, three architectural gaps stand out as **critical**:

1. **No replay attack protection whatsoever** — a captured signed envelope can be replayed indefinitely with no mechanism (nonce, timestamp TTL, monotonic counter) to detect or reject it.
2. **No signature verification on snapshot load** — the snapshot store trusts any JSON-shaped dict on disk, even if the HMAC is forged or absent.
3. **The signing secret lives in memory as a plain Python `str`** — accessible via attribute, visible in core dumps, and never zeroized.

The v1.0 roadmap acknowledges replay prevention and key rotation as deferred items, but snapshot-load signature verification and secret management are not on the roadmap at all.

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH | 5 |
| MEDIUM | 6 |
| LOW | 5 |
| INFO | 4 |

---

## Threat Model

### Actors

| Actor | Capabilities | Assumptions |
|-------|-------------|-------------|
| **Framework Builder** | Configures pipeline, registers adapters, chooses signing secret, sets storage path | Trusted; builds abstractions on top of Relay |
| **Agent** | Produces output via adapter; can see its ContextSlice only | Untrusted; may hallucinate, emit malicious payloads |
| **Filesystem Attacker** | Can read/write snapshot files, create symlinks, observe file metadata | Untrusted; has local or network filesystem access |
| **Network Attacker** | Can observe or modify traffic between LocalModelAdapter and model server | Untrusted; on same network segment |
| **External Caller** | Calls `execute_step`, `execute_parallel_step`, `rollback`, `get_current_envelope` | Untrusted; may pass arbitrary arguments |

### Assets

| Asset | Where | Impact if Compromised |
|-------|-------|-----------------------|
| `signing_secret` | `ContextBroker.signing_secret` (memory) | Forge any envelope signature |
| Snapshot store | `storage_path` (filesystem) | Read/modify all pipeline history |
| Context envelope | Memory + snapshot store | Read agent conversation, tamper with payload |
| Pipeline state | `PipelineState` (memory) | Corrupt current execution |
| Adapter registry | `AdapterRegistry._adapters` (memory) | Register malicious adapter |

### Attack Surface

| Entry Point | File | Attacker |
|-------------|------|----------|
| `create_context_broker(signing_secret, ...)` | `context_broker.py:22` | Framework Builder |
| `CoreRelayPipeline.create(signing_secret, ...)` | `core_pipeline.py:70` | Framework Builder |
| `execute_step(agent_output)` | `core_pipeline.py:152` | External Caller |
| `execute_step_with_manifest(agent_output, manifest)` | `core_pipeline.py:156` | External Caller |
| `execute_step_with_runner(adapter_name, manifest)` | `core_pipeline.py:421` | External Caller |
| `execute_parallel_step(fork_specs, join_strategy)` | `core_pipeline.py:481` | External Caller |
| `rollback()` | `core_pipeline.py:406` | External Caller |
| `SnapshotStore.save_snapshot(envelope)` | `snapshot.py:66` | Pipeline internals |
| `SnapshotStore.load_snapshot(snapshot_id)` | `snapshot.py:113` | Pipeline internals |
| `verify_signature(envelope, secret)` | `envelope.py:160` | Pipeline internals |
| `ContextEnvelope(...)` direct construction | `envelope.py:47` | Any Python code |
| `LocalModelAdapter(base_url, ...)` | `runners/local_model.py:22` | Framework Builder |
| `RawSDKAdapter(fn, ...)` | `runners/raw_sdk.py:26` | Framework Builder |

---

## Finding Inventory

---

### CRITICAL Findings

#### CRIT-01: No replay attack protection

| Field | Value |
|-------|-------|
| **Files** | `envelope.py:47-70`, `envelope.py:160-163`, `snapshot.py:335-431` |
| **Lines** | `envelope.py:47-70` (envelope fields), `envelope.py:160-163` (verify_signature), `snapshot.py:335-431` (load path) |
| **Severity** | CRITICAL |
| **CWE** | CWE-294 (Authentication Bypass by Capture-replay) |

**Description:**

Envelopes carry a `timestamp` and `step` field, but neither is enforced for freshness during verification. The `verify_signature` function (`envelope.py:160-163`) only checks HMAC integrity — it does **not**:

- Validate that `envelope.timestamp` is within an acceptable time window (no TTL / max-age check)
- Validate a monotonically increasing nonce per `pipeline_id`
- Consult a "seen nonces" set to detect duplicates
- Reject envelopes where `step` has already been consumed

An attacker who captures a valid signed envelope (e.g., from the snapshot store, network traffic, or log output) can replay it any number of times. Since there is no persisted execution history check per-envelope, replay bypasses all pipeline sequencing.

**Example attack:**
1. Capture `envelope_step_3.json` from the snapshot store (or network)
2. Rename/rewrite nothing — the HMAC still validates
3. Feed the replayed envelope into any `verify_signature` call → passes
4. If the pipeline state is reset or another pipeline exists with a compatible budget state, the replayed envelope can advance a different pipeline to step 3 with stale payload

**Evidence:**
- `envelope.py:137-157` (`compute_signature`): signs all fields including timestamp
- `envelope.py:160-163` (`verify_signature`): only compares HMAC — no freshness check
- `envelope.py:47-70` (`ContextEnvelope`): no nonce field, no sequence counter beyond `step` (which is part of the signed payload and could be arbitrarily set by the attacker's own constructed envelope)

**Suggested fix:**
- Add a `nonce` field (`str | None`) to `ContextEnvelope`
- Add a `sequence_number` (monotonically increasing int per pipeline, separate from `step`)
- Extend `verify_signature` to accept an optional `seen_nonces: set[str] | None` parameter; when provided, reject duplicates
- Add a `max_age_seconds: int | None` parameter to `verify_signature`; when provided, reject envelopes older than the threshold
- Enforce step progression at the verification level (not just in `validate_handoff` which is only called at commit time)

---

#### CRIT-02: No signature verification on snapshot load

| Field | Value |
|-------|-------|
| **Files** | `snapshot.py:113-153` (`load_snapshot`), `snapshot.py:335-431` (`_dict_to_envelope`) |
| **Lines** | `snapshot.py:126-146` (load), `snapshot.py:335-431` (deserialize) |
| **Severity** | CRITICAL |
| **CWE** | CWE-345 (Insufficient Verification of Data Authenticity) |

**Description:**

`SnapshotStore.load_snapshot()` reads a JSON file from disk and deserialises it to a `ContextEnvelope`, but **never calls `verify_signature`** on the result. The HMAC signature field is deserialised from the JSON dict and stored on the envelope object, but it is never validated against the envelope contents.

An attacker who gains write access to the snapshot store can:
1. Modify any snapshot file's payload
2. Construct a new JSON dict that looks like a valid `ContextEnvelope`
3. Inject a completely fabricated envelope with any `signature` value (empty string, garbage)
4. The `RollbackHandler.restore_to_previous()` will happily load and return the attacker-controlled envelope

`save_snapshot` at `snapshot.py:66-111` does call `_sign_envelope` in `core_pipeline.py`, so snapshots created by legitimate pipeline operation have valid signatures. But the signature is never re-verified on load.

**Evidence:**
- `snapshot.py:126-146`: loads JSON, calls `_dict_to_envelope`, checks `envelope.step != step` — but never calls `verify_signature`
- `snapshot.py:335-431` (`_dict_to_envelope`): deserialises the `signature` field as a string (`line 389-392`) but never validates it
- `pipeline_rollback.py:44-48`: calls `snapshot_store.load_snapshot()` and trusts the result without verification
- `core_pipeline.py:374-383` (`_do_rollback`): restores from snapshot without re-verifying signature

**Suggested fix:**
- In `save_snapshot`, store the signing secret (or a derived key hash) and envelope HMAC side by side in a separate integrity file
- OR: In `_dict_to_envelope`, accept an optional `secret` parameter and call `verify_signature` after deserialisation, returning `Failure(INVALID_SNAPSHOT)` on mismatch
- OR: Add a `SnapshotStore.verify_integrity(snapshot_id, secret) -> bool` method called by `RollbackHandler.restore_to_previous`
- At minimum: add a warning log when a loaded snapshot has an invalid signature, even if enforcement is deferred

---

#### CRIT-03: Signing secret stored as plain Python `str` — no memory protection

| Field | Value |
|-------|-------|
| **Files** | `context_broker.py:48-60`, `core_pipeline.py:48-69` |
| **Lines** | `context_broker.py:59` (`signing_secret: str`), `core_pipeline.py:55` (`signing_secret: str`) |
| **Severity** | CRITICAL |
| **CWE** | CWE-312 (Cleartext Storage of Sensitive Information) |

**Description:**

The HMAC signing secret is stored as a plain Python `str` in two frozen/regular dataclasses:

- `ContextBroker.signing_secret` (`context_broker.py:59`): a `str` attribute on a `@dataclass(frozen=True)`
- `CoreRelayPipeline.signing_secret` (`core_pipeline.py:55`): a `str` attribute on a `@dataclass`

Python strings are immutable, unzeroizable, and remain in memory until garbage collected (which may never happen promptly). The secret is:
- Visible in `repr()` output of `ContextBroker` and `CoreRelayPipeline` (both are dataclasses with default `__repr__`)
- Accessible via `pipeline._context_broker.signing_secret`
- Present in memory dumps, core dumps, and debugger attach
- Passed by value between methods: `create_initial_envelope(..., secret=self.signing_secret)` — each call adds another copy to Python's string interning

**Evidence:**
- `context_broker.py:59`: `signing_secret: str` — no `repr=False`, no `@property` wrapper
- `core_pipeline.py:55`: `signing_secret: str` — same exposure
- `context_broker.py:69-75`: passes `self.signing_secret` to `create_initial_envelope` — string is copied
- `context_broker.py:84-88`: same pattern for `create_next_envelope`
- `core_pipeline.py:350-351`: accesses `self._context_broker.signing_secret` in `_apply_manifest`

**Suggested fix:**
- Use `@dataclass(frozen=True, repr=False)` on `ContextBroker`, or override `__repr__` to mask the secret
- Use `os.urandom(32)` and `hmac.HMAC` object directly rather than string round-trips where possible
- Add `__str__` and `__repr__` methods that redact the secret
- Consider using `secrets` module or a dedicated `SigningKey` wrapper class that implements `__repr__`/`__str__` redaction
- At minimum: exclude from `__repr__` via field-level `repr=False`

---

### HIGH Findings

#### HIGH-01: No payload size limits — unbounded disk/memory consumption

| Field | Value |
|-------|-------|
| **Files** | `snapshot.py:66-111` (`save_snapshot`), `snapshot.py:113-153` (`load_snapshot`) |
| **Lines** | `snapshot.py:92-93` (json.dump), `snapshot.py:128` (json.load) |
| **Severity** | HIGH |
| **CWE** | CWE-770 (Allocation of Resources Without Limits or Throttling) |

**Description:**

`save_snapshot` writes the envelope payload to disk without any size limit. `load_snapshot` reads any JSON file without limiting input size. An attacker who can influence the payload (via a malicious agent adapter or by directly calling `execute_step` with a crafted dict) can:

1. **Disk fill**: A single snapshot with a multi-gigabyte payload fills the storage path. N such snapshots multiply the effect.
2. **Memory exhaustion**: `json.load(f)` loads the entire file into memory. A crafted snapshot file of 500MB consumes 500MB+ in RAM.
3. **CPU exhaustion**: `json.dump` and `json.load` on very large payloads are CPU-intensive. Repeated large snapshots degrade system performance.

**Evidence:**
- `snapshot.py:92-93`: `json.dump(self._envelope_to_dict(envelope), f, indent=2)` — no max_size parameter
- `snapshot.py:128`: `data: object = json.load(f)` — no max_bytes check
- `envelope.py:253-269` (`estimate_tokens`): the heuristic token counter could return large values for big payloads, but this provides no hard limit

**Suggested fix:**
- Add a `MAX_SNAPSHOT_BYTES` constant (e.g., 100MB) to `SnapshotStore`
- In `save_snapshot`, serialize to string first, check `len(json_str) < MAX_SNAPSHOT_BYTES`, return `Failure(ErrorCode.SNAPSHOT_SAVE_FAILED)` if exceeded
- In `load_snapshot`, read file size before loading: `if stat_result.st_size > MAX_SNAPSHOT_BYTES: return Failure(...)`
- Document payload size recommendations for framework builders

---

#### HIGH-02: SSRF via LocalModelAdapter.unvalidated `base_url`

| Field | Value |
|-------|-------|
| **File** | `runners/local_model.py:22-40` |
| **Lines** | `local_model.py:36` (`base_url: str`), `local_model.py:76` (URL construction) |
| **Severity** | HIGH |
| **CWE** | CWE-918 (Server-Side Request Forgery) |

**Description:**

`LocalModelAdapter.base_url` is a user-supplied string with zero validation. It is used directly to construct the request URL:

```python
url = f"{self.base_url}/v1/chat/completions"  # line 76
```

An attacker who can configure the adapter (or who registers a misnamed adapter pointing at a malicious URL) can:
- Target internal network services (`http://localhost:9200` — Elasticsearch, `http://169.254.169.254/` — cloud metadata)
- Target filesystem paths via `file://` scheme (httpx may not support this, but URL parsing ambiguity is risky)
- Target arbitrary external endpoints for data exfiltration (payload content is sent as POST body)
- Exploit URL parsing differentials between Python and httpx

No validation checks for:
- Scheme (should be `https://` or `http://`)
- Hostname (no allowlist, no blocklist for internal/loopback addresses)
- Path traversal characters
- Credential leakage (`http://user:pass@internal.service/`)

**Evidence:**
- `local_model.py:22-40` (`@dataclass(frozen=True)`): no URL validation in `__post_init__`
- `local_model.py:75-76`: `url = f"{self.base_url}/v1/chat/completions"` — direct string interpolation
- `local_model.py:78-80`: `httpx.AsyncClient.post(url, json=payload)` — arbitrary HTTP request

**Suggested fix:**
- Validate `base_url` in `__post_init__`: reject non-HTTP schemes, reject private/loopback IPs (unless explicitly configured via a flag)
- Use `yarl` or `urllib.parse.urlparse` to normalise and validate the URL
- Add an option for a proxy or explicit network allowlist
- Document the SSRF risk for framework builders who configure this adapter

---

#### HIGH-03: No timestamp freshness validation in `verify_signature`

| Field | Value |
|-------|-------|
| **File** | `envelope.py:160-163` |
| **Lines** | `envelope.py:160-163` |
| **Severity** | HIGH |
| **CWE** | CWE-613 (Insufficient Session Expiration) |

**Description:**

Related to CRIT-01 (replay) but focusing specifically on timestamp enforcement. Envelopes include a UTC `timestamp` field that is covered by the HMAC signature, but `verify_signature` never checks whether the timestamp is:

- Reasonably close to the current time (no `max_age_seconds` parameter)
- Within the pipeline's expected lifetime (hours, days, or weeks depending on use case)

A validly-signed envelope from any point in history can be verified successfully. Combined with the lack of nonce enforcement, this means a compromised snapshot store yields indefinitely-valid forged pipeline histories.

**Evidence:**
- `envelope.py:160-163`: the entire function body is `expected_sig = compute_signature(envelope, secret); return hmac.compare_digest(envelope.signature, expected_sig)` — zero time-related checks
- `compute_signature` (`envelope.py:137-157`): includes `_canonical_timestamp(envelope.timestamp)` in the signed payload, so timestamps are integrity-protected but freshness is never enforced

**Suggested fix:**
- Extend `verify_signature` signature to `verify_signature(envelope: ContextEnvelope, secret: str, max_age_seconds: int | None = None) -> bool`
- When `max_age_seconds` is provided, compute `(datetime.now(timezone.utc) - envelope.timestamp).total_seconds()` and reject if > max_age_seconds
- Default `max_age_seconds` to a sensible value (e.g., 86400 = 24 hours) rather than None for production safety
- Call `verify_signature` with a max_age in all load-and-verify paths

---

#### HIGH-04: `CoreRelayPipeline.__post_init__` raises `ValueError` instead of returning `Failure`

| Field | Value |
|-------|-------|
| **File** | `core_pipeline.py:101-116` |
| **Lines** | `core_pipeline.py:107-108` |
| **Severity** | HIGH |
| **CWE** | CWE-754 (Improper Check for Unusual or Exceptional Conditions) |

**Description:**

The `CoreRelayPipeline` factory method `create()` returns `Result[CoreRelayPipeline]` and correctly propagates `Failure` from `create_context_broker`. However, `__post_init__` (called when the class is constructed directly) re-validates the secret and raises `ValueError` instead of returning `Failure`:

```python
def __post_init__(self) -> None:
    ...
    broker_result = create_context_broker(
        signing_secret=self.signing_secret, token_budget_total=self.token_budget
    )
    if isinstance(broker_result, Failure):
        raise ValueError(broker_result.reason)  # line 108 — breaches Result pattern
```

This means:
- Direct construction `CoreRelayPipeline(signing_secret="short")` raises instead of returning `Failure`
- The class has **two different error contracts**: `create()` returns `Failure`, `__post_init__` raises `ValueError`
- Framework builders who use direct construction get an uncaught exception, violating Rule 3.1
- `self.signing_secret` and `self.token_budget` are available in `__post_init__` at the time of the call, but `self._pipeline_id` is already set (line 102) — state mutation occurs before validation completes

**Evidence:**
- `core_pipeline.py:101-108`: `__post_init__` validates and raises on failure
- `core_pipeline.py:70-99`: `create()` validates and returns `Failure` on failure
- The docstring on `ContextBroker` (`context_broker.py:54-58`) explicitly warns about this: "Direct construction bypasses validation and is intended only for internal use with pre-validated secrets" — but `__post_init__` actually does validate and raises

**Suggested fix:**
- Remove validation from `__post_init__` entirely (trust the factory or the caller)
- OR: Remove the `create()` factory and make `__post_init__` return a sentinel error state
- OR: Re-structure so `__post_init__` cannot raise — move all validation to `create()` and document direct construction as "only with pre-validated fields"

---

#### HIGH-05: No secret rotation mechanism — key rotation required for production

| Field | Value |
|-------|-------|
| **Files** | `context_broker.py`, `envelope.py` |
| **Lines** | All signing paths |
| **Severity** | HIGH |
| **CWE** | CWE-320 (Key Management Errors) |

**Description:**

There is zero infrastructure for key rotation. The v1.0 roadmap (§11) lists "Key rotation: Pipelines can rotate signing keys mid-run; old envelopes remain verifiable via key history log" as a planned feature, but v0.4.2 has:

- No key ID / `kid` field in the envelope to identify which key was used for signing
- No key history log
- No support for multiple active keys during rotation
- No key derivation from a master secret

If the signing secret is compromised:
1. All existing envelope signatures are trivially forgeable
2. Rotating the secret invalidates ALL existing envelope signatures — every snapshot becomes unverifiable
3. There is no mechanism to re-sign old snapshots with a new key

**Evidence:**
- `envelope.py:47-70` (`ContextEnvelope`): no `key_id` or `key_version` field
- `envelope.py:137-157` (`compute_signature`): no key derivation step; uses `secret` directly
- `context_broker.py:59` (`signing_secret: str`): single secret, no rotation support
- `core_pipeline.py:55` (`signing_secret: str`): single field, no key chain

**Suggested fix (design-level):**
- Add `key_id: str` field to `ContextEnvelope`
- Introduce a `SigningKey` data class with `id: str`, `secret: str`, `created_at: datetime`
- Change `ContextBroker` to hold a `dict[str, SigningKey]` (key history) rather than a single secret
- During verification, look up the key by `envelope.key_id` rather than using the single active secret
- See v1.0 roadmap — this is the planned scope

---

### MEDIUM Findings

#### MED-01: `with_fork_metadata()` creates unsigned envelope — leak window before re-sign

| Field | Value |
|-------|-------|
| **File** | `envelope.py:99-119` |
| **Lines** | `envelope.py:112-118` |
| **Severity** | MEDIUM |
| **CWE** | CWE-362 (Concurrent Execution with Shared State) |

**Description:**

`with_fork_metadata()` (`envelope.py:99-119`) creates a copy of the envelope with `signature=""` (line 118). The caller is expected to re-sign immediately:

```python
def with_fork_metadata(self, ...) -> "ContextEnvelope":
    return replace(self, ..., signature="")  # line 118
```

In `core_pipeline.py:588-598`:
```python
envelope_with_meta = new_envelope.with_fork_metadata(...)  # line 588 — signature=""
signed = envelope_with_meta.with_signature(
    compute_signature(envelope_with_meta, self._context_broker.signing_secret)  # line 594
)
```

The unsigned envelope (`envelope_with_meta`) exists as a local variable between lines 588 and 594. If an exception occurs during `compute_signature` (unlikely) or if a debugger/trace captures the variable, the unsigned envelope leaks. While the gap is narrow, it violates the principle that every envelope in the system should have a valid signature.

More importantly, `with_fork_metadata` is a **public method** on `ContextEnvelope` — any caller can produce an unsigned envelope. The docstring warns about this, but a public API that produces invalid objects is an accident waiting to happen.

**Suggested fix:**
- Add `signature` parameter to `with_fork_metadata()` that defaults to `""` but allows the caller to pass a pre-computed signature
- OR: Make `with_fork_metadata` private (rename to `_with_fork_metadata`) since it should only be called from within `execute_parallel_step`
- OR: Encapsulate the fork-metadata-attach-and-re-sign logic into a single `ContextBroker` method

---

#### MED-02: TOCTOU race in `_add_to_index` — read-modify-write not atomic

| Field | Value |
|-------|-------|
| **File** | `snapshot.py:197-253` |
| **Lines** | `snapshot.py:199-253` |
| **Severity** | MEDIUM |
| **CWE** | CWE-367 (TOCTOU Race Condition) |

**Description:**

`_add_to_index` reads the index file from disk, modifies it in Python memory, and writes it back via `os.replace()`. While the write is atomic (POSIX `rename`), the read-modify-write cycle is NOT atomic:

1. **Line 203-204**: reads `index.json` from disk
2. **Line 226-227**: appends `snapshot_id` to in-memory list
3. **Line 238-241**: writes modified index to `index.tmp`, atomically replaces `index.json`

Between steps 1 and 3, another concurrent `save_snapshot` call can:
- Read the same (stale) index
- Append a different snapshot_id
- Write it back
- One of the two snapshot_ids is silently lost

The `PipelineState` lock protects in-memory state but NOT the filesystem index — multiple threads in different processes, or concurrent threads after lock release, can race here.

**Evidence:**
- `snapshot.py:203-204`: read
- `snapshot.py:226-241`: modify and write
- `core_pipeline.py:197-200`: `save_snapshot` then `register_snapshot` — snapshot is persisted before index is updated
- No filesystem-level locking (flock, lockfile, etc.)

**Suggested fix:**
- Use a per-pipeline lockfile (`pipeline_path / ".index.lock"`) with `msvc.lock` or similar
- OR: Read the index, modify, and write inside a single `try/except` with retry on version mismatch
- OR: Append snapshot IDs to the index file rather than rewriting the whole file (line-oriented format)
- OR: Document the non-atomicity as an accepted limitation (low probability under normal usage)

---

#### MED-03: `os.replace()` follows symlinks — snapshot file write can target attacker-controlled path

| Field | Value |
|-------|-------|
| **File** | `snapshot.py:83-94` |
| **Lines** | `snapshot.py:83` (`mkdir`), `snapshot.py:94` (`os.replace`) |
| **Severity** | MEDIUM |
| **CWE** | CWE-61 (UNIX Symbolic Link Following) |

**Description:**

`snapshot.py:83` creates the pipeline directory with `mkdir(parents=True, exist_ok=True)`. If an attacker has already created a symlink at the pipeline directory path pointing to an arbitrary filesystem location, subsequent snapshot writes follow the symlink:

```python
pipeline_path = self._storage_path / pipeline_id  # pipeline_id validated, but path itself could be symlink
pipeline_path.mkdir(parents=True, exist_ok=True)  # no symlink check
temp_path = pipeline_path / f"{snapshot_id}.tmp"
snapshot_path = pipeline_path / f"{snapshot_id}.json"
os.replace(temp_path, snapshot_path)  # follows existing symlink
```

Windows `os.replace` follows reparse points (symlinks on NTFS). While filesystem-level attacks require local access, this is a defense-in-depth gap — the coding rules explicitly require prevention of path traversal (Rule 9.3), but symlink attacks at the destination directory bypass the string-level validation.

**Evidence:**
- `snapshot.py:83`: `pipeline_path.mkdir(parents=True, exist_ok=True)` — no `follow_symlinks=False` check
- `snapshot.py:91-94`: open and `os.replace` without checking if path is a symlink

**Suggested fix:**
- After `mkdir()`, check `not pipeline_path.is_symlink()` and return Failure if the path is a symlink
- Use `os.replace` with `follow_symlinks=False` where available
- Validate that `pipeline_path.resolve().parent` starts with `self._storage_path.resolve()` to detect path escapes

---

#### MED-04: Public `create_next_envelope` bypasses budget enforcement

| Field | Value |
|-------|-------|
| **File** | `envelope.py:207-245` |
| **Lines** | `envelope.py:207-245` |
| **Severity** | MEDIUM |
| **CWE** | CWE-862 (Missing Authorization) |

**Description:**

`create_next_envelope` is a public function (exported in `__all__`). Its docstring states: "Budget validation is performed by HardCapEnforcer before envelope creation. This function trusts that the budget check has already been done."

However, any caller — including an attacker who has access to the signing secret — can call `create_next_envelope` directly, bypassing all budget checks. Since `estimate_tokens` is a heuristic (character-count-based), and there's no server-side budget state check in the function, the token budget can be exceeded at will by calling this function directly.

In the normal pipeline flow (`core_pipeline.py:220-227`), `create_next_envelope` is called only after `_check_budget`, so the budget check IS performed before the normal path. But the function's public API surface offers no enforcement.

**Evidence:**
- `envelope.py:207-245`: `create_next_envelope` — no budget check, no nonce, no timestamp validation
- `envelope.py:216-217`: docstring acknowledges the gap
- `core_pipeline.py:220-227`: caller is trusted, but the function is public

**Suggested fix:**
- At minimum, document that `create_next_envelope` is intended for internal use by `ContextBroker` and may reject calls that don't come from the pipeline
- Add an internal-only `_create_next_envelope` or move the function to `ContextBroker` as a private method
- Consider adding optional budget pre-validation if the budget values are available

---

#### MED-05: No signature re-verification in `_apply_manifest` — trusts input envelope HMAC

| Field | Value |
|-------|-------|
| **File** | `core_pipeline.py:328-353` |
| **Lines** | `core_pipeline.py:328-353` |
| **Severity** | MEDIUM |
| **CWE** | CWE-345 (Insufficient Verification of Data Authenticity) |

**Description:**

`_apply_manifest` (`core_pipeline.py:328-353`) receives an envelope and re-signs it with a new manifest hash. However, it never verifies that the input envelope's signature is valid before proceeding:

```python
envelope_with_hash = envelope.with_manifest_hash(manifest_hash)
signed = envelope_with_hash.with_signature(
    compute_signature(envelope_with_hash, self._context_broker.signing_secret)
)
```

If a tampered envelope (invalid HMAC) reaches `_apply_manifest`, the function overwrites the invalid signature with a new valid one. This means a single point of tampering detection is silently healed. While the pipeline flow ensures envelopes reaching this point are freshly constructed by trusted internal paths, defense-in-depth is missing.

**Evidence:**
- `core_pipeline.py:346-353`: no `verify_signature` call before re-signing

**Suggested fix:**
- Add `if not verify_signature(envelope, self._context_broker.signing_secret): return Failure(reason="Envelope signature invalid", code=ErrorCode.INVALID_SNAPSHOT)` at the start of `_apply_manifest`
- This adds a single HMAC operation per step (~microseconds) with significant security benefit

---

#### MED-06: `_build_context_slice` bypasses signature verification on current envelope

| Field | Value |
|-------|-------|
| **File** | `core_pipeline.py:626-658` |
| **Lines** | `core_pipeline.py:626-658` |
| **Severity** | MEDIUM |
| **CWE** | CWE-345 (Insufficient Verification of Data Authenticity) |

**Description:**

`_build_context_slice` (`core_pipeline.py:626-658`) reads the current envelope from `PipelineState` and extracts a filtered slice for the agent. It never verifies the envelope's signature. If a tampered envelope is set as the current envelope (e.g., via direct state manipulation or a bug in rollback), the agent receives data from an unverified source.

The assumption is that envelopes stored in `PipelineState._current_envelope` were signed when they entered the pipeline. But:
- `set_current` (`pipeline_state.py:81-83`) accepts any `ContextEnvelope` without verification
- `rollback` sets restored envelopes (from snapshots that may have been tampered with — see CRIT-02)
- Archive paths also set envelopes without re-verification

**Evidence:**
- `core_pipeline.py:626-658`: no `verify_signature` call
- `pipeline_state.py:81-83` (`set_current`): no validation
- `pipeline_state.py:95-99` (`archive_and_set`): no validation

**Suggested fix:**
- Add signature verification in `PipelineState.set_current` and `archive_and_set` (requires passing the signing secret or having it available)
- OR: Verify before calling `set_current` in all pipeline paths (four call sites: `_handle_initial_step`, `_finalize_step`, `_do_rollback`, `execute_parallel_step`)

---

### LOW Findings

#### LOW-01: `estimate_tokens` heuristic bypass — token budget overdose via compact payload

| Field | Value |
|-------|-------|
| **File** | `envelope.py:253-269` |
| **Lines** | `envelope.py:268-269` |
| **Severity** | LOW |

**Description:**

`estimate_tokens` divides character count by 3. A payload with many non-BPE tokens (e.g., repeated single characters, binary data encoded as Unicode) could have a real token count substantially higher than `len(str) // 3`. The docstring acknowledges this as "a coarse approximation" and "NOT for precise token counting." Budget enforcement based on this heuristic can be bypassed by approximately 3×, and the enforcement is advisory anyway (lock released before adapter.run()).

**Suggested fix:**
- This is already documented. No action needed beyond ensuring framework builders understand the heuristic nature.

---

#### LOW-02: `RawSDKAdapter` can execute arbitrary callables — supply chain risk

| Field | Value |
|-------|-------|
| **File** | `runners/raw_sdk.py:26-60` |
| **Lines** | `runners/raw_sdk.py:36` (`fn: SyncCallable \| AsyncCallable`) |
| **Severity** | LOW |
| **CWE** | CWE-74 (Injection) |

**Description:**

`RawSDKAdapter` accepts any callable and invokes it with messages derived from the context slice. This is by design — the adapter is a bridge to arbitrary agent implementations. However, if a malicious callable is registered (e.g., via dependency confusion in a plugin system), Relay provides no sandboxing.

The try/except at `core_pipeline.py:470-476` catches `Exception` and returns `Failure`, but a callable that performs malicious actions before raising (or that runs indefinitely without raising) is not stopped.

**Suggested fix:**
- Document that all registered adapters are trusted and the `RawSDKAdapter` inherits the security posture of the callable
- Consider a `timeout` parameter for adapter runs
- No code change needed — this is an accepted-risk design decision

---

#### LOW-03: Unvalidated `agent_id` in `AgentManifest` — potential injection in slice context

| Field | Value |
|-------|-------|
| **File** | `slicer/manifest.py:12-28` |
| **Lines** | `slicer/manifest.py:24` (`agent_id: str`) |
| **Severity** | LOW |
| **CWE** | CWE-20 (Improper Input Validation) |

**Description:**

`AgentManifest.agent_id` is a plain `str` with no validation on format, length, or content. It is passed to adapters via `ContextSlice.agent_id` (`runners/protocol.py:34`). If `agent_id` is used in downstream logging, metric labels, or filesystem paths (by a framework builder's code), it could enable injection attacks.

Within Relay itself, `agent_id` is only used in:
- `ContextSlice.agent_id` (data passing)
- `validate_manifest_boundaries` error messages
- `_combine_manifest_hashes` (hashed, not used directly)

No direct injection vector exists in Relay's core paths, but it's a risk for framework builders.

**Suggested fix:**
- Add `agent_id` validation in `AgentManifest.__post_init__` (reject empty strings, control characters, path separators)
- Document that downstream consumers should sanitize `agent_id` before using in filesystem/log contexts

---

#### LOW-04: No timeout on `CrewAIAdapter` thread — stuck agent blocks pipeline

| Field | Value |
|-------|-------|
| **File** | `runners/crewai.py:68-86` |
| **Lines** | `runners/crewai.py:79` |
| **Severity** | LOW |
| **CWE** | CWE-400 (Uncontrolled Resource Consumption) |

**Description:**

`CrewAIAdapter.run` (`crewai.py:79`) calls `await asyncio.to_thread(task.execute_sync)` with no timeout. If the CrewAI task hangs indefinitely, the entire pipeline (which holds no lock but awaits the coroutine) is blocked until the thread completes or the process is killed.

Compare with `LocalModelAdapter` which has a `timeout_seconds` parameter.

**Suggested fix:**
- Add a `timeout_seconds: float = 300.0` parameter to `CrewAIAdapter`
- Use `asyncio.wait_for(asyncio.to_thread(task.execute_sync), timeout=self.timeout_seconds)` in `run`

---

#### LOW-05: No limit on entity extraction count — validator OOM on crafted payload

| Field | Value |
|-------|-------|
| **File** | `validator.py:241-293` |
| **Lines** | `validator.py:257-291` |
| **Severity** | LOW |
| **CWE** | CWE-770 (Allocation of Resources Without Limits or Throttling) |

**Description:**

`_extract_entities` (`validator.py:241-293`) collects entity strings into a `set[str]` with no upper bound. A payload with many unique entity-like strings (thousands or millions of unique values under entity-keyed fields) will consume unbounded memory in the entity set. While `MAX_EXTRACTION_DEPTH = 50` limits nesting depth, a flat dict with 100,000 entity keys at depth 1 passes the depth check and fills memory.

The diff computation (`_compute_diff`) also operates on key sets without size limits, but dict key count is bounded by Python's hash table — the primary risk is `_extract_entities` accumulating many strings.

**Suggested fix:**
- Add `MAX_EXTRACTED_ENTITIES = 10000` (or similar) to cap the entity set size
- Stop adding entities once the cap is reached

---

### INFO

#### INFO-01: Lazy imports — predictable, but dependency confusion is possible

| File | Lines |
|------|-------|
| `runners/__init__.py` | `30-43` |
| `runners/local_model.py` | `69` |
| `runners/crewai.py` | `70` |
| `runners/autogen.py` | `51` |
| `budget/token_counter.py` | `46-85` |

Lazy imports are used throughout (tiktoken, httpx, crewai, autogen). The `__getattr__` pattern in `runners/__init__.py` uses hardcoded module paths, which is safe. However, if a framework builder's environment has a malicious package installed under one of these names (dependency confusion), the lazy import could bring in attacker-controlled code. This is a general Python supply chain risk, not specific to Relay.

**Suggestion:** Document the required/recommended dependency verification (hashes, pinned versions) for production deployments.

---

#### INFO-02: `pipeline_id` generated internally — but `create_initial_envelope` accepts it as parameter

| File | Lines |
|------|-------|
| `core_pipeline.py:102` | `self._pipeline_id = uuid.uuid4().hex` |
| `envelope.py:166-204` | `create_initial_envelope(pipeline_id=...)` |

In normal pipeline flow, `pipeline_id` is a UUID hex string generated internally. However, `create_initial_envelope` accepts it as a parameter — any caller can set any pipeline_id. The pipeline_id is validated against `PIPELINE_ID_PATTERN`, but a caller outside the pipeline could use a valid but confusing pipeline_id (e.g., reusing an existing pipeline's ID). This is by design for flexibility but worth noting.

---

#### INFO-03: `ContextEnvelope` has no `__repr__` override — secrets not leaked, but envelope data visible

| File | Lines |
|------|-------|
| `envelope.py:46-70` | ContextEnvelope is `@dataclass(frozen=True)` |

`ContextEnvelope` fields are visible in repr. The `signature` field is a hex string (64 chars), not the signing secret itself — no direct secret exposure. The `payload` field could contain sensitive agent data and would be visible in logs or debug output. Consider `repr=False` on `payload` if agent conversations are sensitive.

---

#### INFO-04: Platform-compatible `os.replace` — Windows `rename` is not atomic for open files

| File | Lines |
|------|-------|
| `snapshot.py:94,241` | `os.replace(temp_path, snapshot_path)` |

`os.replace` on Windows uses `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, which is atomic at the filesystem level for the metadata operation but not atomic in terms of readers observing a partially-consistent file. Since `json.load` opens the file and reads it completely before returning, and `os.replace` atomically swaps the directory entry, this is safe for readers — no process sees a half-written file. On Linux, `os.replace` is `rename(2)` which is atomic.

---

## v1.0 Security Roadmap Status

The design document (§11) lists three security hardening features for v1.0:

| Feature | Status | Notes |
|---------|--------|-------|
| **Constant-time comparison** | ✅ **IMPLEMENTED** | `envelope.py:163` uses `hmac.compare_digest`. This is correctly in place before v1.0. |
| **Key rotation** | ❌ **NOT IMPLEMENTED** | No key ID, key history, or rotation mechanism. See HIGH-05. |
| **Replay attack prevention** | ❌ **NOT IMPLEMENTED** | No nonce, no timestamp TTL, no seen-nonces tracking. See CRIT-01 and HIGH-03. |

**Other critical items NOT on the v1.0 roadmap:**

| Gap | PRIORITY |
|-----|----------|
| Snapshot signature verification on load (CRIT-02) | Must be fixed before or at v1.0 |
| In-memory secret protection (CRIT-03) | Must be fixed before or at v1.0 |
| Payload size limits (HIGH-01) | Should be fixed by v1.0 |
| SSRF protection in LocalModelAdapter (HIGH-02) | Should be fixed by v1.0 |
| Symlink attack prevention (MED-03) | Should be fixed by v1.0 |
| Re-verify signature on trust boundaries (MED-05, MED-06) | Recommended by v1.0 |

---

## Previously Reported Findings

The following prior-audit findings were verified as **fixed** or **still present**:

| Audit | ID | Status in v0.4.2 |
|-------|----|------------------|
| V0.4-Audit.md (Eric) | GATE-01 (uncommitted changes) | ✅ **FIXED** — only `.claude/settings.local.json` modified |
| V0.4-Audit.md (Eric) | GATE-02 (empty `__all__`) | ✅ **FIXED** — `relay/__init__.py:19-41` exports all public types |
| V0.4-Audit.md (Eric) | BUG-01 (INVALID_STATE vs INVALID_JOIN_STRATEGY) | ❓ **NOT VERIFIED** — code returns INVALID_STATE at line 512; test not read |
| V0.4-Audit.md (Eric) | BUG-02 (text key collision) | ❌ **STILL PRESENT** — `parallel/types.py:68` `raw["text"] = output.text` can be overwritten by `dict(output.structured)` at line 69 if `output.structured` contains `"text"` key |
| V0.4-Audit.md (Eric) | BUG-03 (unused import time) | ❌ **STILL PRESENT** — `fork_runner.py:10` `import time` is exported but not used in that module (it's imported but actually used in the types module) |
| V0.4-Audit.md (Eric) | RULE-01 (private names in __all__) | ✅ **FIXED** — `parallel/__init__.py` exports only public names |
| V0.4-Audit.md (Eric) | RULE-02 (mypy.ini syntax) | ❓ **NOT CHECKED** |
| V0.4-Audit.md (Eric) | RULE-05 (continue vs break) | ❌ **STILL PRESENT** — `packers.py:73,155` uses `continue` |
| V0.4-Audit.md (Eric) | MED-01 (two-step commit) | ❌ **STILL PRESENT** — `core_pipeline.py:572-624` now does everything in one transaction (improved from v0.4.0) |
| V0.4-Audit.md (Matt) | BUG-M-02 (int cast) | ✅ **FIXED** — `_dict_to_envelope` now uses `_require_int` for fork_count and forks_succeeded (lines 399-411) |
| V0.4-Audit.md (Matt) | MED-M-04 (ValueError in join) | ❌ **STILL PRESENT** — `join.py:44-49` and `join.py:87-94` raise `ValueError` instead of returning `Failure` |
| Audit-10-May-2026-2 | Path traversal in load_snapshot | ✅ **FIXED** — `save_snapshot` validates pipeline_id at line 77; `load_snapshot` validates snapshot_id format at line 115 |

---

## Accepted Risks

The following are documented as accepted by design:

| Risk | Rationale | Documented In |
|------|-----------|--------------|
| Budget enforcement is advisory under concurrent load | Lock released before `adapter.run()`; token counts are heuristic | `core_pipeline.py:437-441` (docstring), `AGENTS.md` |
| `RawSDKAdapter` executes arbitrary callables | Adapter layer is trusted; framework builders control registration | By design — not documented as risk |
| `estimate_tokens` is approximate | Heuristic documented; `tiktoken` available for production | `envelope.py:253-269` (docstring) |
| `with_fork_metadata()` creates unsigned envelope | Immediate re-signing required in caller | `envelope.py:107-119` (docstring warning) |

---

*Comprehensive security audit generated by systematic review of all 28 source files (v0.4.2).*
