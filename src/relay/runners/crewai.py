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
from typing import Any

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest


@dataclass
class CrewAIAdapter:
    """Adapter wrapping a CrewAI Agent as an AgentRunner.

    Args:
        agent: A CrewAI Agent instance with memory=False.
        adapter_name: Name for this adapter in AgentOutput.

    Raises:
        ValueError: If agent has memory=True.
        ImportError: If crewai is not installed (raised at call time).
    """

    agent: Any
    adapter_name: str = "crewai"

    def __post_init__(self) -> None:
        if getattr(self.agent, "memory", False):
            raise ValueError(
                "CrewAI agent has memory=True. Relay owns memory via SnapshotStore. "
                "Construct the agent with memory=False to prevent untracked state divergence."
            )

    def _build_task_description(self, slice: ContextSlice) -> str:
        return f"Step {slice.step} context:\n{json.dumps(slice.sections, indent=2)}"

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        try:
            from crewai import Task
        except ImportError:
            raise ImportError(
                "crewai is required for CrewAIAdapter. "
                "Install with: pip install relay-middleware[crewai]"
            )
        task = Task(description=self._build_task_description(slice), agent=self.agent)
        start = time.monotonic()
        response = await asyncio.to_thread(task.execute_sync)
        latency_ms = int((time.monotonic() - start) * 1000)
        text = str(response) if not isinstance(response, str) else response
        return AgentOutput(
            text=text, structured={}, tool_calls=[],
            token_count=slice.token_count + len(text) // 4,
            latency_ms=latency_ms, adapter=self.adapter_name,
        )