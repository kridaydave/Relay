"""Unit tests for relay.budget module."""

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from relay.budget.enforcer import HardCapEnforcer
from relay.budget.token_counter import TokenCounter
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import BudgetExceededError


@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""

    value: int

    def count(self, text: str) -> int:
        return self.value


class TestHardCapEnforcer:
    def test_check_passes_when_under_budget(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipe-1",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=50,
            token_budget_total=100,
            payload={"data": "test"},
            signature="sig1",
        )
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(30))

        enforcer.check(envelope, "any text")

    def test_check_passes_at_exact_boundary(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipe-1",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=90,
            token_budget_total=100,
            payload={"data": "test"},
            signature="sig1",
        )
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))

        enforcer.check(envelope, "any text")

    def test_check_raises_when_over_budget(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipe-1",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=91,
            token_budget_total=100,
            payload={"data": "test"},
            signature="sig1",
        )
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))

        with pytest.raises(BudgetExceededError) as exc_info:
            enforcer.check(envelope, "any text")

        assert exc_info.value.used == 91
        assert exc_info.value.projected == 10
        assert exc_info.value.limit == 100
        assert exc_info.value.step == 1

    def test_check_passes_with_zero_tokens(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipe-1",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=50,
            token_budget_total=100,
            payload={"data": "test"},
            signature="sig1",
        )
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(0))

        enforcer.check(envelope, "")

    def test_check_raises_on_negative_count(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipe-1",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=50,
            token_budget_total=100,
            payload={"data": "test"},
            signature="sig1",
        )
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(-5))

        with pytest.raises(ValueError) as exc_info:
            enforcer.check(envelope, "any text")

        assert "negative" in str(exc_info.value)


class TestTokenCounterProtocol:
    def test_fixed_counter_satisfies_protocol(self):
        counter = FixedCounter(10)
        assert isinstance(counter, TokenCounter)

    def test_function_with_protocol(self):
        def count_tokens(counter: TokenCounter, text: str) -> int:
            return counter.count(text)

        counter = FixedCounter(5)
        assert count_tokens(counter, "hello world") == 5