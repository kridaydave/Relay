"""Context envelope creation, signing, and lifecycle management for Relay.

Owns: envelope lifecycle, cryptographic signing.
Does NOT: validate agent output, persist snapshots, execute agents.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope, create_initial_envelope, create_next_envelope
from relay.types import Result


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
        return create_initial_envelope(
            pipeline_id=pipeline_id,
            initial_payload=initial_payload,
            secret=self.signing_secret,
            token_budget_total=self.token_budget_total,
        )

    def create_next_envelope(
        self,
        previous_envelope: ContextEnvelope,
        agent_output: dict[str, Any]
    ) -> Result[ContextEnvelope]:
        """Create a subsequent envelope for the next step."""
        return create_next_envelope(
            previous_envelope=previous_envelope,
            secret=self.signing_secret,
            agent_output=agent_output,
        )