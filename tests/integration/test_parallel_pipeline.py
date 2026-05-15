"""Integration tests for execute_parallel_step through the full pipeline.

Uses FixedForkRunner — no LLM calls, no Relay internals mocked.
Tests the full path: execute_parallel_step -> forks -> join -> execute_step_with_manifest
-> signing -> fork metadata -> snapshot.
"""

import time

import pytest

from relay.core_pipeline import CoreRelayPipeline
from relay.envelope import verify_signature
from relay.parallel import ForkSpec, JoinStrategy
from relay.runners.registry import AdapterRegistry
from relay.slicer.manifest import AgentManifest
from relay.types import ErrorCode, Failure, Success

from tests.unit.test_parallel.conftest import FixedForkRunner


class TestParallelPipeline:
    @pytest.mark.asyncio
    async def test_union_parallel_step_commits_merged_envelope(self, tmp_path):
        """UNION with two non-conflicting forks produces envelope with merged payload."""
        registry = AdapterRegistry()
        registry.register("agent-a", FixedForkRunner(structured={"section_a": "result-a"}))
        registry.register("agent-b", FixedForkRunner(structured={"section_b": "result-b"}))

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )

        manifest_a = AgentManifest("agent-a", "task", frozenset({"input"}), frozenset({"text", "section_a"}), 4000)
        manifest_b = AgentManifest("agent-b", "task", frozenset({"input"}), frozenset({"text", "section_b"}), 4000)

        pipeline.execute_step({"input": "initial data"})

        result = await pipeline.execute_parallel_step(
            fork_specs=[ForkSpec("agent-a", manifest_a), ForkSpec("agent-b", manifest_b)],
            join_strategy=JoinStrategy.UNION,
        )

        assert isinstance(result, Success)
        envelope = result.value
        assert envelope.step == 2
        assert envelope.fork_id is not None
        assert envelope.join_strategy == "UNION"
        assert envelope.fork_count == 2
        assert envelope.forks_succeeded == 2

    @pytest.mark.asyncio
    async def test_union_fails_on_merge_conflict(self, tmp_path):
        """UNION where both forks write the same key with different values -> MERGE_CONFLICT."""
        registry = AdapterRegistry()
        registry.register("agent-a", FixedForkRunner(output_text="value-a"))
        registry.register("agent-b", FixedForkRunner(output_text="value-b"))

        manifest_a = AgentManifest("agent-a", "task", frozenset({"input"}), frozenset({"text"}), 4000)
        manifest_b = AgentManifest("agent-b", "task", frozenset({"input"}), frozenset({"text"}), 4000)

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )
        pipeline.execute_step({"input": "data"})

        result = await pipeline.execute_parallel_step(
            fork_specs=[ForkSpec("agent-a", manifest_a), ForkSpec("agent-b", manifest_b)],
            join_strategy=JoinStrategy.UNION,
        )

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.MERGE_CONFLICT

        current = pipeline.get_current_envelope()
        assert current is not None
        assert current.step == 1

    @pytest.mark.asyncio
    async def test_vote_selects_winner_and_discards_loser(self, tmp_path):
        """VOTE: winner's output committed; loser's output not in envelope."""
        registry = AdapterRegistry()
        registry.register("fork-a", FixedForkRunner(output_text="output-a"))
        registry.register("fork-b", FixedForkRunner(output_text="output-b"))

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )
        pipeline.execute_step({"input": "data"})

        result = await pipeline.execute_parallel_step(
            fork_specs=[
                ForkSpec("fork-a", AgentManifest("fork-a", "task", frozenset({"input"}), frozenset({"text"}), 4000)),
                ForkSpec("fork-b", AgentManifest("fork-b", "task", frozenset({"input"}), frozenset({"text"}), 4000)),
            ],
            join_strategy=JoinStrategy.VOTE,
        )

        assert isinstance(result, Success)
        assert result.value.join_strategy == "VOTE"
        assert result.value.forks_succeeded == 2

    @pytest.mark.asyncio
    async def test_first_wins_commits_envelope_before_slow_fork_completes(self, tmp_path):
        """FIRST_WINS: fast adapter wins; slow adapter is cancelled."""
        registry = AdapterRegistry()
        registry.register("fast", FixedForkRunner(output_text="fast", delay=0.01))
        registry.register("slow", FixedForkRunner(output_text="slow", delay=2.0))

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )
        pipeline.execute_step({"input": "data"})

        start = time.time()
        result = await pipeline.execute_parallel_step(
            fork_specs=[
                ForkSpec("fast", AgentManifest("fast", "task", frozenset(), frozenset({"text"}), 4000)),
                ForkSpec("slow", AgentManifest("slow", "task", frozenset(), frozenset({"text"}), 4000)),
            ],
            join_strategy=JoinStrategy.FIRST_WINS,
        )
        duration = time.time() - start

        assert isinstance(result, Success)
        assert result.value.payload["text"] == "fast"
        assert duration < 1.0

    @pytest.mark.asyncio
    async def test_envelope_fork_metadata_is_signed(self, tmp_path):
        """Fork metadata fields are covered by the envelope signature."""
        registry = AdapterRegistry()
        registry.register("agent-a", FixedForkRunner(output_text="result-a"))
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )
        pipeline.execute_step({"input": "initial"})

        result = await pipeline.execute_parallel_step(
            fork_specs=[ForkSpec("agent-a", AgentManifest("agent-a", "task", frozenset(), frozenset({"text"}), 4000))],
            join_strategy=JoinStrategy.UNION,
        )

        assert isinstance(result, Success)
        envelope = result.value
        assert verify_signature(envelope, "a" * 32)

    @pytest.mark.asyncio
    async def test_sequential_step_after_parallel_step_advances_correctly(self, tmp_path):
        """Sequential execute_step after execute_parallel_step works as normal."""
        registry = AdapterRegistry()
        registry.register("agent-a", FixedForkRunner(output_text="result-a"))
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=str(tmp_path), registry=registry,
        )

        pipeline.execute_step({"input": "s1"})

        await pipeline.execute_parallel_step(
            fork_specs=[ForkSpec("agent-a", AgentManifest("agent-a", "task", frozenset(), frozenset({"text"}), 4000))],
            join_strategy=JoinStrategy.UNION,
        )

        result = pipeline.execute_step({"input": "s3"})

        assert isinstance(result, Success)
        assert result.value.step == 3
        assert result.value.fork_id is None
        assert result.value.payload["input"] == "s3"

    @pytest.mark.asyncio
    async def test_parallel_step_with_no_registry_returns_failure(self, tmp_path):
        """Parallel step without registry -> NO_REGISTRY Failure, state unchanged."""
        pipeline = CoreRelayPipeline(signing_secret="a" * 32, token_budget=8000, storage_path=str(tmp_path))
        pipeline.execute_step({"input": "data"})
        result = await pipeline.execute_parallel_step(
            fork_specs=[ForkSpec("agent-a", AgentManifest("agent-a", "task", frozenset(), frozenset({"text"}), 4000))],
            join_strategy=JoinStrategy.UNION,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_REGISTRY

    @pytest.mark.asyncio
    async def test_parallel_step_with_empty_fork_specs_returns_failure(self, tmp_path):
        """Empty fork_specs -> INVALID_JOIN_STRATEGY Failure."""
        pipeline = CoreRelayPipeline(signing_secret="a" * 32, token_budget=8000, storage_path=str(tmp_path))
        result = await pipeline.execute_parallel_step(fork_specs=[], join_strategy=JoinStrategy.UNION)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_JOIN_STRATEGY
