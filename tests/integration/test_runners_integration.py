"""Integration tests for relay.runners through the full pipeline.

Uses FixedAgentRunner — no LLM calls, no mocking of Relay internals.
Tests the full path: execute_step_with_runner -> adapter -> execute_step_with_manifest
-> signing -> validation -> snapshotting.
"""

from pathlib import Path

import pytest

from relay.runners import AdapterRegistry
from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest
from tests.unit.test_runners.conftest import FixedAgentRunner


@pytest.fixture
def temp_storage(tmp_path: Path) -> str:
    """Temporary storage path for integration tests."""
    return str(tmp_path / "snapshots")


@pytest.mark.asyncio
async def test_pipeline_runs_adapter_and_creates_correct_envelope(temp_storage: str):
    """execute_step_with_runner must create correct step-2 envelope."""
    from relay.core_pipeline import CoreRelayPipeline
    from relay.types import Success

    registry = AdapterRegistry()
    registry.register("agent-1", FixedAgentRunner(output_text="analysis complete"))

    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32,
        token_budget=8000,
        storage_path=temp_storage,
        registry=registry,
    )
    manifest = AgentManifest(
        agent_id="agent-1",
        task_description="Process input",
        reads=frozenset({"input"}),
        writes=frozenset({"text"}),
        max_tokens=4000,
    )

    pipeline.execute_step({"input": "raw data"})

    result = await pipeline.execute_step_with_runner("agent-1", manifest)

    assert isinstance(result, Success)
    assert result.value.step == 2
    assert result.value.payload.get("text") == "analysis complete"


@pytest.mark.asyncio
async def test_pipeline_returns_failure_when_adapter_raises(temp_storage: str):
    """Adapter exception must return Failure(code=ADAPTER_EXECUTION_FAILED)."""
    from relay.core_pipeline import CoreRelayPipeline
    from relay.types import Failure

    registry = AdapterRegistry()
    registry.register("failing", FixedAgentRunner(fail=True))

    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000,
        storage_path=temp_storage, registry=registry,
    )
    manifest = AgentManifest("failing", "task", frozenset(), frozenset({"text"}), 4000)

    pipeline.execute_step({"input": "data"})
    result = await pipeline.execute_step_with_runner("failing", manifest)

    assert isinstance(result, Failure)
    assert result.code == "ADAPTER_EXECUTION_FAILED"
    assert "failing" in result.reason


@pytest.mark.asyncio
async def test_pipeline_returns_failure_without_registry(temp_storage: str):
    """No registry configured must return Failure(code=NO_REGISTRY)."""
    from relay.core_pipeline import CoreRelayPipeline
    from relay.types import Failure

    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
    )
    manifest = AgentManifest("agent-1", "task", frozenset(), frozenset({"text"}), 4000)
    pipeline.execute_step({"input": "data"})
    result = await pipeline.execute_step_with_runner("agent-1", manifest)

    assert isinstance(result, Failure)
    assert result.code == "NO_REGISTRY"


@pytest.mark.asyncio
async def test_pipeline_returns_failure_for_unknown_adapter(temp_storage: str):
    """Unknown adapter name must return Failure(code=ADAPTER_NOT_FOUND)."""
    from relay.core_pipeline import CoreRelayPipeline
    from relay.types import Failure

    registry = AdapterRegistry()
    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000,
        storage_path=temp_storage, registry=registry,
    )
    manifest = AgentManifest("agent-1", "task", frozenset(), frozenset({"text"}), 4000)
    pipeline.execute_step({"input": "data"})
    result = await pipeline.execute_step_with_runner("nonexistent", manifest)

    assert isinstance(result, Failure)
    assert result.code == "ADAPTER_NOT_FOUND"


@pytest.mark.asyncio
async def test_context_slice_excludes_sections_outside_manifest_reads(temp_storage: str):
    """Agent must not receive payload sections outside its manifest.reads."""
    from relay.core_pipeline import CoreRelayPipeline

    received_slices: list[ContextSlice] = []

    class CapturingRunner:
        async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
            received_slices.append(slice)
            return AgentOutput(text="ok", structured={}, tool_calls=[],
                               token_count=10, latency_ms=1, adapter="capture")

    from relay.runners.protocol import AgentRunner
    registry = AdapterRegistry()
    registry.register("capture", CapturingRunner())
    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000,
        storage_path=temp_storage, registry=registry,
    )
    manifest = AgentManifest(
        agent_id="capture",
        task_description="task",
        reads=frozenset({"public_data"}),
        writes=frozenset({"text"}),
        max_tokens=4000,
    )
    pipeline.execute_step({"public_data": "visible", "private_data": "hidden"})
    await pipeline.execute_step_with_runner("capture", manifest)

    assert len(received_slices) == 1
    assert "public_data" in received_slices[0].sections
    assert "private_data" not in received_slices[0].sections


@pytest.mark.asyncio
async def test_context_slice_empty_on_first_step(temp_storage: str):
    """First step (no current envelope) produces empty sections."""
    from relay.core_pipeline import CoreRelayPipeline

    captured_slice: list[ContextSlice] = []

    class SliceCapturingRunner:
        async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
            captured_slice.append(slice)
            return AgentOutput(text="first", structured={}, tool_calls=[],
                               token_count=1, latency_ms=1, adapter="first")

    registry = AdapterRegistry()
    registry.register("first", SliceCapturingRunner())
    pipeline = CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000,
        storage_path=temp_storage, registry=registry,
    )
    manifest = AgentManifest(
        agent_id="first",
        task_description="first step",
        reads=frozenset(),
        writes=frozenset({"text"}),
        max_tokens=4000,
    )
    await pipeline.execute_step_with_runner("first", manifest)

    assert len(captured_slice) == 1
    assert captured_slice[0].step == 0
    assert captured_slice[0].sections == {}