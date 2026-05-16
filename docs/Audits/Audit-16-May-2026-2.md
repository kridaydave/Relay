# Ruthless Code Review: Relay v0.4.1 (Second Pass)
**Date:** 16 May 2026
**Reviewer:** opencode (Ruthless Reviewer Mode)
**Version:** Relay v0.4.1
**Scope:** All 28 source files under `src/relay/`, 20 test files under `tests/`, docs, config.

---

## Executive Summary

**Grade: B−** (passing but with significant issues that undermine reliability guarantees)

The codebase has strong architecture, good test coverage (315 passing), and clean mypy compliance. However, it suffers from **5 critical bugs**, **8 hard rule violations**, and pervasive mediocre code patterns that directly contradict the project's stated design principles ("trust", "determinism over cleverness", "Result types are the contract").

The most alarming patterns: `_dict_to_envelope` can raise instead of returning `Failure` (violating the core safety contract), `assert` is used in production join-strategy code (disabled under `-O`), and fork validation compares partial outputs against full pre-fork payloads (guarantees false contradictions in parallel steps).

---

## Section 1: Critical Bugs (Must Fix Before Next Release)

### 1.1 `_dict_to_envelope` raises instead of returning `Failure` — violates Rules 9, 13
**File:** `src/relay/snapshot.py:383–398`
**File:** `src/relay/envelope.py:82–94`

The `_dict_to_envelope` method constructs `ContextEnvelope(...)` directly, which triggers `__post_init__`. If a stored snapshot is corrupted (step=0, negative budget counts, etc.), the `raise ValueError` bubbles up as an **unhandled exception**. The try/except in `load_snapshot` only catches `FileNotFoundError`, `json.JSONDecodeError`, and `OSError` — the ValueError from `__post_init__` escapes.

**Why it's unacceptable:** The Coding Rules (Rule 13) explicitly mandate `_dict_to_envelope` must return `Result`, never raise. Corrupted snapshot data is an **operational error**, not a programmer error. An attacker who can write to the snapshot directory (or a bug in a previous version that wrote invalid data) will crash the pipeline instead of getting a clean `Failure`.

**Fix:** Move `__post_init__` validation out of the constructor or wrap the `ContextEnvelope(...)` construction in a try/except that catches `ValueError` and returns `Failure`.

---

### 1.2 `assert` in production code — disabled under `-O`
**File:** `src/relay/parallel/join.py:78–80`
```python
def _confidence(r: ForkResult) -> float:
    assert r.validation is not None
    return r.validation.confidence_score
```

**Why it's unacceptable:** Python's `-O` flag strips all `assert` statements. If a production pipeline runs with optimization (common in Docker containers, deployment scripts, `PYTHONOPTIMIZE`), this precondition check vanishes. The next line `r.validation.confidence_score` raises `AttributeError` instead of returning a meaningful `Failure`.

**Fix:** Replace with explicit check: `if r.validation is None: return Failure(...)`. Never use `assert` for runtime validation in library code.

---

### 1.3 Fork validation compares partial output against full pre-fork payload — guaranteed false contradictions
**File:** `src/relay/parallel/fork_runner.py:75–79`
**File:** `src/relay/validator.py:286–305, 307`

`_run_single_fork` validates a fork's partial output against the **complete** pre-fork envelope. A fork only writes to its `manifest.writes` sections. The validator's `_check_critical_keys_missing` flags all pre-fork keys not in the fork output as "removed" — even though the fork was never supposed to preserve them.

**Why it's unacceptable:** This guarantees false `has_contradiction=True` results for ANY parallel step with multiple forks writing to different sections. The UNION merge strategy which is designed for complementary agents will produce unnecessary rollbacks on every run. This is a **design-level bug**, not a minor logic error.

**Fix:** Fork validation must validate only against the fork's manifest-declared read/write boundaries. Either pass a filtered payload (only fork's read keys) or extend the validator to accept a manifest scope.

---

### 1.4 `RelevanceSlicePacker.pack` passes non-string values to `EmbeddingProvider.embed(text: str)`
**File:** `src/relay/slicer/packers.py:123`
```python
section_embeddings = {
    key: self.provider.embed(text) for key, text in payload.items()
}
```

`payload` is `dict[str, Any]` — values can be nested dicts, lists, numbers. But `EmbeddingProvider.embed` expects `str` (line 21 of `providers.py`). A section like `{"entities": ["Apple", "Microsoft"]}` passes a list to `embed()`.

**Why it's unacceptable:** This will either crash with a `TypeError` or produce garbage embeddings depending on the provider implementation. The type system does not catch this because `payload` is typed as `dict[str, Any]`. This is undetected at call time.

**Fix:** Serialize non-string values to JSON before embedding: `self.provider.embed(json.dumps(text) if not isinstance(text, str) else text)`. Add type guards.

---

### 1.5 Race condition: stale envelope exposed between commit and fork-metadata update
**File:** `src/relay/core_pipeline.py:518, 537–538`

`execute_step_with_manifest` calls `_finalize_step` → `self._state.archive_and_set(new_envelope)` on line 518 (committing the envelope). Then fork metadata is computed (lines 522–536). Then `self._state.set_current(signed)` on line 538 overrides with the metadata-enriched envelope.

Between lines 518 and 538 (under the same transaction lock but after `_finalize_step` releases it), another thread calling `get_current_envelope()` gets the stale envelope without fork metadata. The state is inconsistent.

**Why it's unacceptable:** The design doc says this is "advisory under concurrent load" but the window is wider than necessary. The documentation doesn't warn about this specific window. A caller who reads fork metadata post-step will get incorrect results.

**Fix:** Fold the fork-metadata update into the same atomic block as the step commit, or use a two-phase approach with a pending update flag.

---

## Section 2: Hard Rule Violations

### 2.1 Rule 8 (Layered imports) — Private API imports from higher layers
- `src/relay/snapshot.py:15` — imports `_validate_pipeline_id` (private) from `envelope.py`
- `src/relay/core_pipeline.py:17` — imports `_run_single_fork` (private) from `fork_runner`
- `src/relay/core_pipeline.py:18` — imports `_agent_output_to_payload` (private) from `parallel.types`
- `src/relay/parallel/__init__.py:7,9` — imports private `_run_single_fork` and `_agent_output_to_payload` but does NOT export them in `__all__`

**Why it's unacceptable:** The underscore prefix is Python's convention for "internal implementation detail." Importing private symbols across module boundaries means refactoring these modules silently breaks callers. The parallel `__init__` imports private symbols but hides them from `__all__`, creating a contradictory API surface.

**Fix:** Either make these functions public (remove `_` prefix) and export them in `__all__`, or move the shared logic to a public utility module. The layered import rule exists to prevent exactly this pattern.

---

### 2.2 Rule 9 (Result types are the contract) — `transaction()` raises `RuntimeError` on re-entrance
**File:** `src/relay/pipeline_state.py:60–61`

`raise RuntimeError("Re-entrant lock access detected")` is on a public API path (`with self._state.transaction()`). A developer who accidentally nests transactions gets an exception, not a `Failure`.

**Why it's unacceptable:** The entire error-handling philosophy of the project is "Result types, no exceptions." A lock re-entrance is debatably a programmer error, but it occurs at runtime during a public API call. The consistency argument demands either returning `Failure` or documenting it as a hard crash.

---

### 2.3 Rule 13 (`_dict_to_envelope` must return `Result`) — See Critical Bug 1.1

---

### 2.4 Rule 14 (Heuristics must say they are) — No docstring
**File:** `src/relay/validator.py:241` — `_extract_entities` has no docstring labeling it as heuristic.

**Why it's unacceptable:** Every heuristic must use "approximates" or "estimates" in its docstring. Without it, callers treat the output as exact. The entity extraction is a heuristic (stop-word filtering, entity-name heuristics) that could produce false positives/negatives.

---

### 2.5 Rule 1.3 (Module docstrings) — Missing or incomplete module docstrings
- `src/relay/runners/__init__.py:1` — has a docstring but it says "Adapter implementations". The three-line format (summary, Owns, Does NOT) is missing.
- `src/relay/runners/langchain.py`, `crewai.py`, `autogen.py`, `raw_sdk.py`, `local_model.py` — all have docstrings but only `raw_sdk.py` follows the three-line format. The others are single-line.

**Fix:** All 28 modules must have the three-line format. Currently only about 60% comply.

---

### 2.6 Rule 5.1 (Resource lifecycle/Closeable protocol) — `CoreRelayPipeline` has no `close()` method
**File:** `src/relay/core_pipeline.py`

The class has `__enter__`/`__exit__` but no `close()` method that satisfies the `Closeable` protocol (as defined in the Coding Rules).

**Why it's unacceptable:** Rule 5.1 explicitly says "Every resource has an explicit owner and cleanup path" and references the Closeable protocol. If the pipeline holds no resources to close, the `close()` method should still exist as a no-op for the protocol to be satisfied by future subclasses or wrappers.

---

### 2.7 Rule 9.1 (Default signing secret) — `ContextBroker.__post_init__` logic is fragile in deserialization path
**File:** `src/relay/context_broker.py:25`

Post_init checks `len(secret) < 32` and raises `ValueError`. This is correct per the rule, but `__post_init__` is called during `_dict_to_envelope` path (see bug 1.1). If someone serializes a ContextBroker, it raises during deserialization.

---

### 2.8 Rule 7.2 (Every public function has a test) — Missing failure-path tests
See Section 4: Test Gaps for details. Multiple `Result`-returning functions lack tests for their `Failure` codes.

---

## Section 3: Code Quality / Mediocre Code

### 3.1 Silent `OSError: pass` in three cleanup blocks
**File:** `src/relay/snapshot.py:94–97, 103–105, 218–222`

Three separate `except OSError: pass` blocks silently swallow filesystem errors during cleanup. If cleanup fails, the developer gets **zero signal**. No logging, no warning, no accumulated error state.

**Fix:** At minimum log a warning. The project has no logging infrastructure, which is itself a gap for a library that claims observability as a design goal (v0.5 roadmap).

---

### 3.2 `TiktokenCounter` is a lie when tiktoken is absent
**File:** `src/relay/budget/token_counter.py:83–85`
```python
TiktokenCounter: type[TokenCounter] = _TiktokenCounter
except ImportError:
    TiktokenCounter = HeuristicCounter
```

A user who reads `TiktokenCounter` in documentation or code and imports it gets a `HeuristicCounter` using `len(text)//3` instead of BPE tokenization. The name is factually misleading.

**Fix:** Either name it `TokenCounter` (automatic resolution: tiktoken if available, heuristic otherwise) or export both as separate names and let the user choose.

---

### 3.3 Dead/unreachable code paths
1. `src/relay/envelope.py:39–42` — `if not pipeline_id:` is dead; the regex `{1,128}` already rejects empty strings.
2. `src/relay/core_pipeline.py:210–213` — `if budget_used < 0:` is provably unreachable (budget_used comes from validated envelope fields).
3. `src/relay/snapshot.py:198–202` — unreachable `if not isinstance(snapshot_id, str)` check against a locally-generated UUID hex string.
4. `src/relay/snapshot.py:283,292,301` — redundant `value is None or not isinstance(value, X)` checks. `isinstance(None, X)` is always `False`.

These code paths require testing (Rule 7.2) despite being unreachable, wasting test authoring and execution time.

---

### 3.4 `object.__setattr__` hack for frozen dataclass initialization
**File:** `src/relay/runners/local_model.py:42`

`object.__setattr__(self, "base_url", base_url)` in `__post_init__` is fragile. If the field is renamed but `__post_init__` is not updated, this silently sets a non-existent attribute. A `__init__`-level validation via `__init_subclass__` or a `@classmethod` factory would be cleaner.

---

### 3.5 Entity extraction pushes dead strings back onto stack
**File:** `src/relay/validator.py:262–282`

The stack-based JSON traversal pushes every value back onto the stack after processing leaf strings. For a flat dict of 50 string values, 50 strings are pushed and immediately popped — doubling work for leaf nodes. A simple `continue` after `entities.append(text)` would avoid dead pushes.

---

### 3.6 `_apply_first_wins` silently discards exceptions
**File:** `src/relay/parallel/join.py:115–116`
```python
except Exception:
    continue
```

Task exceptions from fork execution are silently discarded. A fork that raises an exception is treated identically to a fork that fails validation. The error information is lost with no way to debug why a fork failed.

**Fix:** Store the exception information in `ForkResult` or at least log a warning.

---

### 3.7 Test `test_concurrent_step_execution` mocks only half the chain
**File:** `tests/unit/test_pipeline.py:129–171`

Mocks `create_initial_envelope` but not `create_next_envelope`. The mock returns a hardcoded step=1 envelope while the real `pipeline._pipeline_id` is a random UUID. Threads calling `execute_step()` invoke the **real** `create_next_envelope()` with mismatched state (envelope pipeline_id != `_pipeline_id`).

**Why it's unacceptable:** This test proves nothing about concurrent safety of the actual pipeline logic. It's testing a Frankenstein state that can never occur in production.

---

### 3.8 Global state mutation in test
**File:** `tests/unit/test_budget.py:99–115`

Monkeypatches `builtins.__import__`, pops `tiktoken` from `sys.modules`, calls `importlib.reload()`. This corrupts global state for all subsequent tests. Any test importing from `relay.budget.token_counter` after this gets a potentially stale module.

**Fix:** Isolate in its own process or subprocess.

---

### 3.9 Empty test class `TestContextBrokerConstruction`
**File:** `tests/unit/test_context_broker.py:190–191`

A class with `pass` and no test methods. Dead code that wastes CI time and creates a false sense of coverage.

---

### 3.10 `isinstance(result, (Success, RollbackSuccess))` too broad
**File:** `tests/unit/test_pipeline.py:107`

The rollback test accepts both `Success` and `RollbackSuccess`. If the rollback logic is refactored to return `Success` instead of `RollbackSuccess` (defeating the purpose of having a `RollbackSuccess` type), this test silently passes.

---

### 3.11 Duplicate `TestContextEnvelope` class across two test files
**File:** `tests/unit/test_snapshot.py:530–549` and `tests/unit/test_envelope.py:274–289`

Both test that `ContextEnvelope` is a frozen dataclass. Identical logic, different file. Double maintenance burden for a trivial invariant that's enforced by the type system.

---

## Section 4: Test Gaps

| Missing Test | File | Impact |
|---|---|---|
| `_check_budget` `INVALID_TOKEN_COUNT` path | `core_pipeline.py:210–214` | Rule 7.5 violation |
| `_apply_union` `agent_output is None` invariant failure path | `join.py:83–89` | Rule 7.5 violation |
| `_apply_vote` `agent_output is None` invariant failure path | `join.py:83–89` | Rule 7.5 violation |
| `HeuristicCounter` ground-truth benchmark against known BPE | `token_counter.py` | Rule 6.2 — heuristic accuracy unguaranteed |
| `FixedForkRunner` protocol `isinstance` check | `test_parallel/conftest.py` | Rule 7.6 — test double may drift from protocol |
| `unwrap_or` with `RollbackSuccess` | `types.py` | Documented contract untested |
| `_extract_entities` depth limit test | `validator.py` | Recursion limit not tested |
| Fork metadata validation on corrupted snapshots | `snapshot.py:383` | Deserialization robustness untested |
| `create_context_broker` `INVALID_SECRET` code assertion | `test_context_broker.py:14–18` | Asserts reason string but not error code |
| `_apply_vote` `ALL_FORKS_FAILED` code | `test_parallel/test_join.py` | Failure code not asserted |

---

## Section 5: Documentation & Configuration Issues

1. **`README.md:277`** — envelope example shows `"relay_version": "0.3.0"` instead of `"0.4.1"`
2. **`core_pipeline.py:244`** — comment has double word: "lock is is non-reentrant"
3. **`docs/version-0.4/v0.4-plan.md`** — tests reference `ErrorCode.INVALID_JOIN_STRATEGY` but actual code uses `INVALID_STATE`. Plan not updated to match v0.4.1 changelog.
4. **`docs/version-0.3/v0.3-plan.md`** — references `callable=` field name which was renamed to `fn` in v0.3.1
5. **`mypy.ini:36`** — `[mypy-crewai]` missing `.*` suffix unlike all other `[mypy-*.*]` entries
6. **`AGENTS.md:14`** — layer dependency list missing `parallel/` package (v0.4 addition)
7. **`pyproject.toml:65–68`** — dead mypy config (duplicated in `mypy.ini` which takes precedence)
8. **`.gitignore`** — duplicate `dist/` entry (lines 9 and 47)
9. **`parallel/__init__.py`** — imports `_agent_output_to_payload` but does NOT export it in `__all__`, creating a contradictory API surface
10. **`runners/__init__.py`** — eagerly imports all adapter classes at module level; violates lazy-loading convention described in AGENTS.md
11. **`envelope.py:21`** — `RELAY_VERSION = "0.4.1"` hardcoded rather than centralized in `__init__.py`. Potential drift during development.
12. **`tests/unit/test_runners/test_protocol.py:38,67`** — `# type: ignore[misc]` in test code (mypy strict violation extends to tests)

---

## Section 6: Detailed Fix Plan (Priority Order)

### Immediate (blocking release)
1. **`snapshot.py:383–398`** — Wrap `ContextEnvelope(...)` construction in try/except ValueError → return `Failure`. Add to `load_snapshot` catch list.
2. **`join.py:78–80`** — Replace `assert r.validation is not None` with `if r.validation is None: return Failure(reason=..., code=...)`.
3. **`fork_runner.py:75–79`** — Scope validation to only the fork's manifest-declared keys. Either filter payload before validation or extend validator API to accept a manifest scope.
4. **`packers.py:123`** — Add type guard: `json.dumps(text) if not isinstance(text, str) else text` before calling `embed()`.

### High (next release)
5. **`snapshot.py:15, core_pipeline.py:17–18, parallel/__init__.py:7,9`** — Underscore-to-public rename for `_validate_pipeline_id`, `_run_single_fork`, `_agent_output_to_payload`. Update all `__all__` exports.
6. **`core_pipeline.py:518–538`** — Eliminate race window by setting fork metadata in same transaction as step commit.
7. **`pipeline_state.py:60–61`** — Either return `Failure` or document `RuntimeError` as intentional programmer-error hard crash. If keeping hard crash, add to docstring.
8. **`validator.py:241`** — Add docstring to `_extract_entities` labeling it as heuristic with "approximates" language.

### Medium (next sprint)
9. **`token_counter.py:83–85`** — Rename `TiktokenCounter` to `AutoTokenCounter` or restructure to avoid misleading name.
10. **`snapshot.py:94–97,103–105,218–222`** — Replace `except OSError: pass` with `logger.warning(...)` or equivalent.
11. **`join.py:115–116`** — Store exception info in ForkResult instead of silent `continue`.
12. **`core_pipeline.py:210–213`** — Remove unreachable `budget_used < 0` check.
13. **`envelope.py:39–42`** — Remove dead `if not pipeline_id` validation.
14. **`local_model.py:42`** — Replace `object.__setattr__` with classmethod factory pattern.
15. **`runners/__init__.py`** — Lazy-import adapter classes (each adapter module only loaded when first used).
16. **`validator.py:262–282`** — Add `continue` after `entities.append(text)` to avoid dead stack pushes on leaf nodes.
17. **`core_pipeline.py`** — Add `close()` method to satisfy Closeable protocol per Rule 5.1.

### Test fixes
18. **`test_pipeline.py:129–171`** — Rewrite concurrent test to either mock entirely or not at all.
19. **`test_budget.py:99–115`** — Isolate global-state-mutating test in subprocess.
20. **`test_context_broker.py:190–191`** — Delete empty test class `TestContextBrokerConstruction`.
21. **`test_pipeline.py:107`** — Narrow assert to `isinstance(result, RollbackSuccess)` only.
22. Add missing failure-path tests (see Section 4 — 10 test gaps).
23. **`test_snapshot.py:530–549`** — Delete duplicate `TestContextEnvelope` class.

### Documentation
24. Fix stale version in README.md envelope example (`0.3.0` → `0.4.1`).
25. Fix typo in core_pipeline.py:244 ("is is" → "is").
26. Update v0.4-plan.md to match actual error codes.
27. Update AGENTS.md layering to include `parallel/`.
28. Fix `mypy.ini` crewai section to use `[mypy-crewai.*]`.
29. Clean up duplicate `dist/` in `.gitignore`.
30. Remove dead `[tool.mypy]` from `pyproject.toml`.
31. Centralize `RELAY_VERSION` in `__init__.py`.

---

## Section 7: Prevention Strategy

### Systemic Issues Identified

The following root causes explain WHY these bugs were introduced despite good test coverage and a clear design doc:

1. **No `__all__` enforcement** — Modules without `__all__` leak implementation details. Importing private symbols across module boundaries is possible but undocumented. **Fix:** Add `__all__` to every public module. Consider a CI check that flags imports of underscore-prefixed names from other modules.

2. **No invariant-based testing** — The `_dict_to_envelope` / `__post_init__` interaction was never tested with corrupted data. **Fix:** Add fuzz-style tests that feed corrupted JSON to `_dict_to_envelope` and assert it returns `Failure`. Property-based testing (Hypothesis) for envelope deserialization.

3. **`assert` in production code** — Multiple modules use `assert` for runtime validation. **Fix:** Add a CI grep that flags `assert ` in production code (`.py` files not in `tests/`). The only legitimate use of `assert` in production is for TypeGuard annotations.

4. **Partial mocking in concurrent tests** — Tests that mix real and mocked code produce untrustworthy results. **Fix:** Establish a rule: concurrent tests must either mock ALL pipeline internals or NONE. No hybrid mocking.

5. **No logging infrastructure** — Silent `except: pass` blocks cannot provide diagnostics. **Fix:** Add a structured logger (`logging.getLogger("relay")`) early in v0.5 road map. Even if output is not the primary logging backend, the logger exists for diagnostic purposes.

6. **No review checklist for private API imports** — The code review process did not catch that `_run_single_fork` and `_agent_output_to_payload` are private APIs being imported across module boundaries. **Fix:** Add to pre-commit review checklist: "No imports of underscore-prefixed names from other modules."

7. **Documentation drift** — Design docs, README examples, and actual code have version and API mismatches. **Fix:** Automated docstring/example tests (doctest) or a CI step that checks README code blocks parse correctly.

8. **No cross-module boundary testing** — The interaction between `_dict_to_envelope` and `ContextEnvelope.__post_init__` spans two modules with different error-handling strategies (Result vs raise). **Fix:** Add integration tests specifically targeting module boundary interactions. A pre-merge CI step that runs with `-O` to catch stripped assertions.

### Process Changes

| Change | Owner | When |
|--------|-------|------|
| Add `__all__` enforcement to CI (grep for missing `__all__` in `src/relay/`) | DevOps | Next sprint |
| Add `assert` grep to pre-commit hook | DevOps | Immediate |
| Add Hypothesis-based fuzz test for `_dict_to_envelope` | Test team | Next sprint |
| Add "no private import from other module" to review checklist | All devs | Immediate |
| Run integration tests with `python -O` flag | CI | Next sprint |
| Add logging (`logging.getLogger("relay")`) to all `except` blocks | Dev team | v0.5 |
| Add stale-doc check: version numbers in docs match `__version__` | CI | Next sprint |
| Flag unused/dead code paths in PR review | All devs | Ongoing |

### Verification Gates for Future Audits

| Gate | Mechanism |
|------|-----------|
| Production asserts | `rg "assert " src/relay/ --include '*.py' --no-filename` must return empty |
| Private imports | `rg "from relay\.\w+ import _" src/relay/ --include '*.py'` — flag ALL underscore imports |
| Unreachable code | Coverage report showing 100% branch coverage on guard clauses |
| Docstring format | Custom mypy plugin or CI script checking three-line docstring format on all modules |
| Version consistency | `grep -r "$(python -c 'import relay; print(relay.__version__)')" docs/` in CI |

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Source files reviewed | 28 |
| Test files reviewed | 20 |
| Total lines of source | ~6,293 |
| Total tests | 315 |
| Tests passing | 315 (100%) |
| mypy --strict errors | 0 |
| **Critical bugs** | **5** |
| **Rule violations** | **8** |
| **Code quality issues** | **11** |
| **Test gaps** | **10** |
| **Doc/config issues** | **12** |
| **Total actionable items** | **46** |

---

## Appendix: Comparison with Previous Audit (7 May 2026)

The previous review (Ruthless-Code-Review.md) identified 7 issues, all of which have been fixed:
- ✅ Lock leaking via `current_and_lock()` → now uses `transaction()` context manager
- ✅ Control flow via assertions → replaced with `Failure` returns
- ✅ JSON canonicalization fragility → uses explicit separators
- ✅ TOCTOU in snapshot store → removed exists() check
- ✅ Recursive entity extraction DoS → iterative with `MAX_EXTRACTION_DEPTH`
- ✅ Circular imports in validator → uses TYPE_CHECKING
- ✅ Unnecessary wrapper indirection → cleaned up

**V0.4 introduced new issues** in the parallel execution module (fork_runner, join, parallel types) that did not exist in v0.3. All 5 critical bugs and most rule violations are in the v0.4 parallel code.

---

*"One hallucinating agent silently corrupts the shared context" — the project's own problem statement. 5 of the bugs found here would do exactly that.*
