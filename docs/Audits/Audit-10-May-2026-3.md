# Relay v0.3 — Final Pre-Ship Audit
**Date:** 10 May 2026  
**Auditor:** Claude (Sonnet 4.6)  
**Scope:** Full codebase — all 24 source modules, all 28 test modules, integration tests  
**Checked against:** `docs/Relay Coding Rules.md`, `docs/Relay Design Document.md`  
**Passes:** 2 (exhaustive)

---

## Summary

17 bugs found. 4 critical/high severity. No scope creep against design doc. All implemented features map cleanly to v0.1–v0.3. The most dangerous cluster is the rollback subsystem — manual rollback is broken for clean pipelines, and manifest violations always surface the wrong error code to callers.

---

## BUGS

---

### BUG-01 — Manual `rollback()` broken for all clean pipelines
**File:** `core_pipeline.py:_advance_to_new_envelope`  
**Severity:** Critical

`_advance_to_new_envelope` saves the new step's snapshot then immediately deletes the previous step's:

```python
oldest_in_history = self._state.peek_last()       # step N-1
snapshot_ids[new_envelope.step] = save_result.value  # saves step N
snapshot_ids.pop(oldest_in_history.step, None)    # deletes step N-1 ← BUG
```

After 2+ clean steps: `rollback()` → `peek_last()` returns step N-1 → `snapshot_ids.get(N-1)` = `None` → `Failure(NO_SNAPSHOT_REGISTERED)`. Manual rollback is broken for every clean pipeline. Only contradiction-triggered rollback works, because it saves the target snapshot immediately before lookup.

The variable name `oldest_in_history` is also wrong — `peek_last()` returns the MOST RECENTLY archived envelope (last element of `_previous_envelopes`), not the oldest.

**Fix:** Keep both the current step's snapshot AND the previous step's snapshot in `snapshot_ids`. The cleanup should only remove entries that are no longer reachable (older than N-1), not N-1 itself.

---

### BUG-02 — Manifest boundary violations always return the wrong error code
**File:** `core_pipeline.py:_apply_manifest`  
**Severity:** High

```python
result = validate_manifest_boundaries(manifest, set(envelope.payload.keys()))
if isinstance(result, Failure):
    return self._rollback_with_reason(result.reason)   # ← swallows MANIFEST_BOUNDARY_VIOLATION
```

`_rollback_with_reason` never returns `MANIFEST_BOUNDARY_VIOLATION`. What callers actually receive:

| Step | `has_history()` | `snapshot_ids` state | Returned code |
|---|---|---|---|
| Step 1 | False | empty | `NO_ROLLBACK_AVAILABLE` |
| Step 2 (first subsequent) | False | empty | `NO_ROLLBACK_AVAILABLE` |
| Step 3+ (clean history) | True | `{N: snapN}` only — N-1 deleted by BUG-01 | `NO_SNAPSHOT_REGISTERED` |

Callers switch on `Failure.code` (Rule 3.3). Every code path gives the wrong branch. The original `MANIFEST_BOUNDARY_VIOLATION` is completely lost.

**Fix:**
```python
if isinstance(result, Failure):
    return result   # not self._rollback_with_reason(result.reason)
```
Let the caller (`_finalize_step` or `_handle_subsequent_step`) decide whether to rollback.

---

### BUG-03 — `InvalidSnapshotIdError` escapes `_add_to_index` as unhandled exception
**File:** `snapshot.py:_add_to_index`  
**Severity:** High

`_add_to_index` sorts the index using `_extract_step_from_snapshot_id` as the key function. That function raises `InvalidSnapshotIdError` for malformed entries. The outer except only catches `(OSError, json.JSONDecodeError)`:

```python
except (OSError, json.JSONDecodeError) as e:   # ← InvalidSnapshotIdError NOT caught
    return Failure(...)
```

A corrupted index file with one bad snapshot ID causes `save_snapshot` to raise an unhandled exception instead of returning `Failure`. Violates Rule 3.1 (raise only for programmer errors; operational errors return `Failure`).

**Fix:** Add `InvalidSnapshotIdError` to the outer except clause, or rewrite `_extract_step_from_snapshot_id` to return a sentinel (e.g., `-1`) instead of raising, and filter those out before sorting.

---

### BUG-04 — Ghost index entries on file write failure break `get_latest_snapshot`
**File:** `snapshot.py:save_snapshot`  
**Severity:** High

```python
index_result = self._add_to_index(pipeline_id, snapshot_id)   # ← registered FIRST
...
try:
    with open(temp_path, "w") as f:
        json.dump(...)
    os.replace(temp_path, snapshot_path)
except (OSError, ...) as e:
    temp_path.unlink(...)
    return Failure(...)   # ← but the index entry stays!
```

If `_add_to_index` succeeds but the file write fails, the index has a snapshot ID pointing to a non-existent file. `get_latest_snapshot` returns the last index entry by position — now a ghost. The subsequent `load_snapshot` returns `Failure(SNAPSHOT_NOT_FOUND)` when the caller expects a valid checkpoint. This can silently break contradiction rollback if the ghost entry is the latest.

The code comment says "index-first ordering to avoid TOCTOU race: orphaned files are traceable" — but orphaned INDEX entries (pointing to missing files) are the real problem, not orphaned files.

**Fix:** Remove the ghost index entry in the save failure path, or move to file-first ordering with a post-write index update.

---

### BUG-05 — State mutated before validation; no recovery if `validate_handoff` returns `Failure`
**File:** `core_pipeline.py:_finalize_step`  
**Severity:** Medium

```python
def _finalize_step(self, current_envelope, new_envelope):
    self._state.archive_and_set(new_envelope)   # ← state mutated

    validation_result = self._handoff_validator.validate_handoff(...)
    if isinstance(validation_result, Failure):
        return validation_result   # ← returns Failure but _current is now new_envelope
```

`validate_handoff` returns `Failure` for pipeline ID mismatch or non-monotonic step — both impossible in normal operation since the pipeline creates both envelopes. But if it ever fires (external envelopes, future code changes), the internal state is left as `_current = new_envelope` and `current_envelope` in `_previous_envelopes`, while the caller receives a `Failure`. The next step operates on the wrong current envelope.

**Fix:** Move `archive_and_set` after validation succeeds, or add a compensating `set_current(current_envelope)` in the failure path.

---

### BUG-06 — Inconsistent state if snapshot save fails in `_advance_to_new_envelope`
**File:** `core_pipeline.py:_advance_to_new_envelope`  
**Severity:** Medium

`archive_and_set(new_envelope)` is already called in `_finalize_step` before `_advance_to_new_envelope` runs. If the snapshot save then fails:

```python
save_result = self._snapshot_manager.save(new_envelope)
if isinstance(save_result, Failure):
    return save_result   # ← _current = new_envelope, but snapshot_ids has no entry for it
```

`_current_envelope = new_envelope` but `snapshot_ids` has no key for `new_envelope.step`. If a subsequent step triggers contradiction rollback, `_rollback_on_contradiction` saves `new_envelope` as the "clean" snapshot — but `new_envelope` is already current, not a previous step. The pipeline is in a state where rollback cannot restore correctly.

---

### BUG-07 — `_detect_hallucination` shows wrong `removed_count` in error message
**File:** `validator.py:_detect_hallucination`  
**Severity:** Medium

```python
removed_count = len(removed_entities)   # e.g., 0

if new_count > 0:
    removed_count = max(removed_count, 1)   # bumped to 1 for division safety
    ratio = new_count / removed_count
    if ratio > self._hallucination_ratio_threshold:
        return f"... {new_count} new, {removed_count} removed ..."  # shows 1, not 0!
```

When 5 new entities appear and 0 are removed, the message reads `"5 new, 1 removed (ratio: 5.0x)"`. The actual count is 0 removed. Misleads users investigating false positives.

**Fix:**
```python
display_removed = removed_count
removed_count = max(removed_count, 1)
ratio = new_count / removed_count
if ratio > self._hallucination_ratio_threshold:
    return f"... {new_count} new, {display_removed} removed (ratio: {ratio:.1f}x)"
```

---

### BUG-08 — `RecencySlicePacker` returns empty when most recent section is oversized, even if older sections fit
**File:** `slicer/packers.py:RecencySlicePacker.pack`  
**Severity:** Medium

```python
for key in sorted_keys:   # newest → oldest
    if max_tokens and used_tokens + section_tokens > max_tokens:
        if result:
            continue   # correct: skip oversized middle sections
        return Success({})   # BUG: gives up immediately on first section
```

Payload `{"section_3": "x"*1000, "section_2": "a", "section_1": "b"}` with `max_tokens=10`:
- `section_3` is too large, result is empty → `return Success({})` immediately
- `section_2` and `section_1` (which both fit) are never considered

The agent gets empty context when it could have received older context. The `if result: continue` path correctly skips oversized middle sections but the early-exit `return Success({})` should be `continue` too, allowing the loop to reach smaller sections.

`RelevanceSlicePacker` has the identical pattern and the same bug.

**Fix:** Replace `return Success({})` with `continue` in both packers when `result` is empty. The loop will naturally return `Success({})` if no sections fit (loop exhausted with empty `result`).

---

### BUG-09 — `local_model.py:67` — `KeyError` on malformed API response
**File:** `runners/local_model.py:67`  
**Severity:** Low

```python
text = choices[0]["message"]["content"] if choices else ""
```

If the endpoint returns `choices=[{"finish_reason": "length"}]` (no `"message"` key), or `choices=[{"message": {}}]` (no `"content"` key), this raises `KeyError`. The pipeline's `execute_step_with_runner` catches it as `Exception` and converts to `Failure(ADAPTER_EXECUTION_FAILED)`, so it doesn't crash, but the error message is confusing.

**Fix:**
```python
text = choices[0].get("message", {}).get("content", "") if choices else ""
```

---

### BUG-10 — `snapshot._add_to_index` not thread-safe at filesystem level (multi-instance)
**File:** `snapshot.py:_add_to_index`  
**Severity:** Medium

READ-MODIFY-WRITE on `index.json` is not atomic. Two `CoreRelayPipeline` instances pointing at the same `storage_path` can both load the same index, both append their snapshot IDs, and one overwrites the other with `os.replace`. The pipeline-level lock only protects a single pipeline instance. Documented as a known limitation for now, but worth noting for v0.4 multi-pipeline scenarios.

---

## BUGS IN TESTS

---

### TEST-01 — `test_envelope.py:71,77` — attribute access without `isinstance` guard
**Severity:** Medium

```python
result = create_initial_envelope(pipeline_id="", ...)
assert isinstance(result.reason, str)       # AttributeError if result is Success
assert result.code == "INVALID_PIPELINE_ID"
```

If validation is accidentally removed and the function returns `Success`, the test fails with `AttributeError` rather than a meaningful assertion failure, hiding the regression.

**Fix:**
```python
assert isinstance(result, Failure)
assert result.code == ErrorCode.INVALID_PIPELINE_ID
```
Same pattern at lines 75-82.

---

### TEST-02 — `test_envelope.py:145-146` — duplicate assertion
**Severity:** Low

```python
assert second.code == "INVALID_PAYLOAD"
assert second.code == "INVALID_PAYLOAD"   # line 146 — exact duplicate, dead code
```

---

### TEST-03 — `test_pipeline.py:367` — vacuously true assertion
**Severity:** Medium

```python
assert len(results) >= 0   # always True — tests nothing
```

Should be `assert len(results) > 0` or a meaningful state invariant.

---

### TEST-04 — `test_pipeline_integration.py:135` — direct mutation of `snapshot_ids` without lock
**Severity:** Low

```python
pipeline._state.snapshot_ids[step] = "new-id"   # no transaction() context
```

Mutates `snapshot_ids` without holding `_lock`. CPython GIL makes this safe in practice, but violates the lock contract of `PipelineState` and serves as a bad example.

---

## RULE VIOLATIONS

| Rule | Location | Issue |
|---|---|---|
| 2.1 (no `Any`, `Optional`) | `core_pipeline.py:9` | Uses `Optional` from `typing`; project targets Python 3.12+ (`type Result[T]` syntax used in types.py). Use `X \| None`. |
| 2.1 (no `type: ignore`) | `token_counter.py:63` | `TiktokenCounter = None  # type: ignore[assignment, misc]` — explicitly prohibited. |
| 3.1 (Result not raise) | `snapshot.py:_add_to_index` | `InvalidSnapshotIdError` escapes as unhandled exception (see BUG-03). |
| 3.2 (no bare except) | `core_pipeline.py:execute_step_with_runner:~450` | `except Exception as e` — rule requires specific exception types. |
| 5.1 (Closeable protocol) | `core_pipeline.py:close()` | Calls `self.token_counter.close()` on `Optional[TokenCounter]` via attribute check. Rule 5.1 requires `Closeable` Protocol. |
| 7.1 (test names are sentences) | `test_pipeline.py` | Class `TestPipelineRollback2` is an identifier, not a sentence. |
| 7.5 (Failure path tests) | `core_pipeline.py` | `_rollback_with_reason` and `_rollback_and_consume` have no dedicated unit tests. |
| 7.6 (Protocol satisfaction test) | All test files | No `isinstance(FixedCounter(5), TokenCounter)` assertion exists anywhere in the suite (Rule 7.6 requirement). |
| 8.2 (docstring accuracy) | `core_pipeline.py` module docstring | `"Does NOT: define agent behaviour, manage prompts"` — does not mention what it explicitly avoids at current scope (token counting implementation, signing, slice strategy). |
| 9.3 (path sanitisation) | `snapshot.py:__init__` | `storage_path` goes directly into `Path(storage_path).mkdir()` with no validation. `pipeline_id` is validated before path use; `storage_path` is not. |

---

## DEAD CODE

| Location | What | Notes |
|---|---|---|
| `pipeline_snapshot.py:7-14` | Unused imports: `json`, `Any`, `ErrorCode`, `Failure`, `Success` | `SnapshotManager` only uses `Result`, `ContextEnvelope`, `SnapshotStore`. |
| `pipeline_state.py:current()` | Public method not called from `core_pipeline.py` | `core_pipeline.py` always uses `transaction()`. `current()` reads without lock — dangerous for external callers. |
| `_rollback_with_reason` / `_rollback_and_consume` | Near-duplicate logic (15 lines each) | Only difference is `consume_last()`. One internal helper would eliminate the duplication. |

---

## DESIGN CONCERNS

**Rollback depth is 1 and only for contradiction paths.**  
Design doc says "Roll back to last clean snapshot." The implementation stores only the current step's snapshot and deletes prior ones. Manual `rollback()` cannot traverse clean history (see BUG-01). If the intent is one-step rollback only, document it explicitly and make `rollback()` succeed by keeping the previous step's snapshot.

**`_previous_envelopes` grows unboundedly for clean pipelines.**  
`archive_and_set` appends but the list is never pruned for clean steps. After N clean steps: N-1 envelope objects in memory. If rollback depth is intentionally 1, the list should cap at 1 entry.

**`AgentOutput.__post_init__` rejects pure tool-call responses.**  
`not self.text and not self.structured` raises if an agent returns only tool calls. `tool_calls` is a field but not checked. A tool-use-only agent response is legitimate.

**`SnapshotManager` is a transparent wrapper with no added logic.**  
`save` and `load` both delegate to `SnapshotStore` unchanged. `CoreRelayPipeline` already holds `_snapshot_store`. The wrapper adds indirection with no benefit.

**`_apply_manifest` couples validation with rollback.**  
On validation failure it calls `_rollback_with_reason` — mixing two concerns. Validation failures and rollback decisions belong in different layers (see BUG-02).

---

## SCOPE CREEP — NONE FOUND

All implemented code maps cleanly to v0.1–v0.3 design doc scope:
- v0.1: Context broker, handoff validator, snapshot store ✓
- v0.2: Hard-cap token budget, slice packager v2, agent manifests ✓
- v0.3: Universal adapter layer (LangChain, CrewAI, AutoGen, Raw SDK, Local) ✓
- v0.4+ (async fork-join), v0.5 (audit log/OTEL/CLI), v0.6 (Redis/Postgres/S3): correctly absent ✓

---

## PRIORITY ORDER FOR FIXES

| Priority | Bug | Reason |
|---|---|---|
| 1 | BUG-02 `_apply_manifest` wrong error code | Callers switch on `Failure.code` — always wrong branch |
| 2 | BUG-01 `rollback()` broken | Core feature non-functional for clean pipelines |
| 3 | BUG-03 `InvalidSnapshotIdError` unhandled | Any corrupted index crashes instead of failing gracefully |
| 4 | BUG-04 ghost index entries | `get_latest_snapshot` returns wrong result after failed write |
| 5 | BUG-07 hallucination message | Misleads users investigating false positives |
| 6 | BUG-08 `RecencySlicePacker` early exit | Agent gets empty context when older sections would fit |
| 7 | BUG-05 `_finalize_step` state mutation order | Low probability but unrecoverable when triggered |
| 8 | BUG-06 snapshot save failure inconsistency | State diverges in a way that's hard to detect |
| 9 | TEST-01 `.reason` without isinstance | Hides future regressions |
| 10 | TEST-03 vacuous assertion | Tests nothing |
| 11 | BUG-09 `local_model.py` KeyError | Confusing error on malformed API response |
| 12 | Rule violations (2.1, 3.2, 5.1, etc.) | Code quality / type safety |
| 13 | Dead code cleanup | Misleads future readers |
