"""RawSDKAdapter — wraps a plain callable as an AgentRunner.

Owns: converting ContextSlice to a message list and calling the provided callable.
Does NOT: manage retries, streaming, tool parsing, or LLM sessions.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice
from relay.slicer.manifest import AgentManifest


MessageList = list[dict[str, str]]
SyncCallable = Callable[[MessageList], str]
AsyncCallable = Callable[[MessageList], Awaitable[str]]


@dataclass
class RawSDKAdapter:
    """Adapter wrapping sync or async callables as AgentRunner.

    Args:
        callable: A sync or async callable that takes messages and returns text.
        adapter_name: Name for this adapter in AgentOutput.
    """

    callable: SyncCallable | AsyncCallable
    adapter_name: str = "raw_sdk"

    def _build_messages(self, slice: ContextSlice) -> MessageList:
        """Convert ContextSlice.sections to OpenAI-compatible message list."""
        return [{"role": "user", "content": json.dumps(slice.sections, indent=2)}]

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        """Execute the callable and return normalised output."""
        messages = self._build_messages(slice)
        start = time.monotonic()
        if inspect.iscoroutinefunction(self.callable):
            text = await self.callable(messages)
        else:
            text = await asyncio.to_thread(self.callable, messages)
        latency_ms = int((time.monotonic() - start) * 1000)
        return AgentOutput(
            text=text,
            structured={},
            tool_calls=[],
            token_count=slice.token_count + len(text) // 4,
            latency_ms=latency_ms,
            adapter=self.adapter_name,
        )