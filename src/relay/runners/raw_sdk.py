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
from typing import Awaitable, Callable, cast

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice
from relay.slicer.manifest import AgentManifest
from relay.types import JSONDict


MessageList = list[dict[str, str]]
SyncCallable = Callable[[MessageList], str]
AsyncCallable = Callable[[MessageList], Awaitable[str]]


@dataclass
class RawSDKAdapter:
    """Adapter wrapping sync or async callables as AgentRunner.

    Args:
        fn: A sync or async callable that takes messages and returns text.
        adapter_name: Name for this adapter in AgentOutput.
    """

    fn: SyncCallable | AsyncCallable
    adapter_name: str = "raw_sdk"

    def _build_messages(self, slice_: ContextSlice) -> MessageList:
        """Convert ContextSlice.sections to OpenAI-compatible message list."""
        return [{"role": "user", "content": json.dumps(slice_.sections, indent=2)}]

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        """Execute the callable and return normalised output."""
        messages = self._build_messages(slice_)
        start = time.monotonic()
        if inspect.iscoroutinefunction(self.fn):
            async_fn = cast(AsyncCallable, self.fn)
            text: str = await async_fn(messages)
        else:
            sync_fn = cast(SyncCallable, self.fn)
            text = await asyncio.to_thread(sync_fn, messages)
        latency_ms = int((time.monotonic() - start) * 1000)
        return AgentOutput(
            text=text,
            structured=JSONDict(),
            tool_calls=[],
            token_count=slice_.token_count + len(text) // 3,
            latency_ms=latency_ms,
            adapter=self.adapter_name,
        )