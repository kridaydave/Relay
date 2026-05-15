"""Context envelope data model and factory functions for Relay.

Owns: ContextEnvelope data model, envelope construction, HMAC signing.
Does NOT: persist envelopes, manage pipeline state, or validate agent output.

Note: signing lives here rather than in context_broker because the signature
covers fields that only envelope.py knows how to serialise canonically.
context_broker.py decides *when* to create envelopes; envelope.py owns *how*.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from relay.types import ErrorCode, Failure, Result, Success

RELAY_VERSION = "0.4.0"

__all__ = [
    "RELAY_VERSION",
    "ContextEnvelope",
    "create_initial_envelope",
    "create_next_envelope",
    "verify_signature",
    "estimate_tokens",
    "serialize_slice",
    "compute_signature",
]
PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _validate_pipeline_id(pipeline_id: str) -> Result[str]:
    """Validate pipeline_id format."""
    if not pipeline_id:
        return Failure(reason="pipeline_id cannot be empty", code=ErrorCode.INVALID_PIPELINE_ID)
    if not PIPELINE_ID_PATTERN.match(pipeline_id):
        return Failure(
            reason="Invalid pipeline_id: must match pattern ^[a-zA-Z0-9_-]{1,128}$",
            code=ErrorCode.INVALID_PIPELINE_ID,
        )
    return Success(pipeline_id)


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

    fork_id: str | None = None
    join_strategy: str | None = None
    fork_count: int | None = None
    forks_succeeded: int | None = None

    def with_manifest_hash(self, manifest_hash: str) -> "ContextEnvelope":
        """Return a copy of this envelope with a different manifest hash."""
        return replace(self, manifest_hash=manifest_hash)

    def with_signature(self, signature: str) -> "ContextEnvelope":
        """Return a copy of this envelope with a different signature."""
        return replace(self, signature=signature)

    def with_fork_metadata(
        self,
        fork_id: str,
        join_strategy: str,
        fork_count: int,
        forks_succeeded: int,
    ) -> "ContextEnvelope":
        """Return a copy of this envelope with parallel step metadata applied.

        WARNING: The returned copy is UNSIGNED and has an invalid signature field.
        The caller MUST re-sign the envelope (e.g., via execute_step_with_manifest)
        before persisting or transmitting.
        """
        return replace(
            self,
            fork_id=fork_id,
            join_strategy=join_strategy,
            fork_count=fork_count,
            forks_succeeded=forks_succeeded,
            signature="",
        )


def _canonical_timestamp(dt: datetime) -> str:
    """Return ISO-8601 timestamp with seconds precision, always with UTC offset +00:00.

    Uses timespec='seconds' so Python 3.11 (which may emit Z) and 3.12 (which may
    emit +00:00) produce identical output. Both normalise to +00:00 with this spec.
    """
    return dt.isoformat(timespec="seconds")


def _sign_envelope(envelope: ContextEnvelope, secret: str) -> ContextEnvelope:
    """Create a signed copy of the envelope."""
    signature = compute_signature(envelope, secret)
    return envelope.with_signature(signature)


def compute_signature(envelope: ContextEnvelope, secret: str) -> str:
    """Compute HMAC-SHA256 signature for an envelope.

    Canonical signature format (field order is load-bearing):
    {relay_version}|{pipeline_id}|{step}|{timestamp.isoformat()}|{token_budget_used}|{token_budget_total}|{manifest_hash}|{json.dumps(payload, sort_keys=True)}

    When fork_id is not None, fork metadata is appended for parallel steps:
    ...|{fork_id}|{join_strategy}|{fork_count}|{forks_succeeded}
    """
    payload_json = json.dumps(envelope.payload, sort_keys=True, separators=(",", ":"))
    base = (
        f"{envelope.relay_version}|{envelope.pipeline_id}|{envelope.step}|"
        f"{_canonical_timestamp(envelope.timestamp)}|{envelope.token_budget_used}|"
        f"{envelope.token_budget_total}|{envelope.manifest_hash}|{payload_json}"
    )
    if envelope.fork_id is not None:
        base += (
            f"|{envelope.fork_id}|{envelope.join_strategy}|"
            f"{envelope.fork_count}|{envelope.forks_succeeded}"
        )
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def verify_signature(envelope: ContextEnvelope, secret: str) -> bool:
    """Verify the signature of an envelope."""
    expected_sig = compute_signature(envelope, secret)
    return hmac.compare_digest(envelope.signature, expected_sig)


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
        return Failure(reason="initial_payload cannot be empty", code=ErrorCode.INVALID_PAYLOAD)

    token_used = estimate_tokens(initial_payload)
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

    Budget validation is performed by HardCapEnforcer before envelope creation.
    This function trusts that the budget check has already been done.

    Args:
        secret: HMAC signing secret. REQUIRED - must be provided by caller.
            Do NOT use default or placeholder values in production.
        manifest_hash: Optional hash of the agent manifest. Pass "" if not using manifests.
    """
    if not agent_output:
        return Failure(reason="agent_output cannot be empty", code=ErrorCode.INVALID_PAYLOAD)

    token_used = previous_envelope.token_budget_used + estimate_tokens(agent_output)

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


def serialize_slice(data: dict[str, Any]) -> str:
    """Serialize a payload dict to JSON for budget projection or slice passing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def estimate_tokens(payload: dict[str, Any]) -> int:
    """Approximates token count from payload JSON string length.

    This heuristic estimates BPE tokens by dividing character count by 3.
    This is approximately 0.33 tokens/char, which is within the 0.25-0.40
    range of real BPE tokenizers (GPT-4 family, cl100k_base).

    This is a coarse approximation suitable for budget estimation but NOT
    for precise token counting. The 3x tolerance is intentionally wide.

    Uses separators=(",", ":") to match the canonical serialization used
    for signature computation, ensuring token estimate matches actual wire size.

    See test_envelope.py::TestTokenEstimation for the ground-truth benchmark.
    """
    json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return max(1, len(json_str) // 3)
