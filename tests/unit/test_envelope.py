"""Unit tests for relay.envelope."""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.envelope import (
    RELAY_VERSION,
    ContextEnvelope,
    create_initial_envelope,
    create_next_envelope,
    verify_signature,
)


@dataclass(frozen=True)
class EnvelopeFixture:
    relay_version: str
    pipeline_id: str
    step: int
    timestamp: datetime
    token_budget_used: int
    token_budget_total: int
    payload: dict
    signature: str


class TestCreateInitialEnvelope:
    @patch("relay.envelope.datetime")
    def test_create_initial_envelope_with_valid_inputs(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            secret="test-secret",
        )

        assert result.value.relay_version == RELAY_VERSION
        assert result.value.pipeline_id == "pipeline-123"
        assert result.value.step == 1
        assert result.value.token_budget_total == 8000
        assert result.value.payload == {"data": "test"}
        assert result.value.signature != ""

    def test_create_initial_envelope_fails_on_empty_pipeline_id(self):
        result = create_initial_envelope(
            pipeline_id="", initial_payload={"data": "test"}
        )

        assert result.reason == "pipeline_id cannot be empty"
        assert result.code == "INVALID_PIPELINE_ID"

    def test_create_initial_envelope_fails_on_empty_payload(self):
        result = create_initial_envelope(pipeline_id="pipeline-123", initial_payload={})

        assert result.reason == "initial_payload cannot be empty"
        assert result.code == "INVALID_PAYLOAD"


class TestCreateNextEnvelope:
    @patch("relay.envelope.datetime")
    def test_create_next_envelope_increments_step(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        initial_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            signature="sig1",
        )

        result = create_next_envelope(
            previous_envelope=initial_envelope,
            agent_output={"result": "output"},
            secret="test-secret",
        )

        assert result.value.step == 2

    @patch("relay.envelope.datetime")
    def test_create_next_envelope_updates_token_budget(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        initial_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            signature="sig1",
        )

        result = create_next_envelope(
            previous_envelope=initial_envelope,
            agent_output={"result": "output"},
            secret="test-secret",
        )

        assert result.value.token_budget_used > 100

    @patch("relay.envelope.datetime")
    def test_create_next_envelope_fails_on_token_budget_exceeded(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        initial_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=7500,
            token_budget_total=8000,
            payload={"data": "initial"},
            signature="sig1",
        )

        result = create_next_envelope(
            previous_envelope=initial_envelope,
            agent_output={"huge": "payload" * 1000},
            secret="test-secret",
        )

        assert result.code == "TOKEN_BUDGET_EXCEEDED"
        assert "Token budget exceeded" in result.reason

    def test_create_next_envelope_fails_on_empty_agent_output(self):
        initial_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            signature="sig1",
        )

        result = create_next_envelope(
            previous_envelope=initial_envelope, agent_output={}, secret="test-secret"
        )

        assert result.reason == "agent_output cannot be empty"
        assert result.code == "INVALID_PAYLOAD"


class TestVerifySignature:
    @patch("relay.envelope.datetime")
    def test_verify_signature_returns_true_for_valid_signature(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        envelope = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            secret="test-secret",
        ).value

        assert verify_signature(envelope, "test-secret") is True

    def test_verify_signature_returns_false_for_invalid_signature(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "test"},
            signature="invalid-signature",
        )

        assert verify_signature(envelope, "test-secret") is False

    def test_verify_signature_fails_on_tampered_budget(self):
        original = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            secret="test-secret",
        ).value

        tampered = ContextEnvelope(
            relay_version=original.relay_version,
            pipeline_id=original.pipeline_id,
            step=original.step,
            timestamp=original.timestamp,
            token_budget_used=original.token_budget_used,
            token_budget_total=999999,  # tampered
            payload=original.payload,
            signature=original.signature,
        )
        assert verify_signature(tampered, "test-secret") is False


class TestTokenEstimation:
    def test_token_estimate_accuracy(self):
        from relay.envelope import _estimate_tokens

        # Ground truth: '{"data": "test"}' is about 6 tokens in GPT-4.
        payload = {"data": "test"}
        estimate = _estimate_tokens(payload)
        ground_truth = 6
        tolerance = 0.30
        assert (
            (1 - tolerance) * ground_truth <= estimate <= (1 + tolerance) * ground_truth
        )
