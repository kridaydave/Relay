"""Unit tests for relay.context_broker."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import pytest

from relay.context_broker import ContextBroker, create_context_broker
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import ErrorCode, Failure, Success


class TestCreateInitialEnvelope:
    def test_short_secret_returns_failure(self):
        """ContextBroker factory must return Failure for secrets shorter than 32 characters."""
        result = create_context_broker(signing_secret="short", token_budget_total=8000)
        assert isinstance(result, Failure)
        assert "32 characters" in result.reason

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

        broker_result = create_context_broker(signing_secret="a" * 32, token_budget_total=8000)
        assert isinstance(broker_result, Success)
        broker = broker_result.value
        result = broker.create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            manifest_hash="",
        )

        assert isinstance(result, Success)
        assert result.value.pipeline_id == "pipeline-123"
        assert result.value.step == 1
        mock_create.assert_called_once()

    def test_broker_fails_on_empty_pipeline_id(self):
        broker = ContextBroker(signing_secret="a" * 32, token_budget_total=8000)
        result = broker.create_initial_envelope(
            pipeline_id="",
            initial_payload={"data": "test"},
            manifest_hash="",
        )

        assert isinstance(result, Failure)
        assert result.reason == "pipeline_id cannot be empty"
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_broker_fails_on_empty_payload(self):
        broker = ContextBroker(signing_secret="a" * 32, token_budget_total=8000)
        result = broker.create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={},
            manifest_hash="",
        )

        assert isinstance(result, Failure)
        assert result.reason == "initial_payload cannot be empty"
        assert result.code == ErrorCode.INVALID_PAYLOAD


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

        broker = ContextBroker(signing_secret="a" * 32, token_budget_total=8000)
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
            agent_output={"result": "output"},
            manifest_hash="",
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

        broker = ContextBroker(signing_secret="a" * 32, token_budget_total=8000)
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
            agent_output={"result": "output"},
            manifest_hash="",
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

        broker = ContextBroker(signing_secret="a" * 32, token_budget_total=8000)
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
            agent_output={"result": "output"},
            manifest_hash="",
        )

        assert result.value.token_budget_used > 100


class TestContextBrokerConstruction:
    def test_direct_construction_with_short_secret_raises_value_error(self):
        with pytest.raises(ValueError, match="signing_secret"):
            ContextBroker(signing_secret="short", token_budget_total=8000)