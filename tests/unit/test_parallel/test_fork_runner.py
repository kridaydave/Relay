"""Tests for parallel/fork_runner.py — run_single_fork isolation and failure modes."""

import asyncio

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.parallel.fork_runner import run_single_fork
from relay.parallel.types import ForkSpec, agent_output_to_payload
from relay.runners.protocol import AgentOutput
from relay.types import ErrorCode

from relay.runners.protocol import AgentRunner

from relay.runners.registry import AdapterRegistry
from relay.validator import HandoffValidator

from .conftest import (
    FixedForkRunner,
    make_context_slice,
    make_fork_spec,
)


def _make_envelope(
    step: int = 1,
    payload: dict[str, object] | None = None,
) -> ContextEnvelope:
    from datetime import datetime, timezone
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id="test-pipe",
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100,
        token_budget_total=8000,
        payload=payload or {"input": "data"},
        manifest_hash="",
        signature="sig",
    )


class TestAgentOutputToPayload:
    def test_agent_output_to_payload_includes_text_and_structured_when_mapping(self) -> None:
        output = AgentOutput(
            text="hello",
            structured={"key": "value"},
            tool_calls=[],
            token_count=5, latency_ms=1, adapter="test",
        )
        payload = agent_output_to_payload(output)
        assert payload == {"text": "hello", "key": "value"}

    def test_agent_output_to_payload_includes_tool_calls_when_present(self) -> None:
        output = AgentOutput(
            text="hello",
            structured={},
            tool_calls=[{"name": "tool1"}],
            token_count=5, latency_ms=1, adapter="test",
        )
        payload = agent_output_to_payload(output)
        assert payload == {"text": "hello", "tool_calls": [{"name": "tool1"}]}

    def test_agent_output_to_payload_omits_tool_calls_when_empty(self) -> None:
        output = AgentOutput(
            text="hello", structured={}, tool_calls=[],
            token_count=5, latency_ms=1, adapter="test",
        )
        payload = agent_output_to_payload(output)
        assert "tool_calls" not in payload


class TestRunSingleFork:
    @pytest.mark.asyncio
    async def test_run_single_fork_returns_passing_fork_result_on_success(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """Happy path: adapter returns output, validator passes → ForkResult.success=True."""
        registry, validator = make_pipeline_components
        registry.register("agent-a", FixedForkRunner(output_text="result-a"))
        spec = make_fork_spec("agent-a", writes=frozenset({"text"}))
        env = _make_envelope()
        slice_ = make_context_slice(agent_id="agent-a")

        result = await run_single_fork(
            fork_index=0, spec=spec, slice_=slice_,
            pre_fork_envelope=env, registry=registry, validator=validator,
        )
        assert result.success is True
        assert result.agent_output is not None
        assert result.validation is not None
        assert result.failure is None
        assert result.fork_index == 0
        assert result.adapter_name == "agent-a"

    @pytest.mark.asyncio
    async def test_run_single_fork_returns_failing_result_when_adapter_not_found(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """Unknown adapter name → ForkResult.success=False, failure.code=ADAPTER_NOT_FOUND."""
        registry, validator = make_pipeline_components
        spec = make_fork_spec("unknown-agent")
        env = _make_envelope()
        slice_ = make_context_slice()

        result = await run_single_fork(
            fork_index=0, spec=spec, slice_=slice_,
            pre_fork_envelope=env, registry=registry, validator=validator,
        )
        assert result.success is False
        assert result.agent_output is None
        assert result.validation is None
        assert result.failure is not None
        assert result.failure.code == ErrorCode.ADAPTER_NOT_FOUND
        assert result.fork_index == 0

    @pytest.mark.asyncio
    async def test_run_single_fork_returns_failing_result_when_adapter_raises(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """Adapter exception → ForkResult.success=False, failure.code=FORK_EXECUTION_FAILED."""
        registry, validator = make_pipeline_components
        registry.register("agent-a", FixedForkRunner(fail=True))
        spec = make_fork_spec("agent-a", writes=frozenset({"text"}))
        env = _make_envelope()
        slice_ = make_context_slice(agent_id="agent-a")

        result = await run_single_fork(
            fork_index=0, spec=spec, slice_=slice_,
            pre_fork_envelope=env, registry=registry, validator=validator,
        )
        assert result.success is False
        assert result.agent_output is None
        assert result.validation is None
        assert result.failure is not None
        assert result.failure.code == ErrorCode.FORK_EXECUTION_FAILED
        assert result.fork_index == 0

    @pytest.mark.asyncio
    async def test_run_single_fork_concurrent_calls_do_not_share_state(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """N concurrent run_single_fork calls on same envelope produce N independent results."""
        registry, validator = make_pipeline_components
        registry.register("agent-a", FixedForkRunner(output_text="output-a"))
        registry.register("agent-b", FixedForkRunner(output_text="output-b"))
        spec_a = make_fork_spec("agent-a", writes=frozenset({"text"}))
        spec_b = make_fork_spec("agent-b", writes=frozenset({"text"}))
        env = _make_envelope()
        slice_a = make_context_slice(agent_id="agent-a")
        slice_b = make_context_slice(agent_id="agent-b")

        results = await asyncio.gather(
            run_single_fork(0, spec_a, slice_a, env, registry, validator),
            run_single_fork(1, spec_b, slice_b, env, registry, validator),
        )
        assert len(results) == 2
        assert results[0].fork_index == 0
        assert results[1].fork_index == 1
        assert results[0].adapter_name == "agent-a"
        assert results[1].adapter_name == "agent-b"
        assert results[0].success is True
        assert results[1].success is True

    @pytest.mark.asyncio
    async def test_run_single_fork_with_contradiction_returns_failing_result(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """If validator detects contradiction → ForkResult.success=False."""
        registry, validator = make_pipeline_components
        registry.register("agent-a", FixedForkRunner(
            structured={"entity": "bob", "name": "charlie", "subject": "david", "identifier": "eve", "id": "frank"},
        ))
        spec = make_fork_spec("agent-a", writes=frozenset({"text", "entity", "name", "subject", "identifier", "id"}))
        env = _make_envelope(payload={"entities": ["alice"]})
        slice_ = make_context_slice(agent_id="agent-a")

        result = await run_single_fork(
            fork_index=0, spec=spec, slice_=slice_,
            pre_fork_envelope=env, registry=registry, validator=validator,
        )
        assert result.success is False
        assert result.agent_output is not None
        assert result.validation is not None
        assert result.validation.has_contradiction is True
        assert result.failure is not None
        assert result.fork_index == 0

    @pytest.mark.asyncio
    async def test_run_single_fork_returns_failure_when_manifest_boundary_violated(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """Agent writes to a key not declared in manifest.writes → ForkResult.success=False."""
        registry, validator = make_pipeline_components
        registry.register("agent-a", FixedForkRunner(output_text="result-a"))
        spec = make_fork_spec("agent-a", writes=frozenset({"output"}))
        env = _make_envelope()
        slice_ = make_context_slice(agent_id="agent-a")

        result = await run_single_fork(
            fork_index=0, spec=spec, slice_=slice_,
            pre_fork_envelope=env, registry=registry, validator=validator,
        )
        assert result.success is False
        assert result.agent_output is not None
        assert result.validation is None
        assert result.failure is not None
        assert result.fork_index == 0

    @pytest.mark.asyncio
    async def test_run_single_fork_index_matches_input(
        self,
        make_pipeline_components: tuple[AdapterRegistry, HandoffValidator],
    ) -> None:
        """fork_index in result matches the input index."""
        registry, validator = make_pipeline_components
        registry.register("fast", FixedForkRunner(delay=0.01))
        registry.register("slow", FixedForkRunner(delay=0.1))
        spec_fast = make_fork_spec("fast", writes=frozenset({"text"}))
        spec_slow = make_fork_spec("slow", writes=frozenset({"text"}))
        env = _make_envelope()
        slice_fast = make_context_slice(agent_id="fast")
        slice_slow = make_context_slice(agent_id="slow")

        results = await asyncio.gather(
            run_single_fork(0, spec_fast, slice_fast, env, registry, validator),
            run_single_fork(1, spec_slow, slice_slow, env, registry, validator),
        )
        indices = {r.fork_index for r in results}
        assert indices == {0, 1}


class TestFixedForkRunnerProtocol:
    def test_fixed_fork_runner_satisfies_agent_runner_protocol_when_validated(self) -> None:
        """FixedForkRunner must satisfy the AgentRunner protocol per Rule 7.6."""
        runner = FixedForkRunner()
        assert isinstance(runner, AgentRunner), (
            "FixedForkRunner no longer satisfies AgentRunner protocol"
        )
