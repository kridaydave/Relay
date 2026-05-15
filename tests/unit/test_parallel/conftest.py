"""Shared test doubles for relay.parallel unit tests."""

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from relay.parallel.types import ForkResult, ForkSpec, JoinStrategy
from relay.runners.protocol import AgentOutput, ContextSlice
from relay.runners.registry import AdapterRegistry
from relay.slicer.manifest import AgentManifest
from relay.validator import HandoffValidator, ValidationResult


def make_fork_spec(
    adapter_name: str = "test-adapter",
    reads: frozenset[str] | None = None,
    writes: frozenset[str] | None = None,
) -> ForkSpec:
    manifest = AgentManifest(
        agent_id=adapter_name,
        task_description="test",
        reads=reads or frozenset({"input"}),
        writes=writes or frozenset({"output"}),
        max_tokens=4000,
    )
    return ForkSpec(adapter_name=adapter_name, manifest=manifest)


def make_passing_fork_result(
    fork_index: int = 0,
    adapter_name: str = "test-adapter",
    output_text: str = "result",
    confidence: float = 0.9,
) -> ForkResult:
    output = AgentOutput(
        text=output_text, structured={}, tool_calls=[],
        token_count=10, latency_ms=5, adapter=adapter_name,
    )
    validation = ValidationResult(
        has_contradiction=False, diff={}, contradiction_details=None,
        confidence_score=confidence,
    )
    return ForkResult(
        fork_index=fork_index, adapter_name=adapter_name,
        success=True, agent_output=output, validation=validation, failure=None,
    )


def make_failing_fork_result(
    fork_index: int = 0,
    adapter_name: str = "test-adapter",
) -> ForkResult:
    from relay.types import ErrorCode, Failure
    return ForkResult(
        fork_index=fork_index, adapter_name=adapter_name,
        success=False, agent_output=None, validation=None,
        failure=Failure(reason="fork failed", code=ErrorCode.FORK_EXECUTION_FAILED),
    )


@dataclass
class FixedForkRunner:
    """AgentRunner that returns a fixed response. Used for fork runner tests."""
    output_text: str = "fork result"
    structured: dict | None = None
    fail: bool = False
    delay: float = 0.0

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("FixedForkRunner configured to fail")
        return AgentOutput(
            text="" if self.structured else self.output_text,
            structured=self.structured or {},
            tool_calls=[],
            token_count=10, latency_ms=5, adapter="fixed",
        )


@pytest.fixture
def make_pipeline_components():
    """Fixture that returns (registry, validator) for fork runner tests."""
    registry = AdapterRegistry()
    validator = HandoffValidator()
    return registry, validator


def make_context_slice(
    pipeline_id: str = "test-pipe",
    step: int = 1,
    agent_id: str = "test-agent",
    sections: dict | None = None,
    manifest_hash: str = "",
) -> ContextSlice:
    return ContextSlice(
        pipeline_id=pipeline_id,
        step=step,
        agent_id=agent_id,
        sections=sections or {},
        token_count=0,
        manifest_hash=manifest_hash,
    )
