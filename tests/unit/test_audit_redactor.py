"""Unit tests for relay.audit.redactor — PayloadRedactor default-deny redaction."""

import pytest

from relay.audit.redactor import PayloadRedactor
from relay.types import JSONDict


class TestPayloadRedactor:
    """Verify PayloadRedactor strips non-allowlisted fields."""

    def test_redactor_strips_non_allowlisted_fields_when_redacting(self) -> None:
        """Fields not in ALLOWED_FIELDS must be removed."""
        redactor = PayloadRedactor()
        payload: JSONDict = {
            "adapter_name": "test-adapter",
            "agent_name": "test-agent",
            "secret_key": "should-not-appear",
            "user_data": {"ssn": "123-45-6789"},
        }
        result = redactor.redact_payload(payload)
        assert "adapter_name" in result
        assert "agent_name" in result
        assert "secret_key" not in result
        assert "user_data" not in result

    def test_redactor_passes_allowlisted_fields_through_when_present(self) -> None:
        """All allowlisted fields must pass through unchanged."""
        redactor = PayloadRedactor()
        payload: JSONDict = {"adapter_name": "test", "pipeline_id": "abc"}
        result = redactor.redact_payload(payload)
        assert result == {"adapter_name": "test", "pipeline_id": "abc"}

    def test_redactor_returns_empty_dict_when_no_allowlisted_fields(self) -> None:
        """When no allowlisted fields present, must return an empty dict."""
        redactor = PayloadRedactor()
        payload: JSONDict = {"sensitive": "data", "secret": "value"}
        result = redactor.redact_payload(payload)
        assert result == {}

    def test_redactor_constructor_accepts_no_arguments_when_called(self) -> None:
        """PayloadRedactor must be constructable with no arguments."""
        redactor = PayloadRedactor()
        assert isinstance(redactor, PayloadRedactor)

    def test_redact_envelope_returns_only_metadata_fields(self) -> None:
        """redact_envelope must return metadata-only dict from envelope."""
        redactor = PayloadRedactor()
        # We test with a minimal envelope constructed inline
        from relay.envelope import ContextEnvelope
        from relay.types import JSONDict

        from datetime import datetime, timezone

        envelope = ContextEnvelope(
            relay_version="1.0",
            pipeline_id="test-pipeline",
            step=3,
            timestamp=datetime.now(timezone.utc),
            token_budget_used=500,
            token_budget_total=8000,
            payload={"agent_output": "sensitive content"},
            manifest_hash="abc123",
            signature="signed",
        )
        result = redactor.redact_envelope(envelope)
        assert result["pipeline_id"] == "test-pipeline"
        assert result["step"] == 3
        assert result["token_budget_used"] == 500
        assert result["token_budget_total"] == 8000
        # Payload fields must not be present
        assert "agent_output" not in result
        assert "payload" not in result

    def test_redact_envelope_strips_manifest_hash_and_signature_when_redacting(self) -> None:
        """Envelope fields like manifest_hash and signature must be stripped."""
        redactor = PayloadRedactor()
        from relay.envelope import ContextEnvelope

        from datetime import datetime, timezone

        envelope = ContextEnvelope(
            relay_version="1.0",
            pipeline_id="p",
            step=1,
            timestamp=datetime.now(timezone.utc),
            token_budget_used=0,
            token_budget_total=8000,
            payload={},
            manifest_hash="secret-hash",
            signature="secret-sig",
        )
        result = redactor.redact_envelope(envelope)
        assert "manifest_hash" not in result
        assert "signature" not in result
