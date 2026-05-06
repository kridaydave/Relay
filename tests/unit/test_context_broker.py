"""Unit tests for relay.context_broker."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import Failure, Success


class TestCreateInitialEnvelope:
    @patch("relay.context_broker.create_initial_envelope")
    def test_broker_creates_initial_envelope_with_valid_inputs(self, mock_create):
        mock_create.return_value = Success(
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="pipeline-123",
                step=1,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=100,
                token_budget_total=8000,
                payload={"data": "test"},
                manifest_hash="",
                signature="test-signature"
            )
        )

        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        result = broker.create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"}
        )

        assert isinstance(result, Success)
        assert result.value.pipeline_id == "pipeline-123"
        assert result.value.step == 1
        mock_create.assert_called_once()

    def test_broker_fails_on_empty_pipeline_id(self):
        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        result = broker.create_initial_envelope(
            pipeline_id="",
            initial_payload={"data": "test"}
        )

        assert isinstance(result, Failure)
        assert result.reason == "pipeline_id cannot be empty"
        assert result.code == "INVALID_PIPELINE_ID"

    def test_broker_fails_on_empty_payload(self):
        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        result = broker.create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={}
        )

        assert isinstance(result, Failure)
        assert result.reason == "initial_payload cannot be empty"
        assert result.code == "INVALID_PAYLOAD"


class TestCreateNextEnvelope:
    @patch("relay.context_broker.create_next_envelope")
    def test_broker_creates_next_envelope_with_valid_inputs(self, mock_create):
        mock_create.return_value = Success(
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="pipeline-123",
                step=2,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=200,
                token_budget_total=8000,
                payload={"result": "output"},
                manifest_hash="",
                signature="test-signature"
            )
        )

        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        previous_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            manifest_hash="",
            signature="sig1"
        )

        result = broker.create_next_envelope(
            previous_envelope=previous_envelope,
            agent_output={"result": "output"}
        )

        assert isinstance(result, Success)
        assert result.value.step == 2
        mock_create.assert_called_once()

    @patch("relay.context_broker.create_next_envelope")
    def test_broker_next_envelope_increments_step(self, mock_create):
        mock_create.return_value = Success(
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="pipeline-123",
                step=2,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=200,
                token_budget_total=8000,
                payload={"result": "output"},
                manifest_hash="",
                signature="test-signature"
            )
        )

        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        previous_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            manifest_hash="",
            signature="sig1"
        )

        result = broker.create_next_envelope(
            previous_envelope=previous_envelope,
            agent_output={"result": "output"}
        )

        assert result.value.step == 2

    @patch("relay.context_broker.create_next_envelope")
    def test_broker_next_envelope_updates_token_budget(self, mock_create):
        mock_create.return_value = Success(
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="pipeline-123",
                step=2,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=250,
                token_budget_total=8000,
                payload={"result": "output"},
                manifest_hash="",
                signature="test-signature"
            )
        )

        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        previous_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "initial"},
            manifest_hash="",
            signature="sig1"
        )

        result = broker.create_next_envelope(
            previous_envelope=previous_envelope,
            agent_output={"result": "output"}
        )

        assert result.value.token_budget_used > 100

    @patch("relay.context_broker.create_next_envelope")
    def test_broker_next_envelope_fails_on_token_budget_exceeded(self, mock_create):
        mock_create.return_value = Failure(
            reason="Token budget exceeded: 9000 > 8000",
            code="TOKEN_BUDGET_EXCEEDED"
        )

        broker = ContextBroker(signing_secret="secret", token_budget_total=8000)
        previous_envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=7500,
            token_budget_total=8000,
            payload={"data": "initial"},
            manifest_hash="",
            signature="sig1"
        )

        result = broker.create_next_envelope(
            previous_envelope=previous_envelope,
            agent_output={"huge": "payload" * 1000}
        )

        assert isinstance(result, Failure)
        assert result.code == "TOKEN_BUDGET_EXCEEDED"
        assert "Token budget exceeded" in result.reason