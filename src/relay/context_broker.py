"""Context envelope creation, signing, and lifecycle management for Relay.

Owns: envelope lifecycle, cryptographic signing, and verification.
Does NOT: persist snapshots, validate content, or manage pipeline state.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import Failure, Result, Success


def _create_signed_envelope(
    envelope: ContextEnvelope,
    secret: str,
) -> ContextEnvelope:
    """Create a signed copy of the envelope."""
    signature = _compute_signature(envelope, secret)
    return envelope.with_signature(signature)


def _compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature for an envelope.

    Canonical signature format (field order is load-bearing):
    {relay_version}|{pipeline_id}|{step}|{timestamp.isoformat()}|{token_budget_used}|{token_budget_total}|{manifest_hash}|{json.dumps(payload, sort_keys=True)}
    """
    payload = json.dumps(envelope.payload, sort_keys=True)
    message = f"{envelope.relay_version}|{envelope.pipeline_id}|{envelope.step}|{envelope.timestamp.isoformat()}|{envelope.token_budget_used}|{envelope.token_budget_total}|{envelope.manifest_hash}|{payload}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _verify_signature(envelope: ContextEnvelope, secret: str) -> bool:
    """Verify the signature of an envelope."""
    expected_sig = _compute_signature(envelope, secret)
    return hmac.compare_digest(envelope.signature, expected_sig)


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Approximates token count from payload JSON string length.

    Divides character count by 3 to approximate BPE tokenization.
    """
    json_str = json.dumps(payload, sort_keys=True)
    return len(json_str) // 3


def _create_initial_envelope(
    pipeline_id: str,
    initial_payload: dict[str, Any],
    secret: str,
    token_budget_total: int = 8000,
    manifest_hash: str = "",
) -> Result[ContextEnvelope]:
    """Create the first envelope for a pipeline."""
    if not pipeline_id:
        return Failure(reason="pipeline_id cannot be empty", code="INVALID_PIPELINE_ID")
    if not initial_payload:
        return Failure(reason="initial_payload cannot be empty", code="INVALID_PAYLOAD")

    token_used = _estimate_tokens(initial_payload)
    envelope = ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=1,
        timestamp=datetime.now(timezone.utc),
        token_budget_used=token_used,
        token_budget_total=token_budget_total,
        payload=initial_payload,
        manifest_hash=manifest_hash,
        signature="",
    )

    signed = _create_signed_envelope(envelope, secret)
    return Success(signed)


def _create_next_envelope(
    previous_envelope: ContextEnvelope,
    secret: str,
    agent_output: dict[str, Any],
    manifest_hash: str = "",
) -> Result[ContextEnvelope]:
    """Create a subsequent envelope for the next step."""
    if not agent_output:
        return Failure(reason="agent_output cannot be empty", code="INVALID_PAYLOAD")

    token_used = previous_envelope.token_budget_used + _estimate_tokens(agent_output)
    if token_used > previous_envelope.token_budget_total:
        return Failure(
            reason=f"Token budget exceeded: {token_used} > {previous_envelope.token_budget_total}",
            code="TOKEN_BUDGET_EXCEEDED",
        )

    envelope = ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=previous_envelope.pipeline_id,
        step=previous_envelope.step + 1,
        timestamp=datetime.now(timezone.utc),
        token_budget_used=token_used,
        token_budget_total=previous_envelope.token_budget_total,
        payload=agent_output,
        manifest_hash=manifest_hash,
        signature="",
    )

    signed = _create_signed_envelope(envelope, secret)
    return Success(signed)


@dataclass(frozen=True)
class ContextBroker:
    """Manages context envelope creation and signing.

    Owns: envelope lifecycle, cryptographic signing, and verification.
    Does NOT: persist snapshots, validate content, or manage pipeline state.
    """
    signing_secret: str
    token_budget_total: int

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