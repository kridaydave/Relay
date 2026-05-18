"""Default-deny payload redactor for audit event construction.

Owns: PayloadRedactor with default-deny allowlist for safe audit fields.
Does NOT: perform pipeline logic, define event types, or handle sink operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from relay.types import JSONDict

if TYPE_CHECKING:
    from relay.envelope import ContextEnvelope


class PayloadRedactor:
    """Default-deny allowlist-based payload redactor.

    Only fields present in ALLOWED_FIELDS are passed through.
    All other fields are stripped. Applied at event construction time.
    """

    ALLOWED_FIELDS: frozenset[str] = frozenset({
        "adapter_name",
        "agent_name",
        "step",
        "pipeline_id",
        "token_count",
        "budget_used",
        "budget_limit",
    })

    def redact_payload(self, payload: JSONDict) -> JSONDict:
        """Return only allowlisted fields from payload.

        Args:
            payload: Raw payload dict potentially containing sensitive data.

        Returns:
            Dict containing only fields present in ALLOWED_FIELDS.
        """
        return {k: v for k, v in payload.items() if k in self.ALLOWED_FIELDS}

    def redact_envelope(self, envelope: ContextEnvelope) -> JSONDict:
        """Return redacted envelope data: only metadata, no payload content.

        Args:
            envelope: The context envelope to extract metadata from.

        Returns:
            Dict with allowlisted envelope metadata fields.
        """
        return {
            "pipeline_id": envelope.pipeline_id,
            "step": envelope.step,
            "token_budget_used": envelope.token_budget_used,
            "token_budget_total": envelope.token_budget_total,
        }


__all__ = [
    "PayloadRedactor",
]
