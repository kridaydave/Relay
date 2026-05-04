"""Pipeline orchestration for Relay v0.1.

Owns: pipeline lifecycle, component coordination.
Does NOT: define agent behavior, manage prompts.
"""

from dataclasses import dataclass, field
from typing import Any
import uuid

from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope
from relay.snapshot import SnapshotStore
from relay.types import Failure, Result, Success
from relay.validator import HandoffValidator, ValidationResult


@dataclass
class RelayPipeline:
    """Orchestrates the three core components.

    Owns: pipeline lifecycle, component coordination.
    Does NOT: define agent behavior, manage prompts.
    """
    signing_secret: str
    token_budget: int = 8000
    storage_path: str = "./relay_data/snapshots"

    _pipeline_id: str = field(init=False, repr=False)
    _context_broker: ContextBroker = field(init=False, repr=False)
    _handoff_validator: HandoffValidator = field(init=False, repr=False)
    _snapshot_store: SnapshotStore = field(init=False, repr=False)
    _current_envelope: ContextEnvelope | None = field(default=None, init=False, repr=False)
    _previous_envelopes: list[ContextEnvelope] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._pipeline_id = uuid.uuid4().hex
        self._context_broker = ContextBroker(
            signing_secret=self.signing_secret,
            token_budget_total=self.token_budget
        )
        self._handoff_validator = HandoffValidator()
        self._snapshot_store = SnapshotStore(storage_path=self.storage_path)

    def execute_step(self, agent_output: dict[str, Any]) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output."""
        if self._current_envelope is None:
            envelope_result = self._context_broker.create_initial_envelope(
                pipeline_id=self._pipeline_id,
                initial_payload=agent_output
            )
            if isinstance(envelope_result, Failure):
                return envelope_result

            new_envelope = envelope_result.value
            self._current_envelope = new_envelope
            return Success(new_envelope)

        self._previous_envelopes.append(self._current_envelope)

        envelope_result = self._context_broker.create_next_envelope(
            previous_envelope=self._current_envelope,
            agent_output=agent_output
        )
        if isinstance(envelope_result, Failure):
            return envelope_result

        new_envelope = envelope_result.value

        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=self._current_envelope,
            current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        validation = validation_result.value
        if self._handoff_validator.should_rollback(validation):
            return self.rollback()

        snapshot_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(snapshot_result, Failure):
            return snapshot_result

        self._current_envelope = new_envelope
        return Success(new_envelope)

    def rollback(self) -> Result[ContextEnvelope]:
        """Rollback to the last clean state."""
        if not self._previous_envelopes:
            return Failure(reason="No previous envelope to rollback to", code="NO_ROLLBACK_AVAILABLE")

        previous_envelope = self._previous_envelopes[-1]
        restore_result = self._snapshot_store.load_snapshot(
            f"{previous_envelope.step}_{previous_envelope.timestamp.strftime('%Y%m%dT%H%M%S%f')}"
        )
        if isinstance(restore_result, Failure):
            return restore_result

        restored_envelope = restore_result.value
        self._current_envelope = restored_envelope
        return Success(restored_envelope)

    def get_current_envelope(self) -> ContextEnvelope | None:
        """Get the current envelope."""
        return self._current_envelope