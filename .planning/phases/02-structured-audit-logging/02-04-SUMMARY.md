# Plan 02-04 Summary: SEC-12 + Signature Events

**Phase:** 02-structured-audit-logging
**Plan:** 04
**Wave:** 4
**Status:** ✅ Complete
**Requirements:** SEC-12, AUD-01

## What Was Built

### Task 1: STALE_SIGNATURE ErrorCode + verify_signature returns Result[None]
- Added `STALE_SIGNATURE = "STALE_SIGNATURE"` to `ErrorCode` enum in `types.py`
- Changed `verify_signature()` return type from `bool` to `Result[None]` in `envelope.py`
  - Returns `Success(None)` for valid + fresh signatures
  - Returns `Failure(code=STALE_SIGNATURE)` when envelope exceeds `max_age_seconds`
  - Returns `Failure(code=INVALID_SNAPSHOT)` when signature doesn't match
- Updated all 5 callers:
  - `core_pipeline._apply_manifest()` — handles `Result[None]`, preserves error code
  - `snapshot.load_snapshot()` — checks `isinstance(sig_result, Failure)`
  - `test_envelope.py` — updated assertions from `bool` to `Success`/`Failure`
  - `test_parallel_pipeline.py` — updated verify_signature assertion
  - `test_pipeline_integration.py` — updated verify_signature assertion + fixed import shadowing bug
- Added `max_signature_age: int = 86400` field to `CoreRelayPipeline`

### Task 2: Signature Audit Events + max_signature_age
- Wired `SignatureVerificationPassed` and `SignatureVerificationStale` audit events in `_apply_manifest`
  - Emits `SignatureVerificationPassed` when `verify_signature` returns `Success`
  - Emits `SignatureVerificationStale` with `envelope_age_seconds` and `max_age_seconds` when stale
  - Added `from datetime import datetime, timezone` to `core_pipeline.py`
- Fixed `execute_step_with_runner` None guard (`assert` → conditional)
- Fixed integration test `UnboundLocalError` for `Success` (duplicate local import)

### Task 3: Verification Checkpoint
- All verification steps pass

## Files Modified
| File | Change |
|------|--------|
| `src/relay/types.py` | +STALE_SIGNATURE ErrorCode |
| `src/relay/envelope.py` | verify_signature return type → Result[None] |
| `src/relay/core_pipeline.py` | max_signature_age field; signature audit events; execute_step_with_runner fix |
| `src/relay/snapshot.py` | Updated verify_signature caller |
| `tests/unit/test_envelope.py` | Updated assertions for Result[None] |
| `tests/integration/test_parallel_pipeline.py` | Updated verify_signature assertion |
| `tests/integration/test_pipeline_integration.py` | Updated verify_signature assertion; fixed import |

## Verification
- ✅ 422 unit tests passed (1 skipped — tiktoken benchmark)
- ✅ 28 integration tests passed
- ✅ mypy --strict zero suppressions on all changed files

## Commits
- `fc3394d` test(02-04): add failing tests for Result[None] with STALE_SIGNATURE
- `d9318e1` feat(02-04): add STALE_SIGNATURE, change verify_signature, update callers
- `e77cff4` feat(02-04): emit signature events in _apply_manifest; fix runner None guard
