"""Context envelope data model for Relay.

Owns: ContextEnvelope data model only.
Does NOT: create envelopes, sign envelopes, persist data, or manage pipeline state.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

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


def verify_signature(envelope: ContextEnvelope, secret: str) -> bool:
    """Verify the signature of an envelope."""
    expected_sig = _compute_signature(envelope, secret)
    return hmac.compare_digest(envelope.signature, expected_sig)


def _sign_envelope(envelope: ContextEnvelope, secret: str) -> ContextEnvelope:
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
    return len(json_str) // 3
