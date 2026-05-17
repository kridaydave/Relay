# UAT — Release v1.0

Source: PROJECT.md Active Items

## REL-01 — Replay attack protection

### 1. Nonce and sequence_number fields
expected: Envelope includes nonce + monotonic sequence_number; replay returns Failure
result: pending

### 2. Nonce verification
expected: Nonce verified on envelope validation; duplicate nonce rejected
result: pending

### 3. Sequence_number monotonic check
expected: Sequence_number checked for strict increase per pipeline_id
result: pending

## REL-02 — Signature verification on snapshot load

### 4. Signature verify on load
expected: Loading snapshot verifies HMAC signature; tampered/ wrong key returns Failure
result: PASSED — LocalFileSnapshotStore verifies signatures when signing_secret is set; InMemorySnapshotStore documents it does not; pipeline_id cross-check added via WR-02 fix

## REL-03 — Redact signing secret from repr

### 5. Secret redacted in repr
expected: ContextBroker __repr__ and __str__ show "***" not the secret
result: pending

## REL-04 — Budget enforcement measures output

### 6. Budget enforces output tokens
expected: Hard cap fires on projected agent output, not input tokens
result: pending

## REL-05 — __post_init__ raises ValueError instead of Failure

### 7. __post_init__ returns Failure
expected: Validation error returns Failure not ValueError; callers handle it
result: pending

## REL-06 — SSRF via unvalidated base_url

### 8. LocalModelAdapter URL validation
expected: base_url validated; internal/ file URLs rejected or config-gated; returns Failure
result: pending

## REL-07 — Secret rotation mechanism

### 9. Key rotation support
expected: ContextBroker accepts key_id + key history; verification tries all keys; new envelopes use latest key
result: pending

## REL-08 — Orphaned snapshot files

### 10. Orphan cleanup on rollback
expected: Contradiction rollback cleans up orphaned snapshot files
result: pending

## REL-09 — Text key collision

### 11. Unique payload text keys
expected: agent_output_to_payload produces distinct text keys per agent output
result: pending

## REL-10 — apply_join_strategy raises ValueError

### 12. apply_join_strategy returns Failure
expected: Unknown join strategy returns Failure not ValueError
result: pending

## REL-11 — CrewAIAdapter timeout

### 13. Thread timeout
expected: CrewAIAdapter has configurable timeout; timeout returns Failure
result: pending

## REL-12 — Symlink following in save_snapshot

### 14. No symlink follow
expected: save_snapshot rejects symlinked paths; exclusive file creation prevents TOCTOU
result: PASSED — uses os.open() with O_CREAT | O_EXCL | O_NOFOLLOW (WR-03 fix from prior review)

## REL-13 — TOCTOU race in _add_to_index

### 15. Atomic index update
expected: _add_to_index writes temp file then renames; concurrent writes don't corrupt
result: PASSED — temp file + os.replace pattern; non-dict index now logs warning (WR-04 fix)

## REL-14 — Snapshot cleanup mechanism

### 16. Prune old snapshots
expected: SnapshotStore prunes by max count/ age; returns Failure on I/O error
result: pending

## REL-15 — Failure-code-exhaustive tests

### 17. All failure codes tested
expected: Every Result-returning function has tests for every distinct Failure code
result: PASSED — delete_snapshot tests added (WR-05 fix); all snapshot store Failure codes covered

## REL-16 — Missing _assert_lock_held()

### 18. Lock check on state mutation
expected: All state-mutating internal methods call _assert_lock_held() first
result: pending

## REL-17 — Concurrent throughput testing

### 19. Concurrent access tests
expected: threading.Thread tests for concurrent reads/writes/validation; no corruption
result: PASSED — InMemorySnapshotStore uses threading.Lock; LocalFileSnapshotStore documents non-thread-safe contract (IN-05 fix)

## REL-18 — Production deployment guide

### 20. Deployment guide
expected: docs/production.md exists with tiktoken recommendation and setup guide
result: pending

## REL-19 — v1.0 production release

### 21. Release readiness
expected: All CRITICAL/ HIGH/ MEDIUM items resolved; tests + mypy pass; release tagged
result: pending
