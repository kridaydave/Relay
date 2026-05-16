"""Shared test doubles for relay.runners unit tests."""

import asyncio
from dataclasses import dataclass

from typing import Any

import pytest

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice
from relay.slicer.manifest import AgentManifest
from relay.types import JSONDict


@dataclass
class FixedAgentRunner:
    """AgentRunner that always returns a fixed AgentOutput. Satisfies the Protocol."""
    output_text: str = "fixed response"
    fail: bool = False
    fail_with: type[Exception] = RuntimeError

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        if self.fail:
            raise self.fail_with("FixedAgentRunner configured to fail")
        return AgentOutput(
            text=self.output_text,
            structured={},
            tool_calls=[],
            token_count=slice.token_count + len(self.output_text) // 4,
            latency_ms=10,
            adapter="fixed",
        )


def make_test_slice(
    sections: JSONDict | None = None,
    token_count: int = 100,
    step: int = 1,
) -> ContextSlice:
    return ContextSlice(
        pipeline_id="test-pipeline",
        step=step,
        agent_id="test-agent",
        sections=sections or {"input": "test data"},
        token_count=token_count,
        manifest_hash="abc123",
    )


def make_test_manifest(
    reads: frozenset[str] | None = None,
    writes: frozenset[str] | None = None,
    max_tokens: int = 4000,
) -> AgentManifest:
    return AgentManifest(
        agent_id="test-agent",
        task_description="Test task",
        reads=reads or frozenset({"input"}),
        writes=writes or frozenset({"output"}),
        max_tokens=max_tokens,
    )