"""Unit tests for relay.budget_enforcer."""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.budget_enforcer import TokenBudgetEnforcer
from relay.envelope import ContextEnvelope, create_initial_envelope
from relay.types import Success, Failure


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


class TestCanProceed:
    @patch("relay.envelope.datetime")
    def test_enforcer_allows_execution_when_within_budget(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        envelope_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            token_budget_total=8000,
            secret="test-secret"
        )
        envelope = envelope_result.value

        enforcer = TokenBudgetEnforcer(default_model="gpt-4")
        estimated_tokens = 1000

        result = enforcer.can_proceed(envelope, estimated_tokens)

        assert result.value is True

    @patch("relay.envelope.datetime")
    def test_enforcer_blocks_execution_when_budget_exceeded(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        envelope_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"data": "test"},
            token_budget_total=8000,
            secret="test-secret"
        )
        envelope = envelope_result.value

        enforcer = TokenBudgetEnforcer(default_model="gpt-4")
        estimated_tokens = 10000

        result = enforcer.can_proceed(envelope, estimated_tokens)

        assert result.value is False


class TestEstimateAgentTokens:
    def test_enforcer_estimates_tokens_from_prompt(self):
        enforcer = TokenBudgetEnforcer(default_model="gpt-4")
        prompt = "This is a test prompt with twenty words."

        token_count = enforcer.estimate_agent_tokens(prompt)

        assert token_count == len(prompt) // 4

    def test_enforcer_uses_custom_model_token_multiplier(self):
        enforcer = TokenBudgetEnforcer(default_model="gpt-4")
        prompt = "Test prompt for model multiplier"

        result_with_model = enforcer.estimate_agent_tokens(prompt, model="gpt-3.5-turbo")
        result_without_model = enforcer.estimate_agent_tokens(prompt)

        assert result_with_model == result_without_model