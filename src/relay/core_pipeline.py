"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker, create_context_broker
from relay.envelope import _compute_signature, ContextEnvelope, estimate_tokens, serialize_slice
from relay.pipeline_rollback import RollbackHandler
from relay.pipeline_snapshot import SnapshotManager
from relay.pipeline_state import PipelineState
from relay.runners import AdapterRegistry, AgentOutput
from relay.runners.protocol import ContextSlice
from relay.slicer import AgentManifest, SlicePacker
from relay.snapshot import SnapshotStore
from relay.types import ErrorCode, Failure, Result, RollbackSuccess, Success
from relay.validator import (
    HandoffValidator,
    ValidationResult,
    validate_manifest_boundaries,
)


def _agent_output_to_payload(
    output: AgentOutput,
    manifest: AgentManifest,
) -> dict[str, Any]:
    """Convert AgentOutput to a payload dict suitable for execute_step_with_manifest.

    Merges text, structured fields, and tool_calls into a dict unconditionally.
    No filtering by manifest.writes is performed — that validation happens in
    validate_manifest_boundaries inside execute_step_with_manifest.

    This function does NOT validate — it only shapes the payload. Validation is
    the responsibility of validate_manifest_boundaries inside execute_step_with_manifest.
    """
    raw: dict[str, Any] = {"text": output.text, **output.structured}
    if output.tool_calls:
        raw["tool_calls"] = output.tool_calls
    return raw


@dataclass
class CoreRelayPipeline:
    """Base class for pipeline orchestration.

    Owns: pipeline lifecycle, component coordination, budget enforcement, slicer dispatch.
    Does NOT: define agent behavior, manage prompts.
    """

    signing_secret: str
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"
    token_counter: Optional[TokenCounter] = None
    slice_packer: Optional[SlicePacker] = None
    registry: Optional[AdapterRegistry] = None

    _pipeline_id: str = field(init=False, repr=False)
    _state: PipelineState = field(init=False, repr=False)
    _context_broker: ContextBroker = field(init=False, repr=False)
    _handoff_validator: HandoffValidator = field(init=False, repr=False)
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    _snapshot_manager: SnapshotManager = field(init=False, repr=False)
    _rollback_handler: RollbackHandler = field(init=False, repr=False)
    _enforcer: Optional[HardCapEnforcer] = field(init=False, repr=False)

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
        self._snapshot_manager = SnapshotManager(self._snapshot_store)
        self._rollback_handler = RollbackHandler()
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self._pipeline_id, self.token_counter)
        else:
            self._enforcer = None
        # registry is set directly from __init__ field, no additional setup needed

    def close(self) -> None:
        """Release pipeline resources.

        Cleans up token counter if it has a close method.
        """
        if self.token_counter is not None:
            self.token_counter.close()

    def __enter__(self) -> "CoreRelayPipeline":
        """Enter the pipeline context."""
        return self

    def __exit__(self, *_: object) -> None:
        """Exit the pipeline context and release resources."""
        self.close()

    def execute_step(self, agent_output: dict[str, Any]) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output."""
        return self.execute_step_with_manifest(agent_output, manifest=None)

    def execute_step_with_manifest(
        self,
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest] = None,
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
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Handle the first pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        budget_result = self._check_budget(manifest, None)
        if isinstance(budget_result, Failure):
            return budget_result

        result = self._context_broker.create_initial_envelope(
            pipeline_id=self._pipeline_id, initial_payload=agent_output
        )
        if isinstance(result, Failure):
            return result

        apply_result = self._apply_manifest(result.value, manifest)
        if isinstance(apply_result, Failure):
            return apply_result
        new_envelope = apply_result.value
        self._state.set_current(new_envelope)
        return Success(new_envelope)

    def _handle_subsequent_step(
        self,
        current_envelope: ContextEnvelope,
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Handle a subsequent pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        budget_result = self._check_budget(manifest, current_envelope)
        if isinstance(budget_result, Failure):
            return budget_result

        result = self._context_broker.create_next_envelope(
            previous_envelope=current_envelope, agent_output=agent_output
        )
        if isinstance(result, Failure):
            return result
        new_envelope = result.value

        result = self._apply_manifest_if_present(new_envelope, manifest)
        if isinstance(result, Failure):
            return result
        new_envelope = result.value

        return self._finalize_step(current_envelope, new_envelope)

    def _check_budget(
        self,
        manifest: Optional[AgentManifest],
        current_envelope: ContextEnvelope | None,
    ) -> Result[None]:
        """Check token budget if manifest and enforcer present.

        Checks both pipeline-level budget (token_budget_total) and per-agent
        budget (manifest.max_tokens) when available.

        When current_envelope is None (initial step), token_budget_used is 0.
        """
        if manifest is not None and self._enforcer is not None:
            if current_envelope is not None:
                projected = self._slice_payload(manifest, current_envelope)
            else:
                projected = serialize_slice({s: "<slice>" for s in manifest.writes})
            budget_used = (
                current_envelope.token_budget_used
                if current_envelope is not None
                else 0
            )
            envelope_for_check = current_envelope
            if envelope_for_check is None:
                # Build a temporary envelope for budget checking on initial step.
                from datetime import datetime, timezone

                envelope_for_check = ContextEnvelope(
                    relay_version="0.0.0",
                    pipeline_id=self._pipeline_id,
                    step=0,
                    timestamp=datetime.now(timezone.utc),
                    token_budget_used=budget_used,
                    token_budget_total=self.token_budget,
                    payload={},
                    manifest_hash="",
                    signature="",
                )
            enforcer_result = self._enforcer.check(envelope_for_check, projected)
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

    def _apply_manifest_if_present(
        self,
        envelope: ContextEnvelope,
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Apply manifest hash to envelope when manifest is provided.

        Validates write boundaries (agent can only write to sections in
        manifest.writes). Returns Success with the updated envelope if no
        manifest, or if manifest is valid.

        REQUIRES: caller holds self._state._lock.
        """
        if manifest is None:
            return Success(envelope)
        return self._apply_manifest(envelope, manifest)

    def _finalize_step(
        self,
        current_envelope: ContextEnvelope,
        new_envelope: ContextEnvelope,
    ) -> Result[ContextEnvelope]:
        """Archive envelope, validate handoff, and advance pipeline.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is is non-reentrant.
        """
        self._state.archive_and_set(new_envelope)

        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=current_envelope, current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        if self._handoff_validator.should_rollback(validation_result.value):
            save_result = self._snapshot_manager.save(current_envelope)
            if isinstance(save_result, Failure):
                return save_result
            self._state.snapshot_ids[current_envelope.step] = save_result.value
            return self._rollback_on_contradiction(
                new_envelope, validation_result.value
            )

        return self._advance_to_new_envelope(new_envelope)

    def _apply_manifest(
        self,
        envelope: ContextEnvelope,
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Apply manifest hash to envelope, validating write boundaries.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        """
        if manifest is None:
            return Success(envelope)
        result = validate_manifest_boundaries(manifest, set(envelope.payload.keys()))
        if isinstance(result, Failure):
            return self._rollback_with_reason(result.reason)
        envelope_with_hash = envelope.with_manifest_hash(manifest.compute_hash())
        # Re-sign after setting manifest_hash so signature covers the actual hash.
        signed = envelope_with_hash.with_signature(
            _compute_signature(envelope_with_hash, self._context_broker.signing_secret)
        )
        return Success(signed)

    def _rollback_on_contradiction(
        self, proposed_envelope: ContextEnvelope, validation: ValidationResult
    ) -> Result[ContextEnvelope]:
        """Rollback to previous envelope on contradiction.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        reason = validation.contradiction_details or "Contradiction detected"
        return self._rollback_with_reason(reason)

    def _rollback_with_reason(self, reason: str) -> Result[ContextEnvelope]:
        """Rollback to previous envelope with explicit reason.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        if not self._state.has_history():
            return Failure(
                reason="No previous envelope to rollback to",
                code=ErrorCode.NO_ROLLBACK_AVAILABLE,
            )

        previous_envelope = self._state.peek_last()
        assert previous_envelope is not None  # guarded by has_history()

        result = self._rollback_handler.restore_to_previous(
            previous_envelope,
            self._state.snapshot_ids,
            self._snapshot_store,
            reason,
        )
        if isinstance(result, RollbackSuccess):
            self._state.set_current(result.value)
        return result

    def _rollback_and_consume(self, reason: str) -> Result[ContextEnvelope]:
        """Rollback to previous envelope and consume history.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        if not self._state.has_history():
            return Failure(
                reason="No previous envelope to rollback to",
                code=ErrorCode.NO_ROLLBACK_AVAILABLE,
            )

        previous_envelope = self._state.peek_last()
        assert previous_envelope is not None  # guarded by has_history()

        result = self._rollback_handler.restore_to_previous(
            previous_envelope,
            self._state.snapshot_ids,
            self._snapshot_store,
            reason,
        )
        if isinstance(result, RollbackSuccess):
            self._state.consume_last()
            self._state.set_current(result.value)
        return result

    def _advance_to_new_envelope(
        self,
        new_envelope: ContextEnvelope,
    ) -> Result[ContextEnvelope]:
        """Advance pipeline to new envelope, saving new envelope's snapshot.

        Saves the new envelope's snapshot and cleans up the oldest snapshot from history.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        oldest_in_history = self._state.peek_last()
        save_result = self._snapshot_manager.save(new_envelope)
        if isinstance(save_result, Failure):
            return save_result
        self._state.snapshot_ids[new_envelope.step] = save_result.value
        if oldest_in_history is not None:
            self._state.snapshot_ids.pop(oldest_in_history.step, None)

        return Success(new_envelope)

    def _slice_payload(
        self, manifest: AgentManifest, current_envelope: ContextEnvelope | None
    ) -> str:
        """Slice the current payload based on the manifest and slice packer."""
        if self.slice_packer is None or current_envelope is None:
            return ""
        pack_result = self.slice_packer.pack(current_envelope.payload, manifest)
        if isinstance(pack_result, Failure):
            return ""
        return serialize_slice(pack_result.value)

    def rollback(self) -> Result[ContextEnvelope]:
        """Rollback to the last clean state."""
        with self._state.transaction():
            if not self._state.has_history():
                return Failure(
                    reason="No previous envelope to rollback to",
                    code=ErrorCode.NO_ROLLBACK_AVAILABLE,
                )
            return self._rollback_and_consume("Manual rollback")

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
        except BaseException as e:
            return Failure(
                reason=f"Adapter '{adapter_name}' raised: {type(e).__name__}: {e}",
                code=ErrorCode.ADAPTER_EXECUTION_FAILED,
            )

        payload = _agent_output_to_payload(agent_output, manifest)
        return self.execute_step_with_manifest(payload, manifest=manifest)

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
        sections = {k: current_envelope.payload[k] for k in permitted}
        token_count = estimate_tokens(sections) if sections else 0
        return ContextSlice(
            pipeline_id=current_envelope.pipeline_id,
            step=current_envelope.step,
            agent_id=manifest.agent_id,
            sections=sections,
            token_count=token_count,
            manifest_hash=manifest.compute_hash(),
        )
