"""AgentRunner protocol and data models for Relay's Layer 3 adapter layer.

Owns: AgentRunner Protocol, AgentOutput, ContextSlice data classes.
Does NOT: execute agents, manage LLM sessions, or own pipeline state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from relay.slicer.manifest import AgentManifest


def _estimate_tokens(data: dict[str, Any]) -> int:
    """Estimate token count by serialised JSON length divided by 4.

    This is a heuristic. Actual token counts vary by model and content.
    """
    return len(json.dumps(data, sort_keys=True)) // 4


@dataclass(frozen=True)
class ContextSlice:
    """A read-only, bounded view of context delivered to a single agent.

    Owns: the data a specific agent is permitted to read for one step.
    Does NOT: contain history, the full envelope, or sections outside the manifest.

    Built by CoreRelayPipeline._build_context_slice() from the current envelope
    and the agent's AgentManifest. The agent never sees envelope metadata
    (pipeline_id, step, timestamp, budget) — it only sees payload sections.
    """

    pipeline_id: str
    step: int
    agent_id: str
    sections: dict[str, Any]
    token_count: int
    manifest_hash: str


@dataclass(frozen=True)
class AgentOutput:
    """Normalised output from any agent adapter.

    Owns: the agent's response in a uniform, Relay-compatible format.
    Does NOT: contain raw provider responses, streaming chunks, or tool execution state.

    The handoff validator runs on AgentOutput, not on raw adapter responses.
    All adapters MUST produce this shape. No adapter-specific fields are permitted
    at this level — extend via structured if needed.
    """

    text: str
    structured: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    token_count: int
    latency_ms: int
    adapter: str

    def __post_init__(self) -> None:
        if self.token_count < 0:
            raise ValueError("token_count must be >= 0")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if not self.adapter:
            raise ValueError("adapter must be non-empty")
        if not self.text and not self.structured:
            raise ValueError("At least one of text or structured must be non-empty")


@runtime_checkable
class AgentRunner(Protocol):
    """Protocol for all agent adapters. Layer 3 of the Relay architecture.

    Every adapter implements exactly this interface.
    The runner receives a bounded ContextSlice and the agent's AgentManifest.
    It returns a normalised AgentOutput.

    Everything else — prompt construction, retries, streaming, session management
    — is the adapter's responsibility. Relay does not prescribe it.

    All adapters are async from the start for v0.4 forward-compatibility.
    Sync callables are wrapped with asyncio.to_thread() inside the adapter.
    """

    async def run(
        self,
        slice: ContextSlice,
        manifest: AgentManifest,
    ) -> AgentOutput:
        """Execute one agent turn and return normalised output.

        Args:
            slice: Bounded, read-only context view for this agent.
            manifest: Agent manifest defining read/write permissions and token budget.

        Returns:
            AgentOutput with text, structured, tool_calls, token_count, latency_ms, adapter.

        Raises:
            Any exception from the underlying provider propagates unchanged.
            Relay catches nothing here — the pipeline's execute_step_with_runner
            wraps the call in a try/except and converts provider exceptions to Failure.
        """
        ...