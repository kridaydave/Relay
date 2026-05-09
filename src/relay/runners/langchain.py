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
from typing import Any

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest


@dataclass
class LangChainAdapter:
    """Adapter wrapping a LangChain Runnable as an AgentRunner.

    Args:
        runnable: Any LangChain Runnable (LCEL chain, chat model, etc.).
                  Must be stateless (no memory configured).
        adapter_name: Name for this adapter in AgentOutput.

    Raises:
        AttributeError at call time if langchain-core is not installed.
    """

    runnable: Any
    adapter_name: str = "langchain"

    def _build_input(self, slice: ContextSlice) -> dict[str, Any]:
        return {
            "input": json.dumps(slice.sections, indent=2),
            "agent_id": slice.agent_id,
            "step": slice.step,
        }

    def _normalise_response(self, response: Any) -> tuple[str, dict[str, Any]]:
        """Normalise LangChain response to (text, structured)."""
        if isinstance(response, str):
            return response, {}
        if isinstance(response, dict):
            text = response.get("output", json.dumps(response))
            structured = {k: v for k, v in response.items() if k != "output"}
            return str(text), structured
        return str(getattr(response, "content", str(response))), {}

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        """Invoke the Runnable and return normalised output."""
        lc_input = self._build_input(slice)
        start = time.monotonic()
        if hasattr(self.runnable, "ainvoke"):
            response = await self.runnable.ainvoke(lc_input)
        else:
            response = await asyncio.to_thread(self.runnable.invoke, lc_input)
        latency_ms = int((time.monotonic() - start) * 1000)
        text, structured = self._normalise_response(response)
        return AgentOutput(
            text=text,
            structured=structured,
            tool_calls=[],
            token_count=slice.token_count + len(text) // 4,
            latency_ms=latency_ms,
            adapter=self.adapter_name,
        )