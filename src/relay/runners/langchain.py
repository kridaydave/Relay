"""LangChainAdapter — wraps a LangChain Runnable as an AgentRunner.

Owns: converting ContextSlice to LangChain input format and invoking the Runnable.
Does NOT: configure the Runnable, manage LangChain memory, or handle streaming.

IMPORTANT: LangChain's internal memory (ConversationBufferMemory, etc.) must be
disabled when running under Relay. Relay owns memory via SnapshotStore. Two memory
systems diverge immediately and silently — a direct violation of Relay's trust guarantee.
Pass a stateless Runnable or chain with no memory configured.
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


class _Runnable(Protocol):
    """Minimal Protocol for LangChain Runnables."""

    async def ainvoke(self, input: JSONDict) -> object: ...
    def invoke(self, input: JSONDict) -> object: ...


@dataclass(frozen=True)
class LangChainAdapter:
    """Adapter wrapping a LangChain Runnable as an AgentRunner.

    Args:
        runnable: Any LangChain Runnable (LCEL chain, chat model, etc.).
                  Must be stateless (no memory configured).
        adapter_name: Name for this adapter in AgentOutput.

    Raises:
        ImportError: If langchain-core is not installed (raised at call time).
    """

    runnable: object
    adapter_name: str = "langchain"

    def __post_init__(self) -> None:
        if not hasattr(self.runnable, "ainvoke") and not hasattr(
            self.runnable, "invoke"
        ):
            raise ValueError(
                "LangChainAdapter.runnable must satisfy the Runnable protocol "
                "(require: ainvoke or invoke method)"
            )

    def _build_input(self, slice_: ContextSlice) -> JSONDict:
        return {
            "input": json.dumps(slice_.sections, indent=2),
            "agent_id": slice_.agent_id,
            "step": slice_.step,
        }

    def _normalise_response(self, response: object) -> tuple[str, JSONDict]:
        """Normalise LangChain response to (text, structured)."""
        if isinstance(response, str):
            return response, JSONDict()
        if isinstance(response, dict):
            response_dict = cast(JSONDict, response)
            text = response_dict.get("output", json.dumps(response))
            structured: JSONDict = {
                k: v for k, v in response_dict.items() if k != "output"
            }
            return str(text), structured
        content: object = getattr(response, "content", str(response))
        return str(content), JSONDict()

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        """Invoke the Runnable and return normalised output."""
        try:
            import langchain_core  # pyright: ignore[reportMissingImports]  # noqa: F401
        except ImportError:
            raise ImportError(
                "langchain-core is required for LangChainAdapter. "
                "Install with: pip install relay-middleware[langchain]"
            )
        lc_input = self._build_input(slice_)
        runnable = cast(_Runnable, self.runnable)
        start = time.monotonic()
        response: object
        if hasattr(self.runnable, "ainvoke"):
            response = await runnable.ainvoke(lc_input)
        else:
            response = await asyncio.to_thread(runnable.invoke, lc_input)
        latency_ms = int((time.monotonic() - start) * 1000)
        text, structured = self._normalise_response(response)
        return AgentOutput(
            text=text,
            structured=structured,
            tool_calls=[],
            token_count=slice_.token_count + len(text) // 3,
            latency_ms=latency_ms,
            adapter=self.adapter_name,
        )
