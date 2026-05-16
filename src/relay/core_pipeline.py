"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field

from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker, create_context_broker
from relay.envelope import (
    ContextEnvelope,
    compute_signature,
    estimate_tokens,
    serialize_slice,
)
from relay.parallel import ForkResult, ForkSpec, JoinStrategy, apply_join_strategy
from relay.parallel.fork_runner import run_single_fork
from relay.parallel.types import agent_output_to_payload
from relay.pipeline_rollback import RollbackHandler
from relay.pipeline_state import PipelineState
from relay.runners import AdapterRegistry
from relay.runners.protocol import ContextSlice
from relay.slicer import AgentManifest, SlicePacker
from relay.snapshot import SnapshotStore
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
    """

    signing_secret: str
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"
    token_counter: TokenCounter | None = None
    slice_packer: SlicePacker | None = None
    registry: AdapterRegistry | None = None

    _pipeline_id: str = field(init=False, repr=False)
    _state: PipelineState = field(init=False, repr=False)
    _context_broker: ContextBroker = field(init=False, repr=False)
    _handoff_validator: HandoffValidator = field(init=False, repr=False)
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    _rollback_handler: RollbackHandler = field(init=False, repr=False)
    _enforcer: HardCapEnforcer | None = field(init=False, repr=False)

    @classmethod
    def create(
        cls,
        signing_secret: str,
        token_budget: int = 8000,
        storage_path: str = "./relay_data/snapshots",
        token_counter: TokenCounter | None = None,
        slice_packer: SlicePacker | None = None,
        registry: AdapterRegistry | None = None,
    ) -> Result["CoreRelayPipeline"]:
        """Create a pipeline with Result-based error handling.

        Use this factory instead of direct construction to handle
        validation errors without exceptions.
        """
        broker_result = create_context_broker(
            signing_secret=signing_secret, token_budget_total=token_budget
        )
        if isinstance(broker_result, Failure):
            return broker_result
        return Success(
            cls(
                signing_secret=signing_secret,
                token_budget=token_budget,
                storage_path=storage_path,
                token_counter=token_counter,
                slice_packer=slice_packer,
                registry=registry,
            )
        )

    def __post_init__(self) -> None:
        self._pipeline_id = uuid.uuid4().hex
        self._state = PipelineState(pipeline_id=self._pipeline_id)
        broker_result = create_context_broker(
            signing_secret=self.signing_secret, token_budget_total=self.token_budget
        )
        if isinstance(broker_result, Failure):
            raise ValueError(broker_result.reason)
        self._context_broker = broker_result.value
        self._handoff_validator = HandoffValidator()
        self._snapshot_store = SnapshotStore(storage_path=self.storage_path)
        self._rollback_handler = RollbackHandler()
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self.token_counter)
        else:
            self._enforcer = None

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

        Releases token counter resources if one was provided.
        """
        if self.token_counter is not None:
            self.token_counter.close()

    def __enter__(self) -> "CoreRelayPipeline":
        """Enter the pipeline context."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit the pipeline context and release resources."""
        self.close()

    def execute_step(self, agent_output: JSONDict) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output."""
        return self.execute_step_with_manifest(agent_output, manifest=None)

    def execute_step_with_manifest(
        self,
        agent_output: JSONDict,
        manifest: AgentManifest | None = None,
    ) -> Result[ContextEnvelope]:
        """Execute a pipeline step with optional manifest for budget/boundary validation."""
        with self._state.transaction() as current_envelope:
            if current_envelope is None:
                return self._handle_initial_step(agent_output, manifest)

            return self._handle_subsequent_step(
                current_envelope, agent_output, manifest
            )

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
        if manifest is not None and self._enforcer is not None:
            if current_envelope is not None:
                slice_result = self._slice_payload(manifest, current_envelope)
                if isinstance(slice_result, Failure):
                    return slice_result
                projected = slice_result.value
            else:
                projected = (
                    serialize_slice(agent_output)
                    if agent_output is not None
                    else serialize_slice(
                        dict[str, object]({s: "<slice>" for s in manifest.writes})
                    )
                )
            budget_used = (
                current_envelope.token_budget_used
                if current_envelope is not None
                else 0
            )
            enforcer_result = self._enforcer.check(
                budget_used, self.token_budget, projected
            )
            if isinstance(enforcer_result, Failure):
                return enforcer_result

            # Per-agent max_tokens check (manifest.max_tokens).
            if manifest.max_tokens is not None:
                projected_cost = self._enforcer.counter.count(projected)
                if projected_cost > manifest.max_tokens:
                    return Failure(
                        reason=(
                            f"Agent budget exceeded: projected {projected_cost} tokens "
                            f"exceeds manifest.max_tokens={manifest.max_tokens}"
                        ),
                        code=ErrorCode.TOKEN_BUDGET_EXCEEDED,
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
        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=current_envelope, current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        if self._handoff_validator.should_rollback(validation_result.value):
            save_result = self._snapshot_store.save_snapshot(current_envelope)
            if isinstance(save_result, Failure):
                return save_result
            self._state.register_snapshot(current_envelope.step, save_result.value)
            self._state.push_current_to_history()
            return RollbackSuccess(
                value=current_envelope,
                reason=validation_result.value.contradiction_details
                or "Contradiction detected",
            )

        save_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(save_result, Failure):
            return save_result
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
        create_next_envelope.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        """
        if manifest is None:
            return Success(envelope)
        result = validate_manifest_boundaries(manifest, set(envelope.payload.keys()))
        if isinstance(result, Failure):
            return result
        manifest_hash = manifest.compute_hash()
        if envelope.manifest_hash == manifest_hash:
            return Success(envelope)
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

        result = self._rollback_handler.restore_to_previous(
            previous_envelope,
            self._state.snapshot_ids,
            self._snapshot_store,
            reason,
        )
        if isinstance(result, RollbackSuccess):
            if consume:
                self._state.consume_last()
            self._state.set_current(result.value)
        return result

    def _slice_payload(
        self, manifest: AgentManifest, current_envelope: ContextEnvelope | None
    ) -> Result[str]:
        """Slice the current payload based on the manifest and slice packer.

        When no slice_packer is configured, serializes the full payload so budget
        enforcement still has a realistic projection. When current_envelope is None
        (initial step), returns the writes-based stub from _check_budget.
        """
        if self.slice_packer is None:
            if current_envelope is None:
                return Success("")
            return Success(serialize_slice(current_envelope.payload))
        if current_envelope is None:
            return Success("")
        pack_result = self.slice_packer.pack(current_envelope.payload, manifest)
        if isinstance(pack_result, Failure):
            return pack_result
        return Success(serialize_slice(pack_result.value))

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
            slice_ = self._build_context_slice(current_envelope, manifest)
            budget_result = self._check_budget(manifest, current_envelope)
            if isinstance(budget_result, Failure):
                return budget_result

        try:
            agent_output = await adapter.run(slice_, manifest)
        except Exception as e:
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
        else:
            collected: list[ForkResult] = list(await asyncio.gather(*fork_coros))
            forks_succeeded = sum(1 for r in collected if r.success)
            merged_result = await apply_join_strategy(join_strategy, collected, None)

        if isinstance(merged_result, Failure):
            return merged_result

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
                save_result = self._snapshot_store.save_snapshot(current_envelope)
                if isinstance(save_result, Failure):
                    return save_result
                self._state.register_snapshot(current_envelope.step, save_result.value)
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
