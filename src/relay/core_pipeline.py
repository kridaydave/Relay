"""Core pipeline orchestration for Relay.

Owns: pipeline lifecycle, component coordination, budget enforcement hooks, slicer dispatch.
Does NOT: define agent behaviour, manage prompts, implement token counting, or implement slicing strategies.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope
from relay.pipeline_rollback import RollbackHandler
from relay.pipeline_snapshot import SnapshotManager
from relay.pipeline_state import PipelineState
from relay.slicer import AgentManifest, SlicePacker
from relay.snapshot import SnapshotStore
from relay.types import ErrorCode, Failure, Result, RollbackSuccess, Success
from relay.validator import (
    HandoffValidator,
    ValidationResult,
    validate_manifest_boundaries,
)


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
        self._context_broker = ContextBroker(
            signing_secret=self.signing_secret, token_budget_total=self.token_budget
        )
        self._handoff_validator = HandoffValidator()
        self._snapshot_store = SnapshotStore(storage_path=self.storage_path)
        self._snapshot_manager = SnapshotManager(self._snapshot_store)
        self._rollback_handler = RollbackHandler()
        if self.token_counter is not None:
            self._enforcer = HardCapEnforcer(self._pipeline_id, self.token_counter)
        else:
            self._enforcer = None

    def close(self) -> None:
        """Release pipeline resources.

        Cleans up token counter if it has a close method.
        """
        if self.token_counter is not None and hasattr(self.token_counter, "close"):
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

            return self._handle_subsequent_step(agent_output, manifest)

    def _handle_initial_step(
        self,
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Handle the first pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        result = self._context_broker.create_initial_envelope(
            pipeline_id=self._pipeline_id, initial_payload=agent_output
        )
        if isinstance(result, Failure):
            return result

        new_envelope = self._apply_manifest(result.value, manifest)
        self._state.set_current(new_envelope)
        return Success(new_envelope)

    def _handle_subsequent_step(
        self,
        agent_output: dict[str, Any],
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Handle a subsequent pipeline step.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        current_envelope = self._state.current()
        if current_envelope is None:
            return Failure(
                reason="Current envelope is None - invalid state",
                code=ErrorCode.INVALID_STATE,
            )

        budget_result = self._check_budget(manifest, current_envelope)
        if isinstance(budget_result, Failure):
            return budget_result

        result = self._create_next_envelope(current_envelope, agent_output)
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
        current_envelope: ContextEnvelope,
    ) -> Result[None]:
        """Check token budget if manifest and enforcer present."""
        if manifest is not None and self._enforcer is not None:
            projected = self._slice_payload(manifest, current_envelope)
            return self._enforcer.check(current_envelope, projected)
        return Success(None)

    def _create_next_envelope(
        self,
        current_envelope: ContextEnvelope,
        agent_output: dict[str, Any],
    ) -> Result[ContextEnvelope]:
        """Create the next envelope from current envelope and agent output.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        return self._context_broker.create_next_envelope(
            previous_envelope=current_envelope, agent_output=agent_output
        )

    def _apply_manifest_if_present(
        self,
        envelope: ContextEnvelope,
        manifest: Optional[AgentManifest],
    ) -> Result[ContextEnvelope]:
        """Apply manifest validation if manifest provided.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        if manifest is None:
            return Success(envelope)
        return self._apply_manifest_validation(envelope, manifest)

    def _finalize_step(
        self,
        current_envelope: ContextEnvelope,
        new_envelope: ContextEnvelope,
    ) -> Result[ContextEnvelope]:
        """Save snapshot, validate handoff, and advance pipeline.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        self._state.archive_and_set(new_envelope)

        save_result = self._snapshot_manager.save(current_envelope)
        if isinstance(save_result, Failure):
            return save_result
        self._state.snapshot_ids[current_envelope.step] = save_result.value

        validation_result = self._handoff_validator.validate_handoff(
            previous_envelope=current_envelope, current_envelope=new_envelope
        )
        if isinstance(validation_result, Failure):
            return validation_result

        if self._handoff_validator.should_rollback(validation_result.value):
            return self._rollback_on_contradiction(
                new_envelope, validation_result.value
            )

        return self._advance_to_new_envelope(new_envelope)

    def _apply_manifest(
        self,
        envelope: ContextEnvelope,
        manifest: Optional[AgentManifest],
    ) -> ContextEnvelope:
        """Apply manifest hash to envelope if manifest provided.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        if manifest is None:
            return envelope
        return envelope.with_manifest_hash(manifest.compute_hash())

    def _apply_manifest_validation(
        self,
        new_envelope: ContextEnvelope,
        manifest: AgentManifest,
    ) -> Result[ContextEnvelope]:
        """Validate manifest boundaries and apply manifest hash to envelope.

        Uses the already-created envelope (passed in) instead of re-creating one.
        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        result = validate_manifest_boundaries(
            new_envelope, manifest, set(new_envelope.payload.keys())
        )
        if isinstance(result, Failure):
            return self._rollback_with_reason(result.reason)

        return Success(new_envelope.with_manifest_hash(manifest.compute_hash()))

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

        return self._do_rollback(reason, consume_history=False)

    def _do_rollback(self, reason: str, consume_history: bool) -> Result[ContextEnvelope]:
        """Execute rollback to previous envelope.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        previous_envelope = self._state.peek_last()
        if previous_envelope is None:
            return Failure(
                reason="No previous envelope to rollback to",
                code=ErrorCode.INVALID_STATE,
            )
        result = self._rollback_handler.restore_to_previous(
            previous_envelope,
            self._state.snapshot_ids,
            self._snapshot_store,
            reason,
        )
        if isinstance(result, RollbackSuccess):
            if consume_history:
                self._state.consume_last()
            self._state.set_current(result.value)
        return result

    def _advance_to_new_envelope(
        self,
        new_envelope: ContextEnvelope,
    ) -> Result[ContextEnvelope]:
        """Advance pipeline to new envelope, saving snapshot and cleaning up old.

        REQUIRES: caller holds self._state._lock via transaction() context manager.
        Must NOT call self._state.transaction() — lock is non-reentrant.
        """
        """Advance pipeline to new envelope, saving snapshot and cleaning up old."""
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
        return json.dumps(pack_result.value)

    def rollback(self) -> Result[ContextEnvelope]:
        """Rollback to the last clean state."""
        with self._state.transaction():
            if not self._state.has_history():
                return Failure(
                    reason="No previous envelope to rollback to",
                    code=ErrorCode.NO_ROLLBACK_AVAILABLE,
                )
            return self._do_rollback("Manual rollback", consume_history=True)

    def get_current_envelope(self) -> ContextEnvelope | None:
        """Get the current envelope."""
        with self._state.transaction() as envelope:
            return envelope

    # Backward-compatible accessors for tests
    @property
    def _current_envelope(self) -> ContextEnvelope | None:
        """Expose current envelope for test compatibility."""
        return self._state.current()

    @property
    def _snapshot_ids(self) -> dict[int, str]:
        """Expose snapshot_ids for test compatibility."""
        return self._state.snapshot_ids
