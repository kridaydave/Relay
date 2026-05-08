"""Context envelope data model for Relay.

Owns: ContextEnvelope data model only.
Does NOT: create envelopes, sign envelopes, persist data, or manage pipeline state.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _validate_pipeline_id(pipeline_id: str) -> Result[str]:
    """Validate pipeline_id format."""
    if not pipeline_id:
        return Failure(reason="pipeline_id cannot be empty", code="INVALID_PIPELINE_ID")
    if not PIPELINE_ID_PATTERN.match(pipeline_id):
        return Failure(
            reason="Invalid pipeline_id: must match pattern ^[a-zA-Z0-9_-]{1,128}$",
            code="INVALID_PIPELINE_ID",
        )
    return Success(pipeline_id)

from relay.types import Failure, Result, Success

RELAY_VERSION = "0.2.0"


@dataclass(frozen=True)
class ContextEnvelope:
    """Immutable context envelope passed between agents.

    Attributes:
        relay_version: Version of Relay that created this envelope.
        pipeline_id: Unique identifier for this pipeline run.
        step: Current step number in the pipeline.
        timestamp: UTC timestamp when envelope was created.
        token_budget_used: Tokens consumed so far.
        token_budget_total: Maximum token budget allowed.
        payload: The actual data being passed (agent output).
        manifest_hash: Hash of the agent manifest.
        signature: HMAC-SHA256 signature of the envelope.
    """

    relay_version: str
    pipeline_id: str
    step: int
    timestamp: datetime
    token_budget_used: int
    token_budget_total: int
    payload: dict[str, Any]
    manifest_hash: str
    signature: str

    def with_manifest_hash(self, manifest_hash: str) -> "ContextEnvelope":
        """Return a copy of this envelope with a different manifest hash."""
        return ContextEnvelope(
            relay_version=self.relay_version,
            pipeline_id=self.pipeline_id,
            step=self.step,
            timestamp=self.timestamp,
            token_budget_used=self.token_budget_used,
            token_budget_total=self.token_budget_total,
            payload=self.payload,
            manifest_hash=manifest_hash,
            signature=self.signature,
        )

    def with_signature(self, signature: str) -> "ContextEnvelope":
        """Return a copy of this envelope with a different signature."""
        return ContextEnvelope(
            relay_version=self.relay_version,
            pipeline_id=self.pipeline_id,
            step=self.step,
            timestamp=self.timestamp,
            token_budget_used=self.token_budget_used,
            token_budget_total=self.token_budget_total,
            payload=self.payload,
            manifest_hash=self.manifest_hash,
            signature=signature,
        )


def _compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature for an envelope.

    Canonical signature format (field order is load-bearing):
    {relay_version}|{pipeline_id}|{step}|{timestamp.isoformat()}|{token_budget_used}|{token_budget_total}|{manifest_hash}|{json.dumps(payload, sort_keys=True)}
    """
    payload = json.dumps(envelope.payload, sort_keys=True, separators=(",", ":"))
    message = f"{envelope.relay_version}|{envelope.pipeline_id}|{envelope.step}|{envelope.timestamp.isoformat()}|{envelope.token_budget_used}|{envelope.token_budget_total}|{envelope.manifest_hash}|{payload}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(envelope: ContextEnvelope, secret: str) -> bool:
    """Verify the signature of an envelope."""
    expected_sig = _compute_signature(envelope, secret)
    return hmac.compare_digest(envelope.signature, expected_sig)


def _sign_envelope(envelope: ContextEnvelope, secret: str) -> ContextEnvelope:
    """Create a signed copy of the envelope."""
    signature = _compute_signature(envelope, secret)
    return envelope.with_signature(signature)


def create_initial_envelope(
    pipeline_id: str,
    initial_payload: dict[str, Any],
    secret: str,
    manifest_hash: str,
    token_budget_total: int = 8000,
) -> Result[ContextEnvelope]:
    """Create the first envelope for a pipeline.

    Args:
        secret: HMAC signing secret. REQUIRED - must be provided by caller.
            Do NOT use default or placeholder values in production.
        manifest_hash: Optional hash of the agent manifest. Pass "" if not using manifests.
    """
    validation_result = _validate_pipeline_id(pipeline_id)
    if isinstance(validation_result, Failure):
        return validation_result
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

    signed = _sign_envelope(envelope, secret)
    return Success(signed)


def create_next_envelope(
    previous_envelope: ContextEnvelope,
    secret: str,
    agent_output: dict[str, Any],
    manifest_hash: str,
) -> Result[ContextEnvelope]:
    """Create a subsequent envelope for the next step.

    Args:
        secret: HMAC signing secret. REQUIRED - must be provided by caller.
            Do NOT use default or placeholder values in production.
        manifest_hash: Optional hash of the agent manifest. Pass "" if not using manifests.
    """
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

    signed = _sign_envelope(envelope, secret)
    return Success(signed)


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Approximates token count from payload JSON string length.

    This is a heuristic that estimates BPE tokens by dividing character count by 3.
    Note: This is NOT precise - actual token counts vary based on:
    - Specific vocabulary/merge table of the tokenizer
    - Content type (code vs natural language)
    - Repetitive vs diverse content

    This achieves ~50% accuracy in typical cases and is suitable for budget
    estimation but NOT for precise token counting. Do not rely on this
    for exact limits.

    See test_envelope.py::TestTokenEstimation::test_token_estimate_within_realistic_tolerance
    for the benchmark test.
    """
    json_str = json.dumps(payload, sort_keys=True)
    return max(1, len(json_str) // 3)
