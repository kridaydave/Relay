"""Core pipeline orchestration for Relay v0.1.

Owns: pipeline lifecycle, component coordination.
Does NOT: define agent behavior, manage prompts.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import json
import uuid

from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope
from relay.slicer import AgentManifest, SlicePacker
from relay.snapshot import SnapshotStore
from relay.types import Failure, Result, Success, RollbackSuccess
from relay.validator import HandoffValidator, ValidationResult, validate_manifest_boundaries


@dataclass
class CoreRelayPipeline:
    """Base class for pipeline orchestration.

    Owns: pipeline lifecycle, component coordination.
    Does NOT: define agent behavior, manage prompts.
    """
    signing_secret: str
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"
    token_counter: Optional[TokenCounter] = None
    slice_packer: Optional[SlicePacker] = None

    _pipeline_id: str = field(init=False, repr=False)
    _context_broker: ContextBroker = field(init=False, repr=False)
    _handoff_validator: HandoffValidator = field(init=False, repr=False)
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    _current_envelope: ContextEnvelope | None = field(default=None, init=False, repr=False)
    _previous_envelopes: list[ContextEnvelope] = field(default_factory=list, init=False, repr=False)
    _snapshot_ids: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _enforcer: Optional[HardCapEnforcer] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._pipeline_id = uuid.uuid4().hex
        self._context_broker = ContextBroker(
            signing_secret=self.signing_secret,
            token_budget_total=self.token_budget
        )
        self._handoff_validator = HandoffValidator()
        self._snapshot_store = SnapshotStore(storage_path=self.storage_path)
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self._pipeline_id, self.token_counter)
        else:
            self._enforcer = None

    def execute_step(self, agent_output: dict[str, Any]) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output."""
        return self.execute_step_with_manifest(agent_output, manifest=None)

    def execute_step_with_manifest(
        self,
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest] = None,
    ) -> Result[ContextEnvelope]:
        """Execute a pipeline step with optional agent manifest for budget and boundary validation.

        Args:
            agent_output: The output from the agent.
            manifest: Optional agent manifest for enforcing budget and write boundaries.
        """
        if self._current_envelope is None:
            envelope_result = self._context_broker.create_initial_envelope(
                pipeline_id=self._pipeline_id,
                initial_payload=agent_output
            )
            if isinstance(envelope_result, Failure):
                return envelope_result

            new_envelope = envelope_result.value

            if manifest is not None:
                manifest_hash = manifest.compute_hash()
                new_envelope = ContextEnvelope(
                    relay_version=new_envelope.relay_version,
                    pipeline_id=new_envelope.pipeline_id,
                    step=new_envelope.step,
                    timestamp=new_envelope.timestamp,
                    token_budget_used=new_envelope.token_budget_used,
                    token_budget_total=new_envelope.token_budget_total,
                    payload=new_envelope.payload,
                    manifest_hash=manifest_hash,
                    signature=new_envelope.signature,
                )

            self._current_envelope = new_envelope
            return Success(new_envelope)

        if self._enforcer is not None and manifest is not None:
            projected_slice = self._slice_payload(manifest)
            self._enforcer.check(self._current_envelope, projected_slice)

        envelope_result = self._context_broker.create_next_envelope(
            previous_envelope=self._current_envelope,
            agent_output=agent_output
        )
        if isinstance(envelope_result, Failure):
            return envelope_result

        new_envelope = envelope_result.value

        if manifest is not None:
            written_sections = set(agent_output.keys())
            try:
                validate_manifest_boundaries(new_envelope, manifest, written_sections)
            except Exception as e:
                return self._rollback_to_previous_with_reason(new_envelope, str(e))

            manifest_hash = manifest.compute_hash()
            token_used = new_envelope.token_budget_used
            new_envelope = ContextEnvelope(
                relay_version=new_envelope.relay_version,
                pipeline_id=new_envelope.pipeline_id,
                step=new_envelope.step,
                timestamp=new_envelope.timestamp,
                token_budget_used=token_used,
                token_budget_total=new_envelope.token_budget_total,
                payload=new_envelope.payload,
                manifest_hash=manifest_hash,
                signature="",
            )

            signed_envelope = self._context_broker.create_next_envelope(
                previous_envelope=self._current_envelope,
                agent_output=agent_output
            )
            if isinstance(signed_envelope, Failure):
                return signed_envelope
            new_envelope = ContextEnvelope(
                relay_version=signed_envelope.value.relay_version,
                pipeline_id=signed_envelope.value.pipeline_id,
                step=signed_envelope.value.step,
                timestamp=signed_envelope.value.timestamp,
                token_budget_used=token_used,
                token_budget_total=signed_envelope.value.token_budget_total,
                payload=signed_envelope.value.payload,
                manifest_hash=manifest_hash,
                signature=signed_envelope.value.signature,
            )

        self._previous_envelopes.append(self._current_envelope)

        current_snapshot_result = self._snapshot_store.save_snapshot(self._current_envelope)
        if isinstance(current_snapshot_result, Failure):
            return current_snapshot_result
        self._snapshot_ids[self._current_envelope.step] = current_snapshot_result.value

        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=self._current_envelope,
            current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        validation = validation_result.value
        if self._handoff_validator.should_rollback(validation):
            return self._rollback_to_previous(new_envelope, validation)

        snapshot_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(snapshot_result, Failure):
            return snapshot_result

        snapshot_id = snapshot_result.value
        self._snapshot_ids[new_envelope.step] = snapshot_id
        if self._previous_envelopes:
            oldest_step = self._previous_envelopes[0].step
            self._snapshot_ids.pop(oldest_step, None)

        self._current_envelope = new_envelope
        return Success(new_envelope)

    def _slice_payload(self, manifest: AgentManifest) -> str:
        """Slice the current payload based on the manifest and slice packer."""
        if self.slice_packer is None or self._current_envelope is None:
            return ""
        sliced = self.slice_packer.pack(self._current_envelope.payload, manifest)
        return json.dumps(sliced)

    def _rollback_to_previous(
        self,
        proposed_envelope: ContextEnvelope,
        validation: ValidationResult
    ) -> Result[ContextEnvelope]:
        """Rollback to previous envelope on contradiction."""
        reason = validation.contradiction_details or "Contradiction detected"
        return self._rollback_to_previous_with_reason(proposed_envelope, reason)

    def _rollback_to_previous_with_reason(
        self,
        proposed_envelope: ContextEnvelope,
        reason: str
    ) -> Result[ContextEnvelope]:
        """Rollback to previous envelope with explicit reason."""
        if not self._previous_envelopes:
            return Failure(reason="No previous envelope to rollback to", code="NO_ROLLBACK_AVAILABLE")

        previous_envelope = self._previous_envelopes[-1]
        snapshot_id = self._snapshot_ids.get(previous_envelope.step)
        if snapshot_id is None:
            return Failure(reason="No snapshot registered for step", code="NO_SNAPSHOT_REGISTERED")

        restore_result = self._snapshot_store.load_snapshot(snapshot_id)
        if isinstance(restore_result, Failure):
            return restore_result

        restored_envelope = restore_result.value
        self._current_envelope = restored_envelope
        return RollbackSuccess(value=restored_envelope, reason=reason)

    def rollback(self) -> Result[ContextEnvelope]:
        """Rollback to the last clean state."""
        if not self._previous_envelopes:
            return Failure(reason="No previous envelope to rollback to", code="NO_ROLLBACK_AVAILABLE")

        previous_envelope = self._previous_envelopes[-1]
        snapshot_id = self._snapshot_ids.get(previous_envelope.step)
        if snapshot_id is None:
            return Failure(reason="No snapshot registered for step", code="NO_SNAPSHOT_REGISTERED")

        restore_result = self._snapshot_store.load_snapshot(snapshot_id)
        if isinstance(restore_result, Failure):
            return restore_result

        self._previous_envelopes.pop()
        restored_envelope = restore_result.value
        self._current_envelope = restored_envelope
        return RollbackSuccess(value=restored_envelope, reason="Manual rollback")

    def get_current_envelope(self) -> ContextEnvelope | None:
        """Get the current envelope."""
        return self._current_envelope
