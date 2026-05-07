"""Unit tests for relay.budget module."""

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from relay.budget import HardCapEnforcer, TokenCounter
from relay.envelope import ContextEnvelope
from relay.types import BudgetExceeded, Failure, Success
from tests.conftest import FixedCounter


def make_envelope(token_budget_used: int = 0, token_budget_total: int = 1000, step: int = 1) -> ContextEnvelope:
    return ContextEnvelope(
        relay_version="0.2.0",
        pipeline_id="test-pipeline",
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=token_budget_used,
        token_budget_total=token_budget_total,
        payload={"data": "test"},
        manifest_hash="",
        signature="sig",
    )


class TestHardCapEnforcer:
    def test_exact_boundary_passes(self):
        """Exact boundary (used + projected == total) must pass."""
        envelope = make_envelope(token_budget_used=90, token_budget_total=100)
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
        result = enforcer.check(envelope, "any text")
        assert isinstance(result, Success)

    def test_one_over_returns_failure(self):
        """One over the limit must return Failure."""
        envelope = make_envelope(token_budget_used=91, token_budget_total=100)
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
        result = enforcer.check(envelope, "any text")
        assert isinstance(result, Failure)
        assert result.code == "BUDGET_EXCEEDED"

    def test_zero_token_slice_passes(self):
        """Zero-token slice always passes regardless of budget state."""
        envelope = make_envelope(token_budget_used=100, token_budget_total=100)
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(0))
        result = enforcer.check(envelope, "")
        assert isinstance(result, Success)

    def test_negative_count_returns_failure(self):
        """Negative count must return Failure immediately."""
        envelope = make_envelope()
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(-5))
        result = enforcer.check(envelope, "any text")
        assert isinstance(result, Failure)
        assert result.code == "INVALID_TOKEN_COUNT"
        assert "negative" in result.reason.lower()

    def test_under_budget_passes(self):
        """Under budget should pass and return Success."""
        envelope = make_envelope(token_budget_used=50, token_budget_total=100)
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(30))
        result = enforcer.check(envelope, "any text")
        assert isinstance(result, Success)


class TestTokenCounterProtocol:
    def test_fixed_counter_is_protocol_compatible(self):
        """Test that FixedCounter satisfies TokenCounter protocol."""
        counter = FixedCounter(42)
        assert isinstance(counter, TokenCounter)
        assert counter.count("anything") == 42