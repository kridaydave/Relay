# ⚡ RUTHLESS CODE REVIEW — Relay v0.5.0
**Date:** 18 May 2026
**Reviewer:** Ruthless Reviewer (AI) — no sugarcoating, no mercy
**Scope:** Full codebase (src/relay/, tests/, runners/, budget/, slicer/, parallel/, config, CI, docs)

---

## EXECUTIVE SUMMARY

**Grade: C+ (Mediocre — significant issues remain despite 12 prior audits)**

The codebase has a **strong architectural vision** (layered modules, frozen dataclasses, Result-based error handling, Protocol-based DI) and many correct patterns. However, this is a codebase that **has gone through 12 audits in 12 days** and STILL has:

- **3 CRITICAL security/correctness bugs** in production code
- **6 CRITICAL holes in quality enforcement** (CI, mypy config)
- **Production `assert` statements** that vanish with `-O`
- **Budget enforcement that doesn't actually enforce**
- **A slice packer strategy that ignores the budget entirely**
- **Dead code that runs after cancellation** in the parallel join path
- **Tests that prove nothing** (bare assert on Result types — always passes)
- **Silent error swallowing** in snapshot cleanup

The same categories of issues recur across audits because **automated enforcement is incomplete**. The problem is not the code — it's the **quality system**.

---

## PROJECT BASELINE

| Property | Value |
|----------|-------|
| Language | Python 3.12+ |
| Version | 0.5.0 (code) / 0.5.1 (changelog) — **drift** |
| Approach | Layered middleware, HMAC-signed envelopes, Result[T] errors |
| Tests | ~450 tests across unit + integration |
| Prior audits | 12+ in .planning/audits/ |

### The Law (from AGENTS.md + Coding Rules)
1. `mypy --strict` with zero `# type: ignore` — Rule 2.1
2. Frozen dataclasses for all value types — Rule 2.4
3. Module docstrings: three-line format (Owns/Does NOT) — Rule 8.3
4. Result[T] for operational errors; exceptions only for programmer errors — Rule 3.1
5. Test names are sentences — Rule 7.1
6. Every Result function needs tests for every Failure code — Rule 7.5
7. Lower layers never import upper layers — Rule 1.2
8. Protocols in their own file, not next to implementations — Rule 1.3
9. HMAC via `hmac.compare_digest` — Rule 9.2
10. Pipeline ID validated before filesystem use — Rule 4.3

---

## FINDING REGISTRY — PRODUCTION CODE (src/relay/)

### CRITICAL

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **PC-01** | `envelope.py` | 20 | **CRITICAL** | **Layer violation.** `envelope.py` imports `HeuristicCounter` from `relay.budget.token_counter`. Per AGENTS.md layering: `types.py → envelope.py → snapshot.py → ... → budget/`. Lower layers (`envelope.py`) must NEVER import upper layers (`budget/`). This is a structural architecture violation. |
| **PC-02** | `snapshot.py` | 185-198 | **CRITICAL** | **Broken symlink protection on Windows.** `os.O_NOFOLLOW` defaults to 0 when unavailable, and the `lstat` fallback has a TOCTOU race. On Python <3.13 on Windows, symlink attack protection is completely disabled. |
| **PC-03** | `core_pipeline.py` | 840 | **CRITICAL** | **Production `assert` statement.** `assert winner.agent_output is not None` vanishes under `python -O`. If assertions are disabled, `None` propagates into `agent_output_to_payload()` causing `AttributeError`. Fix: replace with `if winner.agent_output is None: return Failure(...)` |

### HIGH

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **PH-01** | `budget/enforcer.py` | 34-35 | **HIGH** | **Budget enforcement is systematically under-enforced.** `HardCapEnforcer.check()` only validates projected *input* tokens against the budget. Agent *output* tokens are never projected or checked. Example: budget=1000, used=900, slice=50 tokens → check passes (950≤1000). Agent generates 200 output tokens → actual consumption 1100 > 1000. Budget blown by 100 tokens. The hard cap is NOT a hard cap. |
| **PH-02** | `slicer/packers.py` | 87-101 | **HIGH** | **StructuralSlicePacker completely ignores `max_tokens`.** This packer returns ALL sections in `manifest.reads` with zero regard for `manifest.max_tokens`. If reads specifies 10 sections at 5000 tokens but max_tokens=1000, all 5000 are returned. This completely defeats token budget enforcement for this strategy. Contrast with `RecencySlicePacker` (line 72) and `RelevanceSlicePacker` (line 154) which correctly cap at `max_tokens`. |
| **PH-03** | `parallel/join.py` | 132-146 | **HIGH** | **Dead code executed after cancellation.** `_apply_first_wins` builds a `collected: list[ForkResult]` list from cancelled/finished tasks at lines 132-140. The caller at line 185 discards it: `result, _collected = await _apply_first_wins(...)`. The `_collected` variable is never used. The loop iterates all tasks, checks exceptions, and builds results — all for nothing. This runs AFTER task cancellation, adding unnecessary latency. |
| **PH-04** | `runners/crewai.py` | 72 | **HIGH** | **Rule 2.1 violation: `# type: ignore[import-not-found]`.** The project claims "zero suppressions" but has 2 of these in runners. |
| **PH-05** | `runners/autogen.py` | 59 | **HIGH** | **Rule 2.1 violation: `# type: ignore[import-not-found]`.** Same as PH-04. |
| **PH-06** | `slicer/packers.py` | 111 | **HIGH** | **Rule 2.3 violation: missing return type on `__init__`.** `RelevanceSlicePacker.__init__` at line 111 lacks `-> None` return annotation. Every other `__init__` in codebase has it. |
| **PH-07** | `pipeline_rollback.py` | 52 | **HIGH** | **Unchecked Success in rollback path.** `restore_to_previous()` returns `Result[ContextEnvelope]` (union of Success, RollbackSuccess, Failure). It creates `RollbackSuccess`, but caller in `_do_rollback` (line 584) only checks `isinstance(result, Failure)`. Should verify it's RollbackSuccess not plain Success. |
| **PH-08** | `pipeline_state.py` | 109-113 | **HIGH** | **Rule 3.1 violation: raises `IndexError` instead of returning `Failure`.** `consume_last()` is an operational error (no previous envelopes) expressed as an exception. |

### MEDIUM

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **PM-01** | Multiple | - | MEDIUM | **Unused `Any` imports** in `snapshot.py:14`, `envelope.py:18`, `validator.py:8`, `parallel/types.py:10` |
| **PM-02** | `snapshot.py` | 272 | MEDIUM | **Snapshot signature verification uses default staleness.** `verify_signature(envelope, self._signing_secret)` uses default `max_age_seconds=86400` instead of pipeline-configured value. |
| **PM-03** | `snapshot.py` | 139-140 | MEDIUM | **Silent error swallow.** `except OSError: pass` in `_remove_from_index` temp file cleanup. Two other similar blocks were fixed (now have `logger.warning`), but this one remains. |
| **PM-04** | `parallel/fork_runner.py` | 30 | MEDIUM | **Shared mutable validator across concurrent forks.** `HandoffValidator` instance is shared across concurrent `run_single_fork` calls. Docstring says "Stateless HandoffValidator" but this is not enforced. If any mutable state exists, this is a data race. |
| **PM-05** | `parallel/fork_runner.py` | 83-111 | MEDIUM | **Wrong validation order.** Handoff validation runs BEFORE boundary check. Should be boundary first (did agent write to allowed sections?), then content validation. |
| **PM-06** | `budget/enforcer.py` | 23 | MEDIUM | **`Result[None]` conflates two semantically different states.** "Budget OK" and "vacuous check (counter returned 0)" both map to `Success(None)`. Caller cannot distinguish valid check from counter error. |
| **PM-07** | `budget/enforcer.py` | 21 | MEDIUM | **Frozen dataclass holds mutable `counter`.** `HardCapEnforcer` is frozen but `counter` attribute references a potentially mutable object (`_TiktokenCounter` with lazy-loaded `_enc`). Thread-safe only if `counter.count()` is safe. |
| **PM-08** | `runners/registry.py` | 19 | MEDIUM | **`AdapterRegistry` not frozen.** Rule 2.4 says all value types are frozen. Registry is intentionally mutable but this is undocumented inconsistency. |
| **PM-09** | `runners/local_model.py` | 55-75 | MEDIUM | **Code duplication.** `__post_init__` and `create()` classmethod both do `rstrip("/")` and `_validate_base_url()`. Maintenance hazard. |
| **PM-10** | `runners/langchain.py` | - | MEDIUM | **No lazy import; no explicit dependency check.** Docstring claims lazy imports but langchain adapter has no import guard. Non-LangChain objects with `ainvoke` pass silently. |
| **PM-11** | `core_pipeline.py` | 383-385 | MEDIUM | **Budget gap: projection bypassed when `manifest.writes` is empty.** If no write permissions, projected payload is `{}` → 2 bytes → 1 token. Budget check is effectively vacuous for read-only agents. |
| **PM-12** | `core_pipeline.py` | 453, 556 | MEDIUM | **Encapsulation violation.** `self._state._assert_lock_held()` calls private method of another class. Underscore means private. |

### LOW (selected)

`local_model.py:36` — No post-construction SSRF re-validation. `langchain.py` — No `__all__`. `autogen.py:84` — Raw agent object used as dict key (fragile). `autogen.py:77-79` — No timeout on agent call (unlike CrewAI's timeout). `raw_sdk.py:46` — `iscoroutinefunction` fails for `__call__` class instances. `slicer/packers.py:58-61` — Recency sort key non-deterministic for non-digit keys. `slicer/packers.py:15-20` — Re-exports `estimate_tokens` from envelope.py (confusing). `budget/token_counter.py:83-85` — `AutoTokenCounter` is a type alias, not a class, confusing for isinstance checks.

---

## FINDING REGISTRY — TEST SUITE (tests/)

### CRITICAL

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **TC-01** | `test_envelope.py` | 738 | **CRITICAL** | **Completely meaningless assertion.** `assert verify_signature(signed, "a" * 32)` — `verify_signature` returns `Result[None]` which is `Success[None] | RollbackSuccess[None] | Failure`. All three are unconditionally truthy Python dataclasses with no custom `__bool__`. This assertion ALWAYS passes, even when the function returns `Failure`. The test proves NOTHING. Fix: `assert isinstance(verify_signature(...), Success)`. |

### HIGH

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **TH-01** | `test_context_broker.py` | 27-196 | **HIGH** | **Tests mock everything, test nothing.** Every test in `TestCreateInitialEnvelope` and `TestCreateNextEnvelope` patches `create_initial_envelope` and `create_next_envelope` — the EXACT functions they claim to test. They verify the mock was called and return the mock's value. Zero actual `ContextBroker` behavior tested. 7 tests doing mocking framework testing. |
| **TH-02** | `test_pipeline.py` | 129-469 | **HIGH** | **Concurrent tests bypass all real logic.** All 6 concurrent tests patch both `create_initial_envelope` and `create_next_envelope` with mocked envelopes, bypassing validation, rollback, budget enforcement, and snapshotting. They prove "mocked calls don't crash" — not "concurrent access is safe." |
| **TH-03** | `test_envelope.py` | 414-415 | **HIGH** | **Catches generic `Exception` instead of `AttributeError`.** `with pytest.raises(Exception): envelope.step = 2` — frozen dataclasses raise `AttributeError` specifically. Catching `Exception` masks unexpected errors like `TypeError`. |
| **TH-04** | `test_context_broker.py` | - | **HIGH** | **Missing method tests.** `ContextBroker.verify_signature`, `ContextBroker.get_key`, `ContextBroker.close` — zero test coverage. |

### MEDIUM

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **TM-01** | `test_validator.py` | 258, 315-520 | MEDIUM | **Excessive private method testing.** Tests invoke `validator._detect_hallucination`, `_extract_entities`, `_validate_payloads` directly. Tightly coupled to implementation. Refactoring internals breaks tests even if public API stays correct. |
| **TM-02** | `test_join.py` | 8-227 | MEDIUM | **Tests private functions instead of public API.** Imports `_apply_union`, `_apply_vote`, `_apply_first_wins` directly. `TestApplyJoinStrategy` only tests invalid strategy — all strategy behavior tested through private functions. |
| **TM-03** | `test_pipeline.py` | 760 | MEDIUM | **Tests private `_apply_manifest` method.** Implementation detail leak. |
| **TM-04** | `test_snapshot.py` | Multiple | MEDIUM | **Unittest-style setup/teardown instead of pytest fixtures.** Boilerplate `tempfile.mkdtemp()` + `shutil.rmtree()` repeated in 10 classes. |
| **TM-05** | `test_budget.py` | 121-138 | MEDIUM | **Fragile subprocess test.** Spawns subprocess to `importlib.reload` with mutated `__import__`. Fragile across Python versions and platforms. |
| **TM-06** | `test_pipeline_rollback.py` | 36-84 | MEDIUM | **Only 3 tests.** Missing edge cases: `consume=True` vs `consume=False`, corrupt snapshot_ids, empty snapshot_ids with valid envelope. |
| **TM-07** | `test_audit_events.py` | 222-271 | MEDIUM | **Hard-coded event type lists.** Manually enumerates 17-18 event types. Adding a new event type won't trigger test failure — new type silently untested. |
| **TM-08** | `test_pipeline.py` / `test_fork_runner.py` | Duplicate | MEDIUM | **Duplicate `agent_output_to_payload` tests** in both files — nearly identical. |

---

## FINDING REGISTRY — CONFIG / CI / DOCS

### CRITICAL

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **CC-01** | `.github/workflows/ci.yml` | 33 | **CRITICAL** | **CI does NOT run `mypy --strict tests/`.** Prior audit found 592 mypy errors in tests. "Fixed" but with zero regression protection. Next bad commit sneaks through silently. The project's most-publicized quality gate is unenforced for half the codebase. |
| **CC-02** | `mypy.ini` | 31-35 | **CRITICAL** | **Source exemptions weaken `--strict`.** `[mypy-relay.budget.token_counter]` and `[mypy-relay.runners.local_model]` both set `disallow_any_expr = False`. These are two source modules where the "no bare Any" rule is deliberately disabled. Rule 2.1 says "zero suppressions" — yet these exist. |
| **CC-03** | `mypy.ini` | 21-23 | **CRITICAL** | **Test exemptions contradict quality claims.** `[mypy-tests.*]` sets `disallow_any_expr = False` and `disallow_any_decorated = False`. If tests truly pass `--strict` now, these are dead config. If they don't, the project is lying about test type safety. |

### HIGH

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **CH-01** | `.github/workflows/ci.yml` | 18 | HIGH | **CI only tests Python 3.12.** `pyproject.toml` declares 3.12 + 3.13 support. 3.13 compatibility is untested. |
| **CH-02** | `.github/workflows/ci.yml` | 13,16 | HIGH | **Deprecated action versions.** `actions/checkout@v3` (should be v4), `actions/setup-python@v4` (should be v5). Node.js 16 deprecation. |
| **CH-03** | multiple | - | HIGH | **No coverage enforcement in CI.** README promises ">80% test coverage". `pyproject.toml` has `[tool.coverage]` configured. CI does not run coverage. `coverage` is not even a dev dependency. The claim is unverifiable. |
| **CH-04** | `.pre-commit-config.yaml` | - | HIGH | **Missing critical hooks.** (a) `mypy --strict tests/` — no test type regression protection. (b) No `assert` check in production code — despite prior audit recommendation. (c) No private-API import check. |
| **CH-05** | `pyproject.toml` | 31 | HIGH | **Dev dependencies unpinned.** `dev = ["pytest", "pytest-asyncio", "anyio", "mypy"]` — no version constraints at all. A new major release could break CI. `coverage` is missing despite being configured in `[tool.coverage]`. |

### MEDIUM

| ID | File | Line | Severity | Finding |
|----|------|------|----------|---------|
| **CM-01** | `mypy.ini` | 5 | MEDIUM | `warn_unused_configs = False` hides dead config sections. |
| **CM-02** | `README.md` | 338 | MEDIUM | **Broken link.** Links to `docs/Relay%20Design%20Document.txt` — actual file is `.md`. |
| **CM-03** | `AGENTS.md` | 14 | MEDIUM | **Missing `audit/` in dependency chain.** `core_pipeline.py` imports from `relay.audit` extensively but `audit/` is not listed in the documented layering. |
| **CM-04** | `src/relay/types.py` vs `CHANGELOG.md` | 32 | MEDIUM | **Version drift.** Code says `"0.5.0"`, changelog says `"0.5.1"`. |
| **CM-05** | `docs/success.md` | 94-101 | MEDIUM | **Unverifiable claims.** Claims "A" grade, "363 tests", "100% type safety". Most recent audit gave B-. Test count is stale (actual: ~450). |
| **CM-06** | `docs/untracked/untracked-files.md` | - | MEDIUM | **Stale document.** References `pipeline_snapshot.py` which was deleted. |
| **CM-07** | `.planning/audits/*.md` | 12 files | MEDIUM | **Audit fatigue.** 12 audits in 12 days. Same categories recur because automated enforcement is incomplete. |

---

## CROSS-CUTTING THEMES

### Theme 1: Budget Enforcement is a Lie

The "hard cap" has at least 4 independent bypass mechanisms:
1. **`HardCapEnforcer.check()`** only checks input cost (PH-01)
2. **`StructuralSlicePacker`** ignores `max_tokens` entirely (PH-02)
3. **Empty `manifest.writes`** → projected cost = 1 token → bypass (PM-11)
4. **Heuristic `len(text)//3`** systematically underestimates (~0.33 vs ~0.37 actual) (C1 from sub-report)

Any one of these makes the budget advisory rather than hard. Combined, they gut it.

### Theme 2: Enforcement vs. Aspiration

The project has **excellent written standards** (Coding Rules, AGENTS.md). But automated enforcement is incomplete:
- mypy `--strict` not run on tests (CC-01)
- Source exemptions weaken strict (CC-02, CC-03)
- No coverage enforcement (CH-03)
- Missing pre-commit hooks (CH-04)
- `warn_unused_configs = False` hides stale config (CM-01)

### Theme 3: "Zero Suppressions" is False

The project claims `# type: ignore` zero suppressions. Reality:
- 2 `# type: ignore[import-not-found]` in source code (PH-04, PH-05)
- 1 `# type: ignore[misc]` in test code (line 415)
- 2 source modules with `disallow_any_expr = False` (CC-02)
- All test files with `disallow_any_expr = False` (CC-03)

### Theme 4: The Plateau of Diminishing Audit Returns

12 audits in 12 days. The first few found systemic issues and drove major fixes. Recent audits find the same categories of issues: mypy config gaps, version drift, broken links, silent error swallows. This is a **quality system problem**, not a code problem. Each issue gets fixed, but the root cause (incomplete automation) persists.

---

## BUGS vs. RULE VIOLATIONS vs. SMELLS

### True Bugs (will cause runtime failure)
1. `assert winner.agent_output is not None` in production → AttributeError under -O (PC-03)
2. Bare `assert verify_signature(...)` → never fails (TC-01)
3. Budget under-enforcement → pipeline exceeds budget silently (PH-01)

### Rule Violations (violate stated standards)
1. Layer violation in envelope.py (PC-01)
2. `# type: ignore` suppressions (PH-04, PH-05)
3. Missing return annotation (PH-06)
4. Mypy config exemptions (CC-02, CC-03)
5. Silent error swallow (PM-03)

### Code Smells (structural/design problems)
1. Production assert in core_pipeline.py (PC-03)
2. Dead code in join.py (PH-03)
3. Mutable reference in frozen dataclass (PM-07)
4. Test doubles testing themselves (TH-01)
5. Excessive private method testing (TM-01, TM-02)

---

## SUMMARY COUNTS

| Section | CRITICAL | HIGH | MEDIUM | LOW | TOTAL |
|---------|----------|------|--------|-----|-------|
| Production Code | 3 | 8 | 12 | ~5 | ~28 |
| Test Suite | 1 | 4 | 8 | ~3 | ~16 |
| Config/CI/Docs | 3 | 5 | 7 | ~4 | ~19 |
| **TOTAL** | **7** | **17** | **27** | **~12** | **~63** |

---

## REMEDIATION PLAN

### Phase 1 — Fix the Criticals (do this week)

| Order | Issue | Fix | Effort |
|-------|-------|-----|--------|
| 1 | PC-01: Layer violation | Move `HeuristicCounter` to a new `relay._utils` module or inline the `len(text)//3` calculation | 10 min |
| 2 | PC-03: Production assert | Replace with `if winner.agent_output is None: return Failure(...)` | 5 min |
| 3 | TC-01: Meaningless test | Change to `assert isinstance(verify_signature(...), Success)` | 2 min |
| 4 | CC-02: Source exemptions | Remove `disallow_any_expr = False` from mypy.ini, fix resulting type errors | 2-4 hrs |
| 5 | CC-03: Test exemptions | Same approach for `[mypy-tests.*]` | 2-4 hrs |
| 6 | CC-01: CI gap | Add `mypy --strict tests/` to CI workflow | 30 min |

### Phase 2 — Fix the Highs (do this sprint)

| Order | Issue | Fix | Effort |
|-------|-------|-----|--------|
| 7 | PH-01: Budget enforcement | Add output token projection to `HardCapEnforcer.check()` | 2 hrs |
| 8 | PH-02: StructuralSlicePacker | Implement `max_tokens` capping (same as RecencySlicePacker) | 1 hr |
| 9 | PH-03: Dead code | Remove `collected` list computation from `_apply_first_wins` | 15 min |
| 10 | CH-05: Unpinned deps | Add minimum version pins | 15 min |
| 11 | CH-03: Coverage enforcement | Add `coverage` to dev deps, add CI coverage step | 1 hr |
| 12 | CH-04: Pre-commit hooks | Add test mypy check, assert check, private-API import check | 1 hr |
| 13 | CH-01: 3.13 CI | Add matrix strategy | 30 min |

### Phase 3 — Systemic Prevention (quality system)

| Issue | Change | Why |
|-------|--------|-----|
| Audit fatigue | **Replace manual audits with automated gates.** Every finding category should have a CI check. | 12 audits proved manual reviews alone don't prevent regression |
| Rule 2.1 enforcement | Add CI step: `grep -r "type: ignore" src/relay/` → nonzero exit = fail | Zero suppressions must be machine-enforced |
| Rule 7.5 enforcement | Add CI step: script that extracts Failure codes and checks test coverage | Automated failure path audit |
| Doc freshness | Add CI step: check `__version__` matches CHANGELOG, check `mypy.ini` has no `warn_unused_configs = False` | Version drift caught immediately |
| Remove `.planning/audits/` | Archive audits to git history; keep only latest automated report | 12 audit files are noise, not signal |
| Snapshot security | Replace `os.O_NOFOLLOW` fallback with explicit `lstat` + `open` pattern that atomically checks | PC-02 fix |
| Symlink protection | Add Windows CI job specifically testing on Windows | Platform-specific security |

### Long-term Architecture Improvements

| Change | Why |
|--------|-----|
| Move `HeuristicCounter` to shared utility layer | Fixes layer violation permanently |
| Make `HardCapEnforcer` use actual tokenizer for hard cap, heuristic for pre-check | Budget becomes actual hard cap |
| Replace bare `assert` in production with explicit `Failure` returns | Eliminate entire class of -O bugs |
| Make all adapters `@dataclass(frozen=True)` | Consistency with Rule 2.4 |
| Add `__all__` to all runner adapter modules | Clean API surface |
| Add `verify_signature`, `get_key`, `close` tests for ContextBroker | Closing coverage gaps |
| Convert unittest-style snapshot tests to pytest fixtures | Consistency, less boilerplate |

---

## FINAL VERDICT

**Relay's architecture is sound. Its execution is mediocre.**

The codebase has a strong vision, correct fundamentals (HMAC, pipeline ID validation, Result pattern, frozen dataclasses), and developers who care enough to do 12 audits. But the quality system has critical gaps:

1. **CI doesn't enforce the standards it claims.** `mypy --strict` on tests is unenforced. Coverage is unenforced. Version drift is undetected.
2. **The budget "hard cap" is soft in 4 independent ways.** Any one is a bug. All four together make the feature misleading.
3. **The "zero suppressions" claim is verifiably false.** The mypy.ini has active exemptions that weaken strict mode.

The root cause is not bad code — it's **incomplete automation**. Every finding in this audit that was also in prior audits (CC-01: CI no test mypy, CC-02/CC-03: mypy exemptions, CM-04: version drift, CH-04: missing hooks) persists because there's no machine-enforced gate to catch regressions.

**Grade: C+**

Previous audits gave B-, then 2 more audits happened with same issue categories. The trajectory is not improving fast enough.

