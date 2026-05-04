"""Async pipeline orchestration for Relay.

Owns: async lifecycle, concurrent agent execution.
Does NOT: define agent behavior, manage prompts.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
import uuid

from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope
from relay.snapshot import SnapshotStore
from relay.types import Failure, Result, Success
from relay.validator import HandoffValidator


@dataclass(frozen=True)
class AsyncRelayPipeline:
    """Async version of RelayPipeline.

    Owns: async lifecycle, concurrent agent execution.
    Does NOT: define agent behavior.
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
    _executor: ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, '_pipeline_id', uuid.uuid4().hex)
        object.__setattr__(self, '_context_broker', ContextBroker(
            signing_secret=self.signing_secret,
            token_budget_total=self.token_budget
        ))
        object.__setattr__(self, '_handoff_validator', HandoffValidator())
        object.__setattr__(self, '_snapshot_store', SnapshotStore(storage_path=self.storage_path))
        object.__setattr__(self, '_executor', ThreadPoolExecutor(max_workers=1))

    async def execute_step_async(self, agent_output: dict[str, Any]) -> Result[ContextEnvelope]:
        """Execute a pipeline step with agent output asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._execute_step_sync,
            agent_output
        )

    def _execute_step_sync(self, agent_output: dict[str, Any]) -> Result[ContextEnvelope]:
        """Synchronous implementation of execute_step."""
        if self._current_envelope is None:
            envelope_result = self._context_broker.create_initial_envelope(
                pipeline_id=self._pipeline_id,
                initial_payload=agent_output
            )
            if isinstance(envelope_result, Failure):
                return envelope_result

            new_envelope = envelope_result.value
            object.__setattr__(self, '_current_envelope', new_envelope)
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
            return self._rollback_sync()

        snapshot_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(snapshot_result, Failure):
            return snapshot_result

        object.__setattr__(self, '_current_envelope', new_envelope)
        return Success(new_envelope)

    def _rollback_sync(self) -> Result[ContextEnvelope]:
        """Synchronous implementation of rollback."""
        if not self._previous_envelopes:
            return Failure(reason="No previous envelope to rollback to", code="NO_ROLLBACK_AVAILABLE")

        previous_envelope = self._previous_envelopes[-1]
        restore_result = self._snapshot_store.load_snapshot(
            f"{previous_envelope.step}_{previous_envelope.timestamp.strftime('%Y%m%dT%H%M%S%f')}"
        )
        if isinstance(restore_result, Failure):
            return restore_result

        restored_envelope = restore_result.value
        object.__setattr__(self, '_current_envelope', restored_envelope)
        return Success(restored_envelope)

    async def execute_with_timeout(
        self,
        agent_output: dict[str, Any],
        timeout_seconds: float
    ) -> Result[ContextEnvelope]:
        """Execute a pipeline step with timeout."""
        try:
            return await asyncio.wait_for(
                self.execute_step_async(agent_output),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            return Failure(
                reason=f"Execution timed out after {timeout_seconds} seconds",
                code="EXECUTION_TIMEOUT"
            )

    async def get_current_envelope_async(self) -> ContextEnvelope | None:
        """Get the current envelope asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._get_current_envelope_sync
        )

    def _get_current_envelope_sync(self) -> ContextEnvelope | None:
        """Synchronous implementation of get_current_envelope."""
        return self._current_envelope