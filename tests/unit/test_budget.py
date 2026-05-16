"""Unit tests for relay.budget module."""

import pytest

from relay.budget import HardCapEnforcer, TokenCounter
from relay.budget.token_counter import HeuristicCounter
from relay.types import ErrorCode, Failure, Success
from tests.conftest import FixedCounter


class TestHardCapEnforcer:
    def test_exact_boundary_passes(self):
        """Exact boundary (used + projected == total) must pass."""
        enforcer = HardCapEnforcer(FixedCounter(10))
        result = enforcer.check(90, 100, "any text")
        assert isinstance(result, Success)

    def test_check_returns_failure_when_over_budget(self):
        enforcer = HardCapEnforcer(FixedCounter(10))
        result = enforcer.check(91, 100, "any text")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.BUDGET_EXCEEDED

    def test_zero_token_slice_passes(self):
        """Zero-token slice always passes regardless of budget state."""
        enforcer = HardCapEnforcer(FixedCounter(0))
        result = enforcer.check(100, 100, "")
        assert isinstance(result, Success)

    def test_negative_count_returns_failure(self):
        """Negative count must return Failure immediately."""
        enforcer = HardCapEnforcer(FixedCounter(-5))
        result = enforcer.check(0, 1000, "any text")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_TOKEN_COUNT
        assert "negative" in result.reason.lower()

    def test_under_budget_passes(self):
        """Under budget should pass and return Success."""
        enforcer = HardCapEnforcer(FixedCounter(30))
        result = enforcer.check(50, 100, "any text")
        assert isinstance(result, Success)


class TestTokenCounterProtocol:
    def test_fixed_counter_is_protocol_compatible(self):
        """Test that FixedCounter satisfies TokenCounter protocol."""
        counter = FixedCounter(42)
        assert isinstance(counter, TokenCounter)
        assert counter.count("anything") == 42

    def test_heuristic_counter_satisfies_token_counter_protocol(self):
        """HeuristicCounter must satisfy TokenCounter protocol."""
        from relay.budget.token_counter import HeuristicCounter
        assert isinstance(HeuristicCounter(), TokenCounter)


class TestEmbeddingProviderProtocol:
    def test_fixed_embedding_provider_is_protocol_compatible(self):
        """Test that FixedEmbeddingProvider satisfies EmbeddingProvider protocol."""
        from relay.slicer.providers import EmbeddingProvider
        from tests.conftest import FixedEmbeddingProvider
        provider = FixedEmbeddingProvider([0.1, 0.2, 0.3])
        assert isinstance(provider, EmbeddingProvider)
        vector = provider.embed("any text")
        assert vector == [0.1, 0.2, 0.3]


class TestHeuristicCounter:
    def test_count_returns_at_least_one_for_empty_string(self):
        counter = HeuristicCounter()
        assert counter.count("") == 1

    def test_count_returns_char_length_divided_by_three(self):
        counter = HeuristicCounter()
        result = counter.count("hello world")  # 11 chars -> 11//3 = 3
        assert result == 3

    def test_count_returns_one_for_short_strings(self):
        counter = HeuristicCounter()
        assert counter.count("ab") == 1  # 2//3 = 0 -> max(1, 0) = 1

    def test_context_manager_enter_returns_self(self):
        counter = HeuristicCounter()
        with counter as cm:
            assert cm is counter

    def test_context_manager_exit_does_not_raise(self):
        counter = HeuristicCounter()
        counter.__enter__()
        counter.__exit__(None, None, None)

    def test_close_does_not_raise(self):
        counter = HeuristicCounter()
        counter.close()


class TestTiktokenCounterFallback:
    def test_tiktoken_counter_is_heuristic_when_tiktoken_unavailable(self):
        """Isolated in subprocess because it mutates sys.modules and builtins.__import__."""
        import subprocess
        import sys
        code = (
            "import builtins; "
            "real = builtins.__import__; "
            "builtins.__import__ = lambda n, *a, **kw: (_ for _ in ()).throw(ImportError) if n == 'tiktoken' else real(n, *a, **kw); "
            "import sys; sys.modules.pop('tiktoken', None); "
            "import importlib; import relay.budget.token_counter as tc; importlib.reload(tc); "
            "assert tc.AutoTokenCounter is tc.HeuristicCounter"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"