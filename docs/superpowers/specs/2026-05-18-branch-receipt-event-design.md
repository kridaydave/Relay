# BranchReceipt Audit Event Design

## Problem

Current fork-join audit emits 3 aggregate events (`ForkStarted`, `ForkCompleted`, `JoinCompleted`) that count forks and name the strategy, but a reviewer must replay the entire run to answer:

- Which branch introduced an unexpected claim?
- Was a specific branch's output included in the merge or discarded?
- Did any branch touch files it wasn't permitted to?
- What was the merge decision rationale per branch?

The distinction is **history** (we logged that a fork-join happened) vs **auditability** (an operator can trust the handoff from the ledger alone).

## Solution

Add a `BranchReceipt` frozen dataclass event, emitted once per fork immediately after join resolution and before state commit. Each receipt captures the full audit trail for one branch, making the merge decision independently verifiable.

## Event Schema

```python
@dataclass(frozen=True)
class BranchReceipt:
    event_type: str = "branch_receipt"  # init=False
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = ...
    latency_ms: float = 0.0

    # 1. Branch identity
    fork_index: int
    adapter_name: str

    # 2. Snapshot chain
    parent_snapshot_hash: str     # pre_fork_envelope.manifest_hash
    final_snapshot_hash: str      # combined hash after merge

    # 3. Agent context
    agent_id: str
    policy_hash: str              # spec.manifest hash
    tools_used: tuple[str, ...]   # tool_calls from agent output
    sections_read: tuple[str, ...]    # spec.manifest.reads
    sections_written: tuple[str, ...]  # spec.manifest.writes

    # 4. Claims delta
    keys_added: tuple[str, ...]   # output keys not in pre-fork scope
    keys_removed: tuple[str, ...] # pre-fork scope keys absent from output

    # 5. Merge audit
    join_strategy: str
    merge_decision: str           # "included" | "excluded" | "failed"
    conflict_keys: tuple[str, ...]

    # 6. Outcome
    branch_success: bool
    branch_error: str = ""
```

## Merge Decision Semantics

| Decision | Meaning |
|---|---|
| `included` | Branch contributed to merged result (all UNION passers, VOTE winner, FIRST_WINS winner) |
| `excluded` | Branch passed but was not selected (VOTE losers, FIRST_WINS cancelled) |
| `failed` | Branch failed execution (adapter error, contradiction, budget violation) |

## Field Sources

| BranchReceipt field | Source |
|---|---|
| `fork_index` | `ForkResult.fork_index` |
| `adapter_name` | `ForkResult.adapter_name` or `ForkSpec.adapter_name` |
| `parent_snapshot_hash` | `pre_fork_envelope.manifest_hash` |
| `final_snapshot_hash` | `_combine_manifest_hashes(fork_specs)` |
| `agent_id` | ContextSlice built for this fork |
| `policy_hash` | `spec.manifest.compute_hash()` |
| `tools_used` | `agent_output.tool_calls[].name` |
| `sections_read` | `spec.manifest.reads` |
| `sections_written` | `spec.manifest.writes` |
| `keys_added` | `fork_payload.keys() - pre_fork_scoped.keys()` |
| `keys_removed` | `pre_fork_scoped.keys() - fork_payload.keys()` |
| `join_strategy` | `join_strategy.value` (parameter) |
| `merge_decision` | Computed from join result + fork status |
| `conflict_keys` | Set of keys where UNION found conflicts (empty for VOTE/FIRST_WINS) |
| `branch_success` | `ForkResult.success` |
| `branch_error` | `str(ForkResult.failure.code)` if failed |

## Emission Flow

For UNION and VOTE, the current code collects all `ForkResult` values. For FIRST_WINS, the code currently does NOT collect individual results (to avoid unnecessary work after cancellation). The design changes FIRST_WINS to also gather results — tasks already ran or were cancelled, and collecting what we have is a zero-cost read of completed task results.

The loop after fork execution emits a `BranchReceipt` for each `(ForkSpec, ForkResult)` pair, then the existing `ForkCompleted` and `JoinCompleted` events are emitted as before.

## Changes Required

### `relay.audit.events`
- Add `BranchReceipt` frozen dataclass
- Add to `AuditEvent` union type
- Add to `__all__`

### `relay.core_pipeline`
- In `execute_parallel_step`, after fork execution, loop over results/specs and emit `BranchReceipt` for each
- FIRST_WINS: collect `ForkResult` values after cancellation for audit purposes

### `tests/unit/test_audit_events.py`
- Add `TestBranchReceipt` class verifying all fields construct correctly

### `tests/unit/test_pipeline.py`
- Add integration-style test that `execute_parallel_step` emits a `BranchReceipt` per fork

## AuditEvent Union Update

```python
type AuditEvent = (
    ...
    | ForkStarted
    | ForkCompleted
    | JoinCompleted
    | BranchReceipt        # NEW
    ...
)
```

## Non-Goals

- Human review escalation pathway (out of scope for v0.5)
- Real-time conflict resolution UI (separate system)
- Replacing existing `ForkStarted`/`ForkCompleted`/`JoinCompleted` events (they remain for aggregate counting)
