"""Unit tests for relay.budget module."""

import pytest

from relay.budget import HardCapEnforcer, TokenCounter
from relay.budget.token_counter import HeuristicCounter
from relay.types import ErrorCode, Failure, Success
from tests.conftest import FixedCounter


class TestHardCapEnforcer:
    def test_check_passes_when_exact_boundary_reached(self) -> None:
        """Exact boundary (used + projected == total) must pass."""
        enforcer = HardCapEnforcer(FixedCounter(10))
        result = enforcer.check(90, 100, "any text")
        assert isinstance(result, Success)

    def test_check_returns_failure_when_over_budget(self) -> None:
        enforcer = HardCapEnforcer(FixedCounter(10))
        result = enforcer.check(91, 100, "any text")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.BUDGET_EXCEEDED

    def test_check_passes_for_zero_token_slice_even_at_limit(self) -> None:
        """Zero-token slice always passes regardless of budget state."""
        enforcer = HardCapEnforcer(FixedCounter(0))
        result = enforcer.check(100, 100, "")
        assert isinstance(result, Success)

    def test_check_passes_when_under_budget(self) -> None:
        """Under budget should pass and return Success."""
        enforcer = HardCapEnforcer(FixedCounter(30))
        result = enforcer.check(50, 100, "any text")
        assert isinstance(result, Success)


class TestTokenCounterProtocol:
    def test_fixed_counter_complies_with_token_counter_protocol(self) -> None:
        """Test that FixedCounter satisfies TokenCounter protocol."""
        counter = FixedCounter(42)
        assert isinstance(counter, TokenCounter)
        assert counter.count("anything") == 42

    def test_heuristic_counter_complies_with_token_counter_protocol(self) -> None:
        """HeuristicCounter must satisfy TokenCounter protocol."""
        from relay.budget.token_counter import HeuristicCounter
        assert isinstance(HeuristicCounter(), TokenCounter)


class TestEmbeddingProviderProtocol:
    def test_fixed_embedding_provider_complies_with_embedding_provider_protocol(self) -> None:
        """Test that FixedEmbeddingProvider satisfies EmbeddingProvider protocol."""
        from relay.slicer.providers import EmbeddingProvider
        from tests.conftest import FixedEmbeddingProvider
        provider = FixedEmbeddingProvider([0.1, 0.2, 0.3])
        assert isinstance(provider, EmbeddingProvider)
        vector = provider.embed("any text")
        assert vector == [0.1, 0.2, 0.3]


class TestHeuristicCounter:
    def test_count_returns_at_least_one_for_empty_string(self) -> None:
        counter = HeuristicCounter()
        assert counter.count("") == 1

    def test_count_returns_char_length_divided_by_three(self) -> None:
        counter = HeuristicCounter()
        result = counter.count("hello world")  # 11 chars -> 11//3 = 3
        assert result == 3

    def test_count_returns_one_for_short_strings(self) -> None:
        counter = HeuristicCounter()
        assert counter.count("ab") == 1  # 2//3 = 0 -> max(1, 0) = 1

    def test_context_manager_enter_returns_self(self) -> None:
        counter = HeuristicCounter()
        with counter as cm:
            assert cm is counter

    def test_context_manager_exit_does_not_raise_when_called(self) -> None:
        counter = HeuristicCounter()
        counter.__enter__()
        counter.__exit__(None, None, None)

    def test_close_does_not_raise_when_called(self) -> None:
        counter = HeuristicCounter()
        counter.close()

    def test_heuristic_counter_approximates_bpe_when_benchmarked(self) -> None:
        """HeuristicCounter (len//3) approximates BPE within a documented tolerance.

        This is a ground-truth benchmark per Rule 6.2 — heuristic accuracy is
        documented as approximate. If tiktoken is not installed, the test is skipped.
        The 0.2–4.0 bound covers worst-case inputs: repeated characters where
        BPE is highly efficient and repetitive numeric patterns where each number
        is a separate token.
        """
        try:
            import tiktoken
        except ImportError:
            pytest.skip("tiktoken not installed — skipping BPE benchmark")
        enc = tiktoken.get_encoding("cl100k_base")  # type: ignore[misc]
        samples = [
            "hello world",
            "The quick brown fox jumps over the lazy dog",
            "a" * 300,
            "Paris is the capital of France and a major European city.",
            "1 2 3 4 5 6 7 8 9 10 " * 10,
        ]
        for text in samples:
            bpe_count = len(enc.encode(text))  # type: ignore[misc]
            heuristic_count = HeuristicCounter().count(text)
            ratio = heuristic_count / bpe_count if bpe_count > 0 else 1.0
            assert 0.2 <= ratio <= 4.0, (
                f"HeuristicCounter({heuristic_count}) for {text!r} is "
                f"outside [0.2, 4.0] of BPE({bpe_count}) — ratio={ratio:.2f}"
            )


class TestTiktokenCounterFallback:
    def test_tiktoken_counter_is_heuristic_when_tiktoken_unavailable(self) -> None:
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