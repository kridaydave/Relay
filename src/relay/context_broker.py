"""Context envelope creation, signing, and lifecycle management for Relay.

Owns: envelope lifecycle, cryptographic signing.
Does NOT: validate agent output, persist snapshots, execute agents.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope, create_initial_envelope, create_next_envelope
from relay.types import Result, Success, Failure


@dataclass(frozen=True)
class ContextBroker:
    """Manages context envelope creation and signing.

    Owns: envelope lifecycle, cryptographic signing.
    Does NOT: validate agent output, persist snapshots, execute agents.
    """
    signing_secret: str
    token_budget_total: int

    def create_initial_envelope(
        self,
        pipeline_id: str,
        initial_payload: dict[str, Any]
    ) -> Result[ContextEnvelope]:
        """Create the first envelope for a pipeline."""
        if not pipeline_id:
            return Failure(reason="pipeline_id cannot be empty", code="INVALID_PIPELINE_ID")
        if not initial_payload:
            return Failure(reason="initial_payload cannot be empty", code="INVALID_PAYLOAD")

        return create_initial_envelope(
            pipeline_id=pipeline_id,
            initial_payload=initial_payload,
            token_budget_total=self.token_budget_total,
            secret=self.signing_secret
        )

    def create_next_envelope(
        self,
        previous_envelope: ContextEnvelope,
        agent_output: dict[str, Any]
    ) -> Result[ContextEnvelope]:
        """Create a subsequent envelope for the next step."""
        if not agent_output:
            return Failure(reason="agent_output cannot be empty", code="INVALID_PAYLOAD")

        return create_next_envelope(
            previous_envelope=previous_envelope,
            agent_output=agent_output,
            secret=self.signing_secret
        )