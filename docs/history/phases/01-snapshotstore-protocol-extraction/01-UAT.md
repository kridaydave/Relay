---
status: testing
phase: 01-snapshotstore-protocol-extraction
source: 01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md
started: 2026-05-18T00:00:00.000Z
updated: 2026-05-18T00:00:00.000Z
---

## Current Test

number: 1
name: Nonce and sequence_number fields
expected: |
  Envelope includes nonce + monotonic sequence_number; replay returns Failure
awaiting: user response

## Tests

### 1. Nonce and sequence_number fields
expected: Envelope includes nonce + monotonic sequence_number; replay returns Failure
result: [pending]

### 2. Nonce verification
expected: Nonce verified on envelope validation; duplicate nonce rejected
result: [pending]

### 3. Sequence_number monotonic check
expected: Sequence_number checked for strict increase per pipeline_id
result: [pending]

### 4. Signature verify on load
expected: Loading snapshot verifies HMAC signature; tampered/ wrong key returns Failure
result: pass

### 5. Secret redacted in repr
expected: ContextBroker __repr__ and __str__ show "***" not the secret
result: [pending]

### 6. Budget enforces output tokens
expected: Hard cap fires on projected agent output, not input tokens
result: [pending]

### 7. __post_init__ returns Failure
expected: Validation error returns Failure not ValueError; callers handle it
result: [pending]

### 8. LocalModelAdapter URL validation
expected: base_url validated; internal/ file URLs rejected or config-gated; returns Failure
result: [pending]

### 9. Key rotation support
expected: ContextBroker accepts key_id + key history; verification tries all keys; new envelopes use latest key
result: [pending]

### 10. Orphan cleanup on rollback
expected: Contradiction rollback cleans up orphaned snapshot files
result: [pending]

### 11. Unique payload text keys
expected: agent_output_to_payload produces distinct text keys per agent output
result: [pending]

### 12. apply_join_strategy returns Failure
expected: Unknown join strategy returns Failure not ValueError
result: [pending]

### 13. Thread timeout
expected: CrewAIAdapter has configurable timeout; timeout returns Failure
result: [pending]

### 14. No symlink follow
expected: save_snapshot rejects symlinked paths; exclusive file creation prevents TOCTOU
result: pass

### 15. Atomic index update
expected: _add_to_index writes temp file then renames; concurrent writes don't corrupt
result: pass

### 16. Prune old snapshots
expected: SnapshotStore prunes by max count/ age; returns Failure on I/O error
result: [pending]

### 17. All failure codes tested
expected: Every Result-returning function has tests for every distinct Failure code
result: pass

### 18. Lock check on state mutation
expected: All state-mutating internal methods call _assert_lock_held() first
result: [pending]

### 19. Concurrent access tests
expected: threading.Thread tests for concurrent reads/writes/validation; no corruption
result: pass

### 20. Deployment guide
expected: docs/production.md exists with tiktoken recommendation and setup guide
result: [pending]

### 21. Release readiness
expected: All CRITICAL/ HIGH/ MEDIUM items resolved; tests + mypy pass; release tagged
result: [pending]

## Summary

total: 21
passed: 5
issues: 0
pending: 16
skipped: 0
blocked: 0

## Gaps

[none yet]
