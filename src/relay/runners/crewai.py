"""CrewAIAdapter — wraps a CrewAI Agent for single-turn execution under Relay.

Owns: task construction, single-turn invocation, output normalisation.
Does NOT: manage CrewAI crew lifecycle, multi-agent communication, or CrewAI memory.

IMPORTANT: CrewAI internal memory (memory=True on Agent) creates an untracked
second state store parallel to Relay's SnapshotStore. This causes silent state
divergence and is incompatible with Relay's correctness guarantees.
CrewAI memory is detected at construction and raises ValueError — it is not
a warning but a hard failure. Framework builders must pass memory=False agents.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol, cast

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest
from relay.types import JSONDict


class _CrewAIAgent(Protocol):
    memory: bool


class _CrewAITask(Protocol):
    def execute_sync(self) -> object: ...


def _make_crewai_agent(obj: object) -> _CrewAIAgent:
    return cast(_CrewAIAgent, obj)


def _make_crewai_task(obj: object) -> _CrewAITask:
    return cast(_CrewAITask, obj)


@dataclass
class CrewAIAdapter:
    """Adapter wrapping a CrewAI Agent as an AgentRunner.

    Args:
        agent: A CrewAI Agent instance with memory=False.
        adapter_name: Name for this adapter in AgentOutput.
        timeout_seconds: Maximum time in seconds for agent execution. None disables timeout.

    Raises:
        ValueError: If agent has memory=True.
        ImportError: If crewai is not installed (raised at call time).
    """

    agent: object
    adapter_name: str = "crewai"
    timeout_seconds: float | None = 300.0

    def __post_init__(self) -> None:
        if hasattr(self.agent, "memory") and _make_crewai_agent(self.agent).memory:
            raise ValueError(
                "CrewAI agent has memory=True. Relay owns memory via SnapshotStore. "
                "Construct the agent with memory=False to prevent untracked state divergence."
            )

    def _build_task_description(self, slice_: ContextSlice) -> str:
        return f"Step {slice_.step} context:\n{json.dumps(slice_.sections, indent=2)}"

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        try:
            from crewai import Task  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "crewai is required for CrewAIAdapter. "
                "Install with: pip install relay-middleware[crewai]"
            )
        task_obj: object = Task(description=self._build_task_description(slice_), agent=self.agent)
        task = _make_crewai_task(task_obj)
        start = time.monotonic()
        coro = asyncio.to_thread(task.execute_sync)
        if self.timeout_seconds is not None:
            coro = asyncio.wait_for(coro, timeout=self.timeout_seconds)
        response_raw: object = await coro
        latency_ms = int((time.monotonic() - start) * 1000)
        text = str(response_raw) if not isinstance(response_raw, str) else response_raw
        return AgentOutput(
            text=text, structured={}, tool_calls=[],
            token_count=slice_.token_count + len(text) // 3,
            latency_ms=latency_ms, adapter=self.adapter_name,
        )