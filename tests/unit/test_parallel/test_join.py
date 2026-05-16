"""Tests for parallel/join.py — UNION, VOTE, FIRST_WINS strategies."""

import asyncio
from typing import Any, Coroutine

import pytest

from relay.parallel.join import (
    _apply_first_wins,
    _apply_union,
    _apply_vote,
    apply_join_strategy,
)
from relay.parallel.types import ForkResult, ForkSpec, JoinStrategy
from relay.runners.protocol import AgentOutput
from relay.types import ErrorCode, Failure, Result, Success
from relay.validator import ValidationResult

from .conftest import (
    make_failing_fork_result,
    make_fork_spec,
    make_passing_fork_result,
)


class TestUnionStrategy:
    @pytest.mark.asyncio
    async def test_union_merges_non_overlapping_payloads(self):
        """Forks writing different keys → merged dict contains all keys."""
        from relay.validator import ValidationResult
        output_a = AgentOutput(text="", structured={"section_a": "value-a"}, tool_calls=[], token_count=10, latency_ms=5, adapter="a")
        output_b = AgentOutput(text="", structured={"section_b": "value-b"}, tool_calls=[], token_count=10, latency_ms=5, adapter="b")
        val = ValidationResult(has_contradiction=False, diff={}, contradiction_details=None, confidence_score=1.0)
        fork_a = ForkResult(fork_index=0, adapter_name="a", success=True, agent_output=output_a, validation=val, failure=None)
        fork_b = ForkResult(fork_index=1, adapter_name="b", success=True, agent_output=output_b, validation=val, failure=None)

        result = _apply_union([fork_a, fork_b])
        assert isinstance(result, Success)
        assert result.value.get("section_a") == "value-a"
        assert result.value.get("section_b") == "value-b"

    @pytest.mark.asyncio
    async def test_union_fails_on_conflicting_key_values(self):
        """Two forks writing different values for same key → MERGE_CONFLICT."""
        fork0 = make_passing_fork_result(0, output_text="value-a")
        fork1 = make_passing_fork_result(1, output_text="value-b")

        result = _apply_union([fork0, fork1])
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.MERGE_CONFLICT

    @pytest.mark.asyncio
    async def test_union_fails_if_any_fork_failed(self):
        """One failing fork among passing ones → ALL_FORKS_FAILED."""
        results = [make_passing_fork_result(0), make_failing_fork_result(1)]
        result = _apply_union(results)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ALL_FORKS_FAILED

    @pytest.mark.asyncio
    async def test_union_accepts_identical_values_for_same_key(self):
        """Two forks agreeing on same key+value → not a conflict."""
        fork0 = make_passing_fork_result(0, output_text="same")
        fork1 = make_passing_fork_result(1, output_text="same")
        result = _apply_union([fork0, fork1])
        assert isinstance(result, Success)

    @pytest.mark.asyncio
    async def test_union_invariant_agent_output_none(self):
        """ForkResult with success=True but agent_output=None → UNKNOWN_ERROR."""
        from relay.parallel.types import ForkResult
        from relay.types import ErrorCode
        from relay.validator import ValidationResult
        val = ValidationResult(has_contradiction=False, diff={}, contradiction_details=None, confidence_score=1.0)
        bad = ForkResult(
            fork_index=0, adapter_name="bad", success=True,
            agent_output=None, validation=val, failure=None,
        )
        good = make_passing_fork_result(1, output_text="data")
        result = _apply_union([good, bad])
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.UNKNOWN_ERROR


class TestVoteStrategy:
    @pytest.mark.asyncio
    async def test_vote_picks_highest_confidence_passing_fork(self):
        """Fork with confidence 0.9 beats fork with confidence 0.5."""
        results = [
            make_passing_fork_result(0, output_text="low confidence", confidence=0.5),
            make_passing_fork_result(1, output_text="high confidence", confidence=0.9),
        ]
        result = _apply_vote(results)
        assert isinstance(result, Success)
        assert result.value.get("text") == "high confidence"

    @pytest.mark.asyncio
    async def test_vote_discards_failed_forks(self):
        """Failed fork is ignored; passing fork wins."""
        results = [
            make_failing_fork_result(0),
            make_passing_fork_result(1, confidence=0.7),
        ]
        result = _apply_vote(results)
        assert isinstance(result, Success)
        assert result.value.get("text") == "result"

    @pytest.mark.asyncio
    async def test_vote_fails_when_all_forks_failed(self):
        """All failed → ALL_FORKS_FAILED."""
        results = [make_failing_fork_result(0), make_failing_fork_result(1)]
        result = _apply_vote(results)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ALL_FORKS_FAILED

    @pytest.mark.asyncio
    async def test_vote_invariant_agent_output_none(self):
        """ForkResult with success=True but agent_output=None → UNKNOWN_ERROR."""
        from relay.parallel.types import ForkResult
        from relay.types import ErrorCode
        from relay.validator import ValidationResult
        val = ValidationResult(has_contradiction=False, diff={}, contradiction_details=None, confidence_score=1.0)
        bad = ForkResult(
            fork_index=0, adapter_name="bad", success=True,
            agent_output=None, validation=val, failure=None,
        )
        passing = [bad, make_passing_fork_result(1, output_text="data", confidence=0.5)]
        result = _apply_vote(passing)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.UNKNOWN_ERROR


class TestFirstWinsStrategy:
    @pytest.mark.asyncio
    async def test_first_wins_accepts_first_passing_fork(self):
        """First completing fork that passes validation wins."""

        async def fast_fork():
            return make_passing_fork_result(0, output_text="fast")

        async def slow_fork():
            await asyncio.sleep(0.5)
            return make_passing_fork_result(1, output_text="slow")

        spec = make_fork_spec()
        coros = [(0, spec, fast_fork()), (1, spec, slow_fork())]
        result = await _apply_first_wins(coros)
        assert isinstance(result, Success)
        assert result.value.get("text") == "fast"

    @pytest.mark.asyncio
    async def test_first_wins_skips_failing_forks(self):
        """Failing fork is discarded; next passing fork wins."""

        async def fail_fork():
            return make_failing_fork_result(0)

        async def pass_fork():
            return make_passing_fork_result(1, output_text="winner")

        spec = make_fork_spec()
        coros = [(0, spec, fail_fork()), (1, spec, pass_fork())]
        result = await _apply_first_wins(coros)
        assert isinstance(result, Success)
        assert result.value.get("text") == "winner"

    @pytest.mark.asyncio
    async def test_first_wins_cancels_remaining_tasks(self):
        """Tasks that haven't completed are cancelled when a winner is found."""

        cancelled: list[int] = []

        async def winning_fork():
            return make_passing_fork_result(0, output_text="winner")

        async def slow_fork(coro_id: int):
            try:
                await asyncio.sleep(10)
                return make_passing_fork_result(coro_id)
            except asyncio.CancelledError:
                cancelled.append(coro_id)
                raise

        spec = make_fork_spec()
        coros = [(0, spec, winning_fork()), (1, spec, slow_fork(1))]
        result = await _apply_first_wins(coros)
        assert isinstance(result, Success)
        assert result.value.get("text") == "winner"
        assert len(cancelled) > 0

    @pytest.mark.asyncio
    async def test_first_wins_fails_when_all_forks_fail(self):
        """All forks fail → ALL_FORKS_FAILED."""

        async def fail_fork_0():
            return make_failing_fork_result(0)

        async def fail_fork_1():
            return make_failing_fork_result(1)

        spec = make_fork_spec()
        coros = [(0, spec, fail_fork_0()), (1, spec, fail_fork_1())]
        result = await _apply_first_wins(coros)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ALL_FORKS_FAILED


class TestApplyJoinStrategy:
    @pytest.mark.asyncio
    async def test_apply_join_strategy_fails_on_invalid_strategy(self):
        """Invalid strategy returns INVALID_JOIN_STRATEGY Failure."""
        from typing import cast
        invalid_strategy = cast(JoinStrategy, "INVALID_STRATEGY")
        result = await apply_join_strategy(invalid_strategy, [], None)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_JOIN_STRATEGY
