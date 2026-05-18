# BranchReceipt Audit Event Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-branch `BranchReceipt` audit event for fork-join steps — one per fork — capturing snapshot hashes, agent context, claims delta, conflicts, and merge decision.

**Architecture:** New frozen dataclass in `relay.audit.events`, emitted in `execute_parallel_step` after fork execution and before commit. FIRST_WINS strategy modified to return collected `ForkResult` values so receipts can be built.

**Tech Stack:** Python 3.12+, mypy --strict, pytest, frozen dataclasses

---

### Task 1: Add BranchReceipt event type

**Files:**
- Modify: `src/relay/audit/events.py` (add dataclass + union + __all__)
- Test: `tests/unit/test_audit_events.py` (new test class)

- [ ] **Step 1: Add BranchReceipt dataclass to events.py**

Add after `JoinCompleted`:

```python
@dataclass(frozen=True)
class BranchReceipt:
    """Per-branch audit receipt for a fork-join step.

    One emitted per fork, capturing the full merge audit trail
    so the merge decision is verifiable without replay.
    """

    event_type: str = field(default="branch_receipt", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0

    # 1. Branch identity
    fork_index: int
    adapter_name: str

    # 2. Snapshot chain
    parent_snapshot_hash: str = ""
    final_snapshot_hash: str = ""

    # 3. Agent context
    agent_id: str = ""
    policy_hash: str = ""
    tools_used: tuple[str, ...] = ()
    sections_read: tuple[str, ...] = ()
    sections_written: tuple[str, ...] = ()

    # 4. Claims delta
    keys_added: tuple[str, ...] = ()
    keys_removed: tuple[str, ...] = ()

    # 5. Merge audit
    join_strategy: str = ""
    merge_decision: str = ""
    conflict_keys: tuple[str, ...] = ()

    # 6. Outcome
    branch_success: bool = True
    branch_error: str = ""
```

- [ ] **Step 2: Add BranchReceipt to AuditEvent union**

```python
type AuditEvent = (
    ...
    | ForkStarted
    | ForkCompleted
    | JoinCompleted
    | BranchReceipt
    ...
)
```

- [ ] **Step 3: Add BranchReceipt to `__all__`**

Add `"BranchReceipt"` to the `__all__` list.

- [ ] **Step 4: Write BranchReceipt construction tests**

Add `TestBranchReceipt` class to `tests/unit/test_audit_events.py`:

```python
class TestBranchReceipt:
    """Verify BranchReceipt constructs correctly with all fields."""

    def test_branch_receipt_has_correct_event_type_when_constructed(self) -> None:
        event = BranchReceipt(
            pipeline_id="p", step=1, fork_index=0, adapter_name="a",
        )
        assert event.event_type == "branch_receipt"

    def test_branch_receipt_carries_all_metadata_when_constructed(self) -> None:
        event = BranchReceipt(
            pipeline_id="test-pipeline",
            step=3,
            fork_index=1,
            adapter_name="agent-b",
            parent_snapshot_hash="abc",
            final_snapshot_hash="def",
            agent_id="agent-b",
            policy_hash="manifest-hash-123",
            tools_used=("read_file", "search"),
            sections_read=("context",),
            sections_written=("output",),
            keys_added=("new_key",),
            keys_removed=("old_key",),
            join_strategy="UNION",
            merge_decision="included",
            conflict_keys=(),
            branch_success=True,
        )
        assert event.pipeline_id == "test-pipeline"
        assert event.step == 3
        assert event.fork_index == 1
        assert event.adapter_name == "agent-b"
        assert event.parent_snapshot_hash == "abc"
        assert event.final_snapshot_hash == "def"
        assert event.agent_id == "agent-b"
        assert event.policy_hash == "manifest-hash-123"
        assert event.tools_used == ("read_file", "search")
        assert event.sections_read == ("context",)
        assert event.sections_written == ("output",)
        assert event.keys_added == ("new_key",)
        assert event.keys_removed == ("old_key",)
        assert event.join_strategy == "UNION"
        assert event.merge_decision == "included"
        assert event.conflict_keys == ()
        assert event.branch_success is True
        assert event.branch_error == ""

    def test_branch_receipt_is_frozen_when_mutation_attempted(self) -> None:
        event = BranchReceipt(
            pipeline_id="p", step=1, fork_index=0, adapter_name="a",
        )
        with pytest.raises(AttributeError):
            event.fork_index = 99  # type: ignore[misc]
```

- [ ] **Step 5: Run test, verify pass**

```bash
pytest tests/unit/test_audit_events.py -v -k BranchReceipt
```

- [ ] **Step 6: Commit**

```bash
git add src/relay/audit/events.py tests/unit/test_audit_events.py
git commit -m "feat(audit): add BranchReceipt event type for per-branch fork-join audit trail"
```

---

### Task 2: Modify `_apply_first_wins` to return collected results

**Files:**
- Modify: `src/relay/parallel/join.py`

- [ ] **Step 1: Change `_apply_first_wins` return type**

Change signature and return to `tuple[Result[JSONDict], list[ForkResult]]`:

```python
async def _apply_first_wins(
    fork_index_coros: list[tuple[int, ForkSpec, "Coroutine[None, None, ForkResult]"]],
) -> tuple[Result[JSONDict], list[ForkResult]]:
    """Accept the first passing fork; cancel the rest.

    Returns: (Success(winner_payload) | Failure, collected_results) where
    collected_results contains all ForkResults from completed tasks.
    """

    # ... all existing logic stays the same ...

    # After the cancellation/gather block (lines 127-130):
    collected: list[ForkResult] = []
    for task in tasks:
        if task.done() and not task.cancelled():
            try:
                result = task.result()
                if isinstance(result, ForkResult):
                    collected.append(result)
            except Exception:
                pass

    if winner_payload is None:
        return (
            Failure(
                reason=f"FIRST_WINS: all {len(tasks)} forks failed or were cancelled",
                code=ErrorCode.ALL_FORKS_FAILED,
            ),
            collected,
        )
    return Success(agent_output_to_payload(winner.agent_output)), collected
```

- [ ] **Step 2: Update `apply_join_strategy` FIRST_WINS overload branch**

Update the FIRST_WINS handler to unpack the tuple and return just the Result (keeping public API compatible):

```python
elif strategy == JoinStrategy.FIRST_WINS:
    if first_wins_coros is None:
        return Failure(
            reason="first_wins_coros must be provided for FIRST_WINS strategy",
            code=ErrorCode.INVALID_JOIN_STRATEGY,
        )
    result, _collected = await _apply_first_wins(first_wins_coros)
    return result
```

The overloads stay the same — `apply_join_strategy` still returns `Result[JSONDict]`.

- [ ] **Step 3: Re-export `collected` for the pipeline caller**

Add a module-level attribute to stash collected results, or alternatively, change the approach in core_pipeline to access `_apply_first_wins` directly. The cleanest approach: modify `execute_parallel_step` in Task 3 to call `_apply_first_wins` directly for FIRST_WINS (bypassing the `apply_join_strategy` wrapper for that path).

- [ ] **Step 4: Run existing tests**

```bash
pytest tests/unit/test_parallel/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/relay/parallel/join.py
git commit -m "refactor(parallel): _apply_first_wins returns collected ForkResults for audit"
```

---

### Task 3: Emit BranchReceipt in execute_parallel_step

**Files:**
- Modify: `src/relay/core_pipeline.py` (add BranchReceipt import, emission loop in execute_parallel_step)
- Test: `tests/unit/test_pipeline.py` (new parallel step audit test)

- [ ] **Step 1: Add BranchReceipt import**

Add to the audit events imports at the top of `core_pipeline.py`:

```python
from relay.audit.events import (
    ...
    BranchReceipt,
    ...
)
```

Also add imports needed for receipt building:

```python
from relay.parallel.types import agent_output_to_payload
```

- [ ] **Step 2: Restructure `execute_parallel_step` to run all forks, emit receipts, then apply strategy**

Replace the fork execution branch (lines 774-797) with unified collection + emission:

```python
# Run all forks regardless of strategy for audit completeness
collected_fork_results: list[ForkResult] = list(await asyncio.gather(*fork_coros))

# Per-branch: build a scoped payload for claims-delta computation
fork_scope_keys: list[frozenset[str]] = [
    spec.manifest.reads | spec.manifest.writes for spec in fork_specs
]
pre_fork_scoped_payloads: list[JSONDict] = [
    {k: v for k, v in pre_fork_envelope.payload.items() if k in scope}
    for scope in fork_scope_keys
]

for i, (spec, result) in enumerate(zip(fork_specs, collected_fork_results)):
    fork_payload = (
        agent_output_to_payload(result.agent_output)
        if result.agent_output is not None
        else {}
    )
    pre_scope = pre_fork_scoped_payloads[i]
    keys_added = tuple(sorted(fork_payload.keys() - pre_scope.keys()))
    keys_removed = tuple(sorted(pre_scope.keys() - fork_payload.keys()))

    tools_used: tuple[str, ...] = ()
    if result.agent_output is not None and result.agent_output.tool_calls:
        tools_used = tuple(
            sorted({t.get("name", "") for t in result.agent_output.tool_calls if isinstance(t, dict)})
        )

    branch_success = result.success
    merge_decision: str
    if not branch_success:
        merge_decision = "failed"
    elif join_strategy == JoinStrategy.FIRST_WINS:
        merge_decision = "included" if i == 0 else "excluded"
    else:
        merge_decision = "included"

    self._emit_audit_event(BranchReceipt(
        pipeline_id=self._pipeline_id,
        step=pre_fork_envelope.step,
        fork_index=i,
        adapter_name=spec.adapter_name,
        parent_snapshot_hash=pre_fork_envelope.manifest_hash or "",
        final_snapshot_hash=combined_hash,
        agent_id=spec.manifest.agent_id,
        policy_hash=spec.manifest.compute_hash(),
        tools_used=tools_used,
        sections_read=tuple(sorted(spec.manifest.reads)),
        sections_written=tuple(sorted(spec.manifest.writes)),
        keys_added=keys_added,
        keys_removed=keys_removed,
        join_strategy=join_strategy.value,
        merge_decision=merge_decision,
        conflict_keys=(),
        branch_success=branch_success,
        branch_error=str(result.failure.code) if not branch_success and result.failure else "",
    ))

forks_succeeded = sum(1 for r in collected_fork_results if r.success)

if join_strategy == JoinStrategy.FIRST_WINS:
    winner = next((r for r in collected_fork_results if r.success), None)
    if winner is None:
        merged_result = Failure(
            reason=f"FIRST_WINS: all {len(collected_fork_results)} forks failed",
            code=ErrorCode.ALL_FORKS_FAILED,
        )
    else:
        merged_result = Success(agent_output_to_payload(winner.agent_output))
else:
    merged_result = await apply_join_strategy(join_strategy, collected_fork_results, None)

self._emit_audit_event(ForkCompleted(
    pipeline_id=self._pipeline_id,
    step=pre_fork_envelope.step,
    forks_succeeded=forks_succeeded,
))
```

Note: `combined_hash` is currently computed AFTER the fork execution block (line 808). Move it BEFORE the receipt emission loop. The new order:

1. Run forks, collect results
2. Compute combined_hash
3. Emit BranchReceipt per fork
4. Apply join strategy
5. Emit ForkCompleted
6. Emit JoinCompleted
7. Commit

- [ ] **Step 3: Move `combined_hash` computation before receipt emission**

```python
combined_hash = _combine_manifest_hashes([s.manifest for s in fork_specs])
```

Move this line before the BranchReceipt emission loop.

- [ ] **Step 4: Write pipeline audit test**

Add a new test in `tests/unit/test_pipeline.py`:

```python
class TestParallelStepAuditEvents:
    """Verify BranchReceipt events are emitted per fork during parallel steps."""

    @pytest.mark.asyncio
    async def test_parallel_step_emits_branch_receipt_per_fork_when_union(self) -> None:
        audit_sink = FixedAuditSink()
        async with make_pipeline(audit_sink=audit_sink) as pipeline:
            result1 = await pipeline.execute_step_with_manifest(
                agent_output=AgentOutput(
                    text="step1", structured={}, tool_calls=[],
                    token_count=10, latency_ms=5, adapter="test",
                ),
                manifest=AgentManifest(
                    agent_id="agent-a", task_description="test",
                    reads=frozenset({"input"}), writes=frozenset({"output"}),
                    max_tokens=1000,
                ),
            )
            assert isinstance(result1, Success)

            specs = [
                ForkSpec(
                    adapter_name="test-adapter",
                    manifest=AgentManifest(
                        agent_id="fork-a", task_description="fork-a",
                        reads=frozenset(), writes=frozenset({"fork_output_a"}),
                        max_tokens=1000,
                    ),
                ),
                ForkSpec(
                    adapter_name="test-adapter",
                    manifest=AgentManifest(
                        agent_id="fork-b", task_description="fork-b",
                        reads=frozenset(), writes=frozenset({"fork_output_b"}),
                        max_tokens=1000,
                    ),
                ),
            ]
            result2 = await pipeline.execute_parallel_step(specs, JoinStrategy.UNION)
            assert isinstance(result2, Success)

        receipt_events = [e for e in audit_sink.events if e.event_type == "branch_receipt"]
        assert len(receipt_events) == 2
        for receipt in receipt_events:
            assert receipt.pipeline_id == pipeline_id
            assert receipt.adapter_name == "test-adapter"
            assert receipt.merge_decision == "included"
            assert receipt.branch_success is True
            assert receipt.final_snapshot_hash != ""

    @pytest.mark.asyncio
    async def test_parallel_step_emits_branch_receipt_with_correct_merge_decision_when_vote(self) -> None:
        audit_sink = FixedAuditSink()
        async with make_pipeline(audit_sink=audit_sink) as pipeline:
            result1 = await pipeline.execute_step_with_manifest(
                agent_output=AgentOutput(
                    text="step1", structured={}, tool_calls=[],
                    token_count=10, latency_ms=5, adapter="test",
                ),
                manifest=AgentManifest(
                    agent_id="agent-a", task_description="test",
                    reads=frozenset({"input"}), writes=frozenset({"output"}),
                    max_tokens=1000,
                ),
            )
            assert isinstance(result1, Success)

            specs = [
                ForkSpec(
                    adapter_name="test-adapter",
                    manifest=AgentManifest(
                        agent_id="vote-a", task_description="vote-a",
                        reads=frozenset(), writes=frozenset({"output"}),
                        max_tokens=1000,
                    ),
                ),
                ForkSpec(
                    adapter_name="test-adapter",
                    manifest=AgentManifest(
                        agent_id="vote-b", task_description="vote-b",
                        reads=frozenset(), writes=frozenset({"output"}),
                        max_tokens=1000,
                    ),
                ),
            ]
            result2 = await pipeline.execute_parallel_step(specs, JoinStrategy.VOTE)
            assert isinstance(result2, Success)

        receipts = [e for e in audit_sink.events if e.event_type == "branch_receipt"]
        assert len(receipts) == 2
        # VOTE: both pass, one is included (the winner), one excluded
        decisions = {r.fork_index: r.merge_decision for r in receipts}
        assert set(decisions.values()) == {"included", "excluded"}
        assert all(r.branch_success is True for r in receipts)

    @pytest.mark.asyncio
    async def test_failed_fork_emits_branch_receipt_with_failed_decision_when_adapter_not_found(self) -> None:
        audit_sink = FixedAuditSink()
        async with make_pipeline(audit_sink=audit_sink) as pipeline:
            await pipeline.execute_step_with_manifest(
                agent_output=AgentOutput(
                    text="step1", structured={}, tool_calls=[],
                    token_count=10, latency_ms=5, adapter="test",
                ),
                manifest=AgentManifest(
                    agent_id="agent-a", task_description="test",
                    reads=frozenset({"input"}), writes=frozenset({"output"}),
                    max_tokens=1000,
                ),
            )
            specs = [
                ForkSpec(
                    adapter_name="nonexistent-adapter",
                    manifest=AgentManifest(
                        agent_id="fail-branch", task_description="x",
                        reads=frozenset(), writes=frozenset({"out"}),
                        max_tokens=1000,
                    ),
                ),
            ]
            result = await pipeline.execute_parallel_step(specs, JoinStrategy.UNION)
            assert isinstance(result, Failure)

        receipts = [e for e in audit_sink.events if e.event_type == "branch_receipt"]
        assert len(receipts) == 1
        assert receipts[0].merge_decision == "failed"
        assert receipts[0].branch_success is False
        assert receipts[0].branch_error != ""
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_pipeline.py -v -k TestParallelStepAuditEvents
pytest tests/unit/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add src/relay/core_pipeline.py tests/unit/test_pipeline.py
git commit -m "feat(pipeline): emit BranchReceipt per fork in execute_parallel_step"
```

---

### Task 4: Run full test suite and mypy

**Files:**
- Run: full verification

- [ ] **Step 1: Run check_test_names.py**

```bash
python scripts/check_test_names.py
```

Expected: All pass.

- [ ] **Step 2: Run all unit tests**

```bash
python -m pytest tests/unit -v --tb=short
```

Expected: all pass (422+ new tests).

- [ ] **Step 3: Run mypy on package and tests**

```bash
python -m mypy --strict src/relay
python -m mypy --strict tests/unit/test_audit_events.py tests/unit/test_pipeline.py
```

Expected: no issues found.

- [ ] **Step 4: Update CHANGELOG.md and Internal-changelog.md**

Add v0.5.1 entry to CHANGELOG.md covering BranchReceipt implementation.

Add entry to Internal-changelog.md under 2026-05-18.

- [ ] **Step 5: Final commit for changelog updates**

```bash
git add CHANGELOG.md Internal-changelog.md
git commit -m "docs: update changelogs for BranchReceipt implementation"
```
