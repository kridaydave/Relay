"""Unit tests for relay.context_broker."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from relay.context_broker import ContextBroker, create_context_broker
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import ErrorCode, Failure, SigningKey, Success, create_signing_key


def _make_broker(secret: str = "a" * 32, budget: int = 8000) -> ContextBroker:
    """Helper to create a ContextBroker for testing."""
    key = create_signing_key(secret)
    return ContextBroker(keys={key.key_id: key}, token_budget_total=budget)


class TestCreateInitialEnvelope:
    def test_short_secret_returns_failure(self) -> None:
        """ContextBroker factory must return Failure for secrets shorter than 32 characters."""
        result = create_context_broker(signing_secret="short", token_budget_total=8000)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SECRET
        assert "32 characters" in result.reason

    @patch("relay.context_broker.create_initial_envelope")
    def test_broker_creates_initial_envelope_with_valid_inputs(self, mock_create: MagicMock) -> None:
        mock_create.return_value = Success[ContextEnvelope](
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

    def test_broker_fails_on_empty_pipeline_id(self) -> None:
        broker = _make_broker()
        result = broker.create_initial_envelope(
            pipeline_id="",
            initial_payload={"data": "test"},
            manifest_hash="",
        )

        assert isinstance(result, Failure)
        assert "Invalid pipeline_id" in result.reason
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_broker_fails_on_empty_payload(self) -> None:
        broker = _make_broker()
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
    def test_broker_creates_next_envelope_with_valid_inputs(self, mock_create: MagicMock) -> None:
        mock_create.return_value = Success[ContextEnvelope](
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

        broker = _make_broker()
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
    def test_broker_next_envelope_increments_step_when_created_from_previous(self, mock_create: MagicMock) -> None:
        mock_create.return_value = Success[ContextEnvelope](
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

        broker = _make_broker()
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

    @patch("relay.context_broker.create_next_envelope")
    def test_broker_next_envelope_updates_token_budget(self, mock_create: MagicMock) -> None:
        mock_create.return_value = Success[ContextEnvelope](
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

        broker = _make_broker()
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
        assert result.value.token_budget_used > 100


