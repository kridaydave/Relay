"""Context envelope creation, signing, and lifecycle management for Relay.

Owns: envelope lifecycle, cryptographic signing, and verification.
Does NOT: persist snapshots, validate content, or manage pipeline state.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope, create_initial_envelope, create_next_envelope
from relay.types import Result




def _create_signed_envelope(
    envelope: ContextEnvelope,
    secret: str,
) -> ContextEnvelope:
    """Create a signed copy of the envelope."""
    from relay.envelope import _sign_envelope
    return _sign_envelope(envelope, secret)


def _compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature for an envelope."""
    from relay.envelope import _compute_signature
    return _compute_signature(envelope, secret)


def _verify_signature(envelope: ContextEnvelope, secret: str) -> bool:
    """Verify the signature of an envelope."""
    from relay.envelope import verify_signature
    return verify_signature(envelope, secret)


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Approximates token count from payload JSON string length.

    Divides character count by 3 to approximate BPE tokenization.

    See test_envelope.py::TestTokenEstimation::test_token_estimate_within_realistic_tolerance
    for the benchmark test.
    """
    from relay.envelope import _estimate_tokens as estimate
    return estimate(payload)


def _create_initial_envelope(
    pipeline_id: str,
    initial_payload: dict[str, Any],
    secret: str,
    token_budget_total: int = 8000,
    manifest_hash: str = "",
) -> Result[ContextEnvelope]:
    """Create the first envelope for a pipeline."""
    return create_initial_envelope(
        pipeline_id=pipeline_id,
        initial_payload=initial_payload,
        secret=secret,
        token_budget_total=token_budget_total,
        manifest_hash=manifest_hash,
    )


def _create_next_envelope(
    previous_envelope: ContextEnvelope,
    secret: str,
    agent_output: dict[str, Any],
    manifest_hash: str = "",
) -> Result[ContextEnvelope]:
    """Create a subsequent envelope for the next step."""
    return create_next_envelope(
        previous_envelope=previous_envelope,
        secret=secret,
        agent_output=agent_output,
        manifest_hash=manifest_hash,
    )


@dataclass(frozen=True)
class ContextBroker:
    """Manages context envelope creation and signing.

    Owns: envelope lifecycle, cryptographic signing, and verification.
    Does NOT: persist snapshots, validate content, or manage pipeline state.
    """
    signing_secret: str
    token_budget_total: int

    def __post_init__(self) -> None:
        """Validate the signing secret at boundary entry per R16."""
        if len(self.signing_secret) < 32:
            raise ValueError(
                f"signing_secret must be at least 32 characters, got {len(self.signing_secret)}. "
                "Weak secrets compromise envelope integrity."
            )

    def create_initial_envelope(
        self,
        pipeline_id: str,
        initial_payload: dict[str, Any]
    ) -> Result[ContextEnvelope]:
        """Create the first envelope for a pipeline."""
        return _create_initial_envelope(
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
        return _create_next_envelope(
            previous_envelope=previous_envelope,
            secret=self.signing_secret,
            agent_output=agent_output,
        )