"""Context envelope lifecycle management for Relay.

Owns: deciding when to create envelopes, enforcing secret strength,
      coordinating construction via relay.envelope.
Does NOT: implement signing (owned by relay.envelope), persist envelopes,
          validate agent output, or manage pipeline state.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope, create_initial_envelope, create_next_envelope
from relay.types import ErrorCode, Failure, Result, Success

__all__ = ["ContextBroker", "create_context_broker"]


_MIN_SECRET_LENGTH = 32


def create_context_broker(
    signing_secret: str,
    token_budget_total: int = 8000,
) -> Result[ContextBroker]:
    """Factory function to create a ContextBroker with validation.

    Validates signing_secret strength at boundary entry per R16.

    Args:
        signing_secret: HMAC signing secret. Must be at least 32 characters.
        token_budget_total: Maximum token budget for envelopes.

    Returns:
        Success with ContextBroker, or Failure if validation fails.
    """
    if len(signing_secret) < _MIN_SECRET_LENGTH:
        return Failure(
            reason=(
                f"signing_secret must be at least {_MIN_SECRET_LENGTH} characters, "
                f"got {len(signing_secret)}. Weak secrets compromise envelope integrity."
            ),
            code=ErrorCode.INVALID_SECRET,
        )
    return Success(ContextBroker(signing_secret=signing_secret, token_budget_total=token_budget_total))


@dataclass(frozen=True)
class ContextBroker:
    """Manages context envelope creation and signing.

    Owns: envelope lifecycle, cryptographic signing, and verification.
    Does NOT: persist snapshots, validate content, or manage pipeline state.

    Note: Use create_context_broker() factory function to construct instances.
    Direct construction bypasses validation - use the factory for boundary entry.
    """
    signing_secret: str
    token_budget_total: int

    def __post_init__(self) -> None:
        if len(self.signing_secret) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"signing_secret must be at least {_MIN_SECRET_LENGTH} characters, "
                f"got {len(self.signing_secret)}. Weak secrets compromise envelope integrity."
            )

    def create_initial_envelope(
        self,
        pipeline_id: str,
        initial_payload: dict[str, Any],
        manifest_hash: str = "",
    ) -> Result[ContextEnvelope]:
        """Create the first envelope for a pipeline."""
        return create_initial_envelope(
            pipeline_id=pipeline_id,
            initial_payload=initial_payload,
            secret=self.signing_secret,
            token_budget_total=self.token_budget_total,
            manifest_hash=manifest_hash,
        )

    def create_next_envelope(
        self,
        previous_envelope: ContextEnvelope,
        agent_output: dict[str, Any],
        manifest_hash: str = "",
    ) -> Result[ContextEnvelope]:
        """Create a subsequent envelope for the next step."""
        return create_next_envelope(
            previous_envelope=previous_envelope,
            secret=self.signing_secret,
            agent_output=agent_output,
            manifest_hash=manifest_hash,
        )