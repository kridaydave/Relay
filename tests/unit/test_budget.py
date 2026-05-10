"""Unit tests for relay.budget module."""

import pytest

from relay.budget import HardCapEnforcer, TokenCounter
from relay.types import Failure, Success
from tests.conftest import FixedCounter


class TestHardCapEnforcer:
    def test_exact_boundary_passes(self):
        """Exact boundary (used + projected == total) must pass."""
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
        result = enforcer.check(90, 100, "any text")
        assert isinstance(result, Success)

    def test_one_over_returns_failure(self):
        """One over the limit must return Failure."""
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(10))
        result = enforcer.check(91, 100, "any text")
        assert isinstance(result, Failure)
        assert result.code == "BUDGET_EXCEEDED"

    def test_zero_token_slice_passes(self):
        """Zero-token slice always passes regardless of budget state."""
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(0))
        result = enforcer.check(100, 100, "")
        assert isinstance(result, Success)

    def test_negative_count_returns_failure(self):
        """Negative count must return Failure immediately."""
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(-5))
        result = enforcer.check(0, 1000, "any text")
        assert isinstance(result, Failure)
        assert result.code == "INVALID_TOKEN_COUNT"
        assert "negative" in result.reason.lower()

    def test_under_budget_passes(self):
        """Under budget should pass and return Success."""
        enforcer = HardCapEnforcer("pipe-1", FixedCounter(30))
        result = enforcer.check(50, 100, "any text")
        assert isinstance(result, Success)


class TestTokenCounterProtocol:
    def test_fixed_counter_is_protocol_compatible(self):
        """Test that FixedCounter satisfies TokenCounter protocol."""
        counter = FixedCounter(42)
        assert isinstance(counter, TokenCounter)
        assert counter.count("anything") == 42


class TestEmbeddingProviderProtocol:
    def test_fixed_embedding_provider_is_protocol_compatible(self):
        """Test that FixedEmbeddingProvider satisfies EmbeddingProvider protocol."""
        from relay.slicer.providers import EmbeddingProvider
        from tests.conftest import FixedEmbeddingProvider
        provider = FixedEmbeddingProvider([0.1, 0.2, 0.3])
        assert isinstance(provider, EmbeddingProvider)
        vector = provider.embed("any text")
        assert vector == [0.1, 0.2, 0.3]