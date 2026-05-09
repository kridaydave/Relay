"""AutoGenAdapter — wraps an AutoGen AssistantAgent for single-turn execution.

Owns: single-turn invocation and delta extraction.
Does NOT: maintain AutoGen conversation history between Relay steps, configure
          groupchats, or manage multi-agent AutoGen coordination.

AutoGen's conversation loop is single-stepped: Relay calls one turn at a time.
A fresh UserProxyAgent is created per run() call. This prevents history
accumulation across Relay steps — Relay's SnapshotStore is the history source.
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
class AutoGenAdapter:
    """Adapter wrapping an AutoGen AssistantAgent as an AgentRunner.

    Args:
        agent: An AutoGen AssistantAgent instance.
        adapter_name: Name for this adapter in AgentOutput.

    Raises:
        ImportError: If pyautogen is not installed (raised at call time).
    """

    agent: Any
    adapter_name: str = "autogen"

    def _make_user_proxy(self) -> Any:
        try:
            import autogen
        except ImportError:
            raise ImportError(
                "pyautogen is required for AutoGenAdapter. "
                "Install with: pip install relay-middleware[autogen]"
            )
        return autogen.UserProxyAgent(
            name="relay_proxy",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=1,
            code_execution_config=False,
        )

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        user_proxy = self._make_user_proxy()
        message = json.dumps(slice.sections, indent=2)
        start = time.monotonic()
        await asyncio.to_thread(
            user_proxy.initiate_chat, self.agent, message=message, max_turns=1
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        chat_history = user_proxy.chat_messages.get(self.agent, [])
        last_msg = chat_history[-1] if chat_history else {}
        raw_text = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
        text = raw_text if raw_text else "No response from agent"
        return AgentOutput(
            text=text, structured={}, tool_calls=[],
            token_count=slice.token_count + len(text) // 4,
            latency_ms=latency_ms, adapter=self.adapter_name,
        )