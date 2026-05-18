"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""

__all__ = [
    "CoreRelayPipeline",
]

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field

from relay.audit import (
    AuditEvent,
    AuditSink,
    BudgetCheckFailed,
    BudgetCheckPassed,
    ForkCompleted,
    ForkStarted,
    JoinCompleted,
    JsonLogSink,
    PipelineClosed,
    PipelineCreated,
    RollbackCompleted,
    RollbackTriggered,
    SnapshotSaved,
    StepExecutionFailed,
    StepExecutionStarted,
    StepExecutionSucceeded,
    ValidationContradiction,
    ValidationPassed,
)
from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker, create_context_broker
from relay.envelope import (
    ContextEnvelope,
    compute_signature,
    estimate_tokens,
    serialize_slice,
    verify_signature,
)
from relay.parallel import ForkResult, ForkSpec, JoinStrategy, apply_join_strategy
from relay.parallel.fork_runner import run_single_fork
from relay.parallel.types import agent_output_to_payload
from relay.pipeline_rollback import RollbackHandler
from relay.pipeline_state import PipelineState
from relay.runners import AdapterRegistry
from relay.runners.protocol import ContextSlice
from relay.slicer import AgentManifest
from relay.snapshot import LocalFileSnapshotStore
from relay.snapshot_protocol import SnapshotStore
from relay.types import ErrorCode, Failure, JSONDict, Result, RollbackSuccess, Success
from relay.validator import (
    HandoffValidator,
    validate_manifest_boundaries,
)


def _combine_manifest_hashes(manifests: list[AgentManifest]) -> str:
    def _key(m: AgentManifest) -> str:
        return m.agent_id

    sorted_manifests = sorted(manifests, key=_key)
    hashes = [m.compute_hash() for m in sorted_manifests]
    combined = "|".join(hashes)
    return hashlib.sha256(combined.encode()).hexdigest()


@dataclass
class CoreRelayPipeline:
    """Base class for pipeline orchestration.

    Owns: pipeline lifecycle, component coordination, budget enforcement, slicer dispatch,
          parallel fork-join orchestration.
    Does NOT: define agent behavior, manage prompts, implement token counting, or implement slicing strategies.

    Note: Use create() factory to construct instances with validation. Direct construction
    bypasses secret validation and is intended only for internal use with pre-validated secrets.
    """

    signing_secret: str = field(repr=False)
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"
    token_counter: TokenCounter | None = None
    registry: AdapterRegistry | None = None
    snapshot_store: SnapshotStore | None = None
    audit_sink: AuditSink | None = None
    max_signature_age: int = 86400

    _pipeline_id: str = field(init=False, repr=False)
    _state: PipelineState = field(init=False, repr=False)
    _context_broker: ContextBroker = field(init=False, repr=False)
    _handoff_validator: HandoffValidator = field(init=False, repr=False)
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    _audit_sink: AuditSink = field(init=False, repr=False)
    _rollback_handler: RollbackHandler = field(init=False, repr=False)
    _enforcer: HardCapEnforcer | None = field(init=False, repr=False)

    @classmethod
    def create(
        cls,
        signing_secret: str,
        token_budget: int = 8000,
        storage_path: str = "./relay_data/snapshots",
        token_counter: TokenCounter | None = None,
        registry: AdapterRegistry | None = None,
        snapshot_store: SnapshotStore | None = None,
        audit_sink: AuditSink | None = None,
    ) -> Result["CoreRelayPipeline"]:
        """Create a pipeline with Result-based error handling.

        Use this factory instead of direct construction to handle
        validation errors without exceptions.

        Note: storage_path is ignored when snapshot_store is provided.
        """
        broker_result = create_context_broker(
            signing_secret=signing_secret, token_budget_total=token_budget
        )
        if isinstance(broker_result, Failure):
            return broker_result
        pipeline = cls(
            signing_secret=signing_secret,
            token_budget=token_budget,
            storage_path=storage_path,
            token_counter=token_counter,
            registry=registry,
            snapshot_store=snapshot_store,
            audit_sink=audit_sink,
        )
        pipeline._context_broker = broker_result.value
        return Success(pipeline)

    def __post_init__(self) -> None:
        self._pipeline_id = uuid.uuid4().hex
        self._state = PipelineState(pipeline_id=self._pipeline_id)
        broker_result = create_context_broker(
            signing_secret=self.signing_secret,
            token_budget_total=self.token_budget,
        )
        if isinstance(broker_result, Failure):
            raise ValueError(broker_result.reason)
        self._context_broker = broker_result.value
        self._handoff_validator = HandoffValidator()
        if self.snapshot_store is not None:
            self._snapshot_store = self.snapshot_store
        else:
            self._snapshot_store = LocalFileSnapshotStore(storage_path=self.storage_path)
        if self.audit_sink is not None:
            self._audit_sink = self.audit_sink
        else:
            self._audit_sink = JsonLogSink()
        self._rollback_handler = RollbackHandler()
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self.token_counter)
        else:
            self._enforcer = None

        self._emit_audit_event(PipelineCreated(pipeline_id=self._pipeline_id))

    @property
    def history(self) -> list[ContextEnvelope]:
        """Return a copy of the pipeline's envelope history."""
        with self._state.transaction():
            return self._state.get_previous_envelopes()

    @property
    def snapshot_index(self) -> dict[int, str]:
        """Return a copy of the snapshot index mapping step numbers to IDs."""
        with self._state.transaction():
            return self._state.snapshot_ids

    @property
    def current_envelope(self) -> ContextEnvelope | None:
        """Return the current envelope, or None if the pipeline is new."""
        with self._state.transaction():
            return self._state.current()

    def close(self) -> None:
        """Release pipeline resources.

        Closes the snapshot store and releases token counter resources
        if one was provided. Emits pipeline_closed event before closing
        the audit sink to ensure the event reaches the sink.
        """
        current_step = 0
        with self._state.transaction() as envelope:
            if envelope is not None:
                current_step = envelope.step
        self._emit_audit_event(
            PipelineClosed(
                pipeline_id=self._pipeline_id,
                step=current_step,
            )
        )
        self._audit_sink.close()
        self._snapshot_store.close()
        if self.token_counter is not None:
            self.token_counter.close()

    def __enter__(self) -> "CoreRelayPipeline":
        """Enter the pipeline context."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit the pipeline context and release resources."""
        self.close()

    def _emit_audit_event(self, event: AuditEvent) -> None:
        """Emit an audit event with fire-and-forget semantics.

        Delegates to the configured audit sink. Errors are logged by
        the sink implementation and never propagated per D-06.
        """
        self._audit_sink.emit(event)

    def execute_step(self, agent_output: JSONDict) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output."""
        return self.execute_step_with_manifest(agent_output, manifest=None)

    def execute_step_with_manifest(
        self,
        agent_output: JSONDict,
        manifest: AgentManifest | None = None,
    ) -> Result[ContextEnvelope]:
        """Execute a pipeline step with optional manifest for budget/boundary validation."""
        step: int = 1
        agent_name: str = ""
        with self._state.transaction() as current_envelope:
            agent_name = manifest.agent_id if manifest else ""
            if current_envelope is None:
                step = 1
                self._emit_audit_event(
                    StepExecutionStarted(
                        pipeline_id=self._pipeline_id,
                        step=step,
                        adapter_name="",
                        agent_name=agent_name,
                    )
                )
                result = self._handle_initial_step(agent_output, manifest)
            else:
                step = current_envelope.step + 1
                self._emit_audit_event(
                    StepExecutionStarted(
                        pipeline_id=self._pipeline_id,
                        step=step,
                        adapter_name="",
                        agent_name=agent_name,
                    )
                )
                result = self._handle_subsequent_step(
                    current_envelope, agent_output, manifest
                )

        if isinstance(result, Success):
            self._emit_audit_event(
                StepExecutionSucceeded(
                    pipeline_id=self._pipeline_id,
                    step=step,
                    adapter_name="",
                    agent_name=agent_name,
                )
            )
        elif isinstance(result, RollbackSuccess):
            self._emit_audit_event(
                StepExecutionFailed(
                    pipeline_id=self._pipeline_id,
                    step=step,
                    adapter_name="",
                    agent_name=agent_name,
                    error_code="ROLLBACK",
                )
            )
        elif isinstance(result, Failure):
            self._emit_audit_event(
                StepExecutionFailed(
                    pipeline_id=self._pipeline_id,
                    step=step,
                    adapter_name="",
                    agent_name=agent_name,
                    error_code=result.code.value,
                )
            )

        return result

    def _handle_initial_step(
        self,
        agent_output: JSONDict,
        manifest: AgentManifest | None,
    ) -> Result[ContextEnvelope]:
        """Handle the first pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        budget_result = self._check_budget(manifest, None, agent_output)
        if isinstance(budget_result, Failure):
            return budget_result

        result = self._context_broker.create_initial_envelope(
            pipeline_id=self._pipeline_id,
            initial_payload=agent_output,
            manifest_hash=manifest.compute_hash() if manifest else "",
        )
        if isinstance(result, Failure):
            return result

        apply_result = self._apply_manifest(result.value, manifest)
        if isinstance(apply_result, Failure):
            return apply_result
        new_envelope = apply_result.value

        save_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(save_result, Failure):
            return save_result
        self._state.register_snapshot(new_envelope.step, save_result.value)

        self._state.set_current(new_envelope)
        return Success(new_envelope)

    def _handle_subsequent_step(
        self,
        current_envelope: ContextEnvelope,
        agent_output: JSONDict,
        manifest: AgentManifest | None,
    ) -> Result[ContextEnvelope]:
        """Handle a subsequent pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        budget_result = self._check_budget(manifest, current_envelope)
        if isinstance(budget_result, Failure):
            return budget_result

        result = self._context_broker.create_next_envelope(
            previous_envelope=current_envelope,
            agent_output=agent_output,
            manifest_hash=manifest.compute_hash() if manifest else "",
        )
        if isinstance(result, Failure):
            return result
        new_envelope = result.value

        result = self._apply_manifest(new_envelope, manifest)
        if isinstance(result, Failure):
            return result
        new_envelope = result.value

        return self._finalize_step(current_envelope, new_envelope)

    def _check_budget(
        self,
        manifest: AgentManifest | None,
        current_envelope: ContextEnvelope | None,
        agent_output: JSONDict | None = None,
    ) -> Result[None]:
        """Check token budget if manifest and enforcer present.

        Checks both pipeline-level budget (token_budget_total) and per-agent
        budget (manifest.max_tokens) when available.

        When current_envelope is None (initial step), token_budget_used is 0
        and projection is based on agent_output (the actual payload).
        """
        _audit_budget_triggered = False
        audit_step = (current_envelope.step + 1) if current_envelope is not None else 1
        budget_used = (
            current_envelope.token_budget_used if current_envelope is not None else 0
        )
        if manifest is not None and self._enforcer is not None:
            _audit_budget_triggered = True
            if current_envelope is not None:
                projected = serialize_slice(
                    dict[str, object]({s: "<output>" for s in manifest.writes})
                )
            else:
                projected = (
                    serialize_slice(agent_output)
                    if agent_output is not None
                    else serialize_slice(
                        dict[str, object]({s: "<slice>" for s in manifest.writes})
                    )
                )
            enforcer_result = self._enforcer.check(
                budget_used, self.token_budget, projected
            )
            if isinstance(enforcer_result, Failure):
                self._emit_audit_event(
                    BudgetCheckFailed(
                        pipeline_id=self._pipeline_id,
                        step=audit_step,
                        budget_used=budget_used,
                        budget_limit=self.token_budget,
                    )
                )
                return enforcer_result

            # Per-agent max_tokens check (manifest.max_tokens).
            if manifest.max_tokens is not None:
                projected_cost = self._enforcer.counter.count(projected)
                if projected_cost > manifest.max_tokens:
                    self._emit_audit_event(
                        BudgetCheckFailed(
                            pipeline_id=self._pipeline_id,
                            step=audit_step,
                            budget_used=budget_used,
                            budget_limit=manifest.max_tokens,
                        )
                    )
                    return Failure(
                        reason=(
                            f"Agent budget exceeded: projected {projected_cost} tokens "
                            f"exceeds manifest.max_tokens={manifest.max_tokens}"
                        ),
                        code=ErrorCode.TOKEN_BUDGET_EXCEEDED,
                    )
        if _audit_budget_triggered:
            self._emit_audit_event(
                BudgetCheckPassed(
                    pipeline_id=self._pipeline_id,
                    step=audit_step,
                    budget_used=budget_used,
                    budget_limit=self.token_budget,
                )
            )
        return Success(None)

    def _finalize_step(
        self,
        current_envelope: ContextEnvelope,
        new_envelope: ContextEnvelope,
    ) -> Result[ContextEnvelope]:
        """Archive envelope, validate handoff, and advance pipeline.

        Validates BEFORE mutating state to ensure we don't leave state
        in an inconsistent position if validation fails for non-contradiction reasons.
        Saves snapshot BEFORE advancing state to ensure consistency.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        self._state._assert_lock_held()
        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=current_envelope, current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        self._emit_audit_event(
            ValidationPassed(
                pipeline_id=self._pipeline_id,
                step=new_envelope.step,
            )
        )

        if self._handoff_validator.should_rollback(validation_result.value):
            # current_envelope was already snapshotted when committed — skip redundant save.
            self._state.push_current_to_history()
            self._emit_audit_event(
                ValidationContradiction(
                    pipeline_id=self._pipeline_id,
                    step=new_envelope.step,
                    contradiction_type=validation_result.value.contradiction_details
                    or "",
                    diff_summary="",
                )
            )
            return RollbackSuccess(
                value=current_envelope,
                reason=validation_result.value.contradiction_details
                or "Contradiction detected",
            )

        save_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(save_result, Failure):
            return save_result
        self._emit_audit_event(
            SnapshotSaved(
                pipeline_id=self._pipeline_id,
                step=new_envelope.step,
                snapshot_id=save_result.value,
                snapshot_size_bytes=0,
            )
        )
        self._state.register_snapshot(new_envelope.step, save_result.value)
        self._state.archive_and_set(new_envelope)

        return Success(new_envelope)

    def _apply_manifest(
        self,
        envelope: ContextEnvelope,
        manifest: AgentManifest | None,
    ) -> Result[ContextEnvelope]:
        """Apply manifest hash to envelope, validating write boundaries.

        Skips re-signing when manifest_hash already matches — avoids wasting
        the signature already computed by create_initial_envelope or
        create_next_envelope. Only verifies the signature when about to re-sign,
        since that path overwrites a potentially tampered signature.
        """
        if manifest is None:
            return Success(envelope)
        result = validate_manifest_boundaries(manifest, set(envelope.payload.keys()))
        if isinstance(result, Failure):
            return result
        manifest_hash = manifest.compute_hash()
        if envelope.manifest_hash == manifest_hash:
            return Success(envelope)
        # Verify before re-signing: prevents overwriting a tampered signature.
        sig_result = verify_signature(
            envelope,
            self._context_broker.signing_secret,
            self.max_signature_age,
        )
        if isinstance(sig_result, Failure):
            return Failure(
                reason="Cannot apply manifest to envelope with invalid or stale signature",
                code=sig_result.code,  # preserves STALE_SIGNATURE or INVALID_SNAPSHOT
            )
        envelope_with_hash = envelope.with_manifest_hash(manifest_hash)
        signed = envelope_with_hash.with_signature(
            compute_signature(envelope_with_hash, self._context_broker.signing_secret)
        )
        return Success(signed)

    def _do_rollback(self, reason: str, consume: bool) -> Result[ContextEnvelope]:
        """Rollback to previous envelope with optional history consumption.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        self._state._assert_lock_held()
        if not self._state.has_history():
            return Failure(
                reason="No previous envelope to rollback to",
                code=ErrorCode.NO_ROLLBACK_AVAILABLE,
            )

        previous_envelope = self._state.peek_last()
        if previous_envelope is None:
            return Failure(
                reason="Invariant violated: has_history() returned true but peek_last() returned None",
                code=ErrorCode.INVALID_STATE,
            )

        self._emit_audit_event(
            RollbackTriggered(
                pipeline_id=self._pipeline_id,
                step=previous_envelope.step,
                reason=reason,
            )
        )

        result = self._rollback_handler.restore_to_previous(
            previous_envelope,
            self._state.snapshot_ids,
            self._snapshot_store,
            reason,
        )
        if isinstance(result, Failure):
            return result
        # RollbackSuccess is the only non-Failure return from restore_to_previous.
        self._emit_audit_event(
            RollbackCompleted(
                pipeline_id=self._pipeline_id,
                step=previous_envelope.step,
                restored_step=result.value.step,
                snapshot_id="",
            )
        )
        if consume:
            self._state.consume_last()
        self._state.set_current(result.value)
        return result

    def rollback(self) -> Result[ContextEnvelope]:
        """Rollback to the last clean state."""
        with self._state.transaction():
            if not self._state.has_history():
                return Failure(
                    reason="No previous envelope to rollback to",
                    code=ErrorCode.NO_ROLLBACK_AVAILABLE,
                )
            return self._do_rollback("Manual rollback", consume=True)

    def get_current_envelope(self) -> ContextEnvelope | None:
        """Get the current envelope."""
        with self._state.transaction() as envelope:
            return envelope

    async def execute_step_with_runner(
        self,
        adapter_name: str,
        manifest: AgentManifest,
    ) -> Result[ContextEnvelope]:
        """Execute a pipeline step by running the named adapter.

        Pipeline sequence:
          1. Look up adapter in registry.
          2. Build ContextSlice from current envelope filtered by manifest.reads.
          3. Check token budget (via _check_budget using manifest + current envelope).
          4. Call adapter.run(slice, manifest) — any exception → Failure.
          5. Merge AgentOutput into payload dict.
          6. Call execute_step_with_manifest(payload, manifest=manifest) to handle
             signing, validation, snapshotting, and rollback as normal.

        Note on concurrent budget enforcement: The budget check at step 3 is advisory under
        concurrent load. The lock is released before adapter.run() (to avoid holding it during
        I/O), so another thread may advance the envelope between the check and execution.
        Token counts are heuristic anyway (character-based estimation). If an overrun occurs,
        execute_step_with_manifest validates post-hoc and rollback is the safety net.

        Args:
            adapter_name: Name of the adapter in the registry to invoke.
            manifest: Agent manifest defining read/write permissions.

        Returns:
            Success, Failure, or RollbackSuccess — same contract as execute_step.

        Raises:
            Nothing. All errors are returned as Failure.
        """
        if self.registry is None:
            return Failure(
                reason="No AdapterRegistry configured on this pipeline",
                code=ErrorCode.NO_REGISTRY,
            )

        adapter_result = self.registry.get(adapter_name)
        if isinstance(adapter_result, Failure):
            return adapter_result
        adapter = adapter_result.value

        with self._state.transaction() as current_envelope:
            assert current_envelope is not None
            step = current_envelope.step + 1
            self._emit_audit_event(
                StepExecutionStarted(
                    pipeline_id=self._pipeline_id,
                    step=step,
                    adapter_name=adapter_name,
                    agent_name=manifest.agent_id,
                )
            )
            slice_ = self._build_context_slice(current_envelope, manifest)
            budget_result = self._check_budget(manifest, current_envelope)
            if isinstance(budget_result, Failure):
                self._emit_audit_event(
                    StepExecutionFailed(
                        pipeline_id=self._pipeline_id,
                        step=step,
                        adapter_name=adapter_name,
                        agent_name=manifest.agent_id,
                        error_code=budget_result.code.value,
                    )
                )
                return budget_result

        try:
            agent_output = await adapter.run(slice_, manifest)
        except Exception as e:
            self._emit_audit_event(
                StepExecutionFailed(
                    pipeline_id=self._pipeline_id,
                    step=step,
                    adapter_name=adapter_name,
                    agent_name=manifest.agent_id,
                    error_code=ErrorCode.ADAPTER_EXECUTION_FAILED.value,
                )
            )
            return Failure(
                reason=f"Adapter '{adapter_name}' failed: {type(e).__name__}: {e}",
                code=ErrorCode.ADAPTER_EXECUTION_FAILED,
            )

        payload = agent_output_to_payload(agent_output)
        return self.execute_step_with_manifest(payload, manifest=manifest)

    async def execute_parallel_step(
        self,
        fork_specs: list[ForkSpec],
        join_strategy: JoinStrategy,
    ) -> Result[ContextEnvelope]:
        """Execute N adapter forks in parallel, merge via join strategy, commit one result.

        Pipeline sequence:
          1. Validate inputs (non-empty specs, registry set, at least one prior step).
          2. Acquire lock: guard None envelope, build slices, check per-fork budgets. Release lock.
          3. Execute forks concurrently (lock NOT held). All strategies route through
             apply_join_strategy — no direct calls to private join functions.
          4. On Failure from join: return immediately — state unchanged.
          5. Commit merged payload via execute_step_with_manifest (unchanged public API).
          6. Attach fork metadata, re-sign, re-save snapshot, update in-memory state.

        Args:
            fork_specs:     One ForkSpec per fork. Must be non-empty.
            join_strategy:  How to merge results. See JoinStrategy enum.

        Returns:
            Success(envelope) — with fork metadata fields populated.
            Note: forks_succeeded is hardcoded to 1 for FIRST_WINS strategy
            since the actual count of passing forks is unknowable after
            cancellation. For UNION and VOTE the count is accurate.
            Failure — if input validation, all forks, or merge fails. State unchanged.
            RollbackSuccess — if validator triggers rollback during commit.
        """
        if not fork_specs:
            return Failure(
                reason="fork_specs must be non-empty",
                code=ErrorCode.INVALID_STATE,
            )
        if self.registry is None:
            return Failure(
                reason="No AdapterRegistry configured on this pipeline",
                code=ErrorCode.NO_REGISTRY,
            )

        with self._state.transaction() as pre_fork_envelope:
            if pre_fork_envelope is None:
                return Failure(
                    reason="execute_parallel_step requires at least one prior sequential step",
                    code=ErrorCode.INVALID_STATE,
                )
            fork_slices = [
                self._build_context_slice(pre_fork_envelope, spec.manifest)
                for spec in fork_specs
            ]
            for spec in fork_specs:
                budget_result = self._check_budget(spec.manifest, pre_fork_envelope)
                if isinstance(budget_result, Failure):
                    return budget_result

            self._emit_audit_event(ForkStarted(
                pipeline_id=self._pipeline_id,
                step=pre_fork_envelope.step,
                fork_count=len(fork_specs),
            ))

        parallel_id = str(uuid.uuid4())
        fork_coros = [
            run_single_fork(
                fork_index=i,
                spec=spec,
                slice_=slice_,
                pre_fork_envelope=pre_fork_envelope,
                registry=self.registry,
                validator=self._handoff_validator,
            )
            for i, (spec, slice_) in enumerate(zip(fork_specs, fork_slices))
        ]

        if join_strategy == JoinStrategy.FIRST_WINS:
            merged_result = await apply_join_strategy(
                join_strategy,
                fork_results=[],
                first_wins_coros=[
                    (i, spec, coro)
                    for i, (spec, coro) in enumerate(zip(fork_specs, fork_coros))
                ],
            )
            forks_succeeded = 1 if isinstance(merged_result, Success) else 0
            self._emit_audit_event(ForkCompleted(
                pipeline_id=self._pipeline_id,
                step=pre_fork_envelope.step,
                forks_succeeded=forks_succeeded,
            ))
        else:
            collected: list[ForkResult] = list(await asyncio.gather(*fork_coros))
            forks_succeeded = sum(1 for r in collected if r.success)
            self._emit_audit_event(ForkCompleted(
                pipeline_id=self._pipeline_id,
                step=pre_fork_envelope.step,
                forks_succeeded=forks_succeeded,
            ))
            merged_result = await apply_join_strategy(join_strategy, collected, None)

        if isinstance(merged_result, Failure):
            return merged_result

        self._emit_audit_event(JoinCompleted(
            pipeline_id=self._pipeline_id,
            step=pre_fork_envelope.step,
            join_strategy=join_strategy.value,
        ))

        combined_hash = _combine_manifest_hashes([s.manifest for s in fork_specs])

        # Commit merged payload with fork metadata in a single transaction.
        # This avoids the race condition where another thread calling
        # get_current_envelope() gets a stale envelope without fork metadata
        # between the step commit and the metadata update.
        with self._state.transaction() as current_envelope:
            if current_envelope is None:
                return Failure(
                    reason="execute_parallel_step requires at least one prior sequential step",
                    code=ErrorCode.INVALID_STATE,
                )
            if current_envelope is not pre_fork_envelope:
                return Failure(
                    reason="Pipeline state changed during parallel execution — fork output invalidated",
                    code=ErrorCode.MERGE_CONFLICT,
                )

            result = self._context_broker.create_next_envelope(
                previous_envelope=current_envelope,
                agent_output=merged_result.value,
                manifest_hash=combined_hash,
            )
            if isinstance(result, Failure):
                return result
            new_envelope = result.value

            envelope_with_meta = new_envelope.with_fork_metadata(
                fork_id=parallel_id,
                join_strategy=join_strategy.value,
                fork_count=len(fork_specs),
                forks_succeeded=forks_succeeded,
            )
            signed = envelope_with_meta.with_signature(
                compute_signature(
                    envelope_with_meta, self._context_broker.signing_secret
                )
            )

            validation_result = self._handoff_validator.validate_handoff(
                previous_envelope=current_envelope, current_envelope=signed
            )
            if isinstance(validation_result, Failure):
                return validation_result

            if self._handoff_validator.should_rollback(validation_result.value):
                # current_envelope was already snapshotted — skip redundant save.
                self._state.push_current_to_history()
                return RollbackSuccess(
                    value=current_envelope,
                    reason=validation_result.value.contradiction_details
                    or "Contradiction detected",
                )

            save_result = self._snapshot_store.save_snapshot(signed)
            if isinstance(save_result, Failure):
                return save_result
            self._state.register_snapshot(signed.step, save_result.value)
            self._state.archive_and_set(signed)

            return Success(signed)

    def _build_context_slice(
        self,
        current_envelope: ContextEnvelope | None,
        manifest: AgentManifest,
    ) -> ContextSlice:
        """Build a ContextSlice from the current envelope, filtered to manifest.reads.

        If current_envelope is None (first step), returns an empty slice.
        Sections not declared in manifest.reads are excluded regardless of
        whether they exist in the payload.

        REQUIRES: no lock needed — reads only from immutable envelope.
        """
        if current_envelope is None:
            return ContextSlice(
                pipeline_id=self._pipeline_id,
                step=0,
                agent_id=manifest.agent_id,
                sections={},
                token_count=0,
                manifest_hash=manifest.compute_hash(),
            )
        permitted = manifest.reads & set(current_envelope.payload.keys())
        sections: JSONDict = {k: current_envelope.payload[k] for k in permitted}
        token_count = estimate_tokens(sections) if sections else 0
        return ContextSlice(
            pipeline_id=current_envelope.pipeline_id,
            step=current_envelope.step,
            agent_id=manifest.agent_id,
            sections=sections,
            token_count=token_count,
            manifest_hash=manifest.compute_hash(),
        )
