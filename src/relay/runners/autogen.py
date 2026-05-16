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
from typing import Protocol, cast

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest
from relay.types import JSONDict


class _UserProxyWithChat(Protocol):
    def initiate_chat(self, agent: object, message: str, max_turns: int) -> object: ...
    chat_messages: object


def _make_user_proxy_with_chat(obj: object) -> _UserProxyWithChat:
    return cast(_UserProxyWithChat, obj)


@dataclass
class AutoGenAdapter:
    """Adapter wrapping an AutoGen AssistantAgent as an AgentRunner.

    Args:
        agent: An AutoGen AssistantAgent instance.
        adapter_name: Name for this adapter in AgentOutput.

    Raises:
        ImportError: If pyautogen is not installed (raised at call time).
    """

    agent: object
    adapter_name: str = "autogen"

    def _make_user_proxy(self) -> _UserProxyWithChat:
        try:
            from autogen import UserProxyAgent  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "pyautogen is required for AutoGenAdapter. "
                "Install with: pip install relay-middleware[autogen]"
            )
        proxy_obj: object = UserProxyAgent(
            name="relay_proxy",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=1,
            code_execution_config=False,
        )
        return _make_user_proxy_with_chat(proxy_obj)

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        user_proxy = self._make_user_proxy()
        message = json.dumps(slice_.sections, indent=2)
        start = time.monotonic()
        await asyncio.to_thread(
            user_proxy.initiate_chat, self.agent, message=message, max_turns=1
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        chat_messages_raw: object = user_proxy.chat_messages
        chat_history: list[object] = []
        if isinstance(chat_messages_raw, dict):
            agent_key: object = self.agent
            chat_history_raw: object = chat_messages_raw.get(agent_key, [])
            if isinstance(chat_history_raw, list):
                chat_history = cast(list[object], chat_history_raw)
        last_msg: object = chat_history[-1] if chat_history else JSONDict()
        if isinstance(last_msg, dict):
            last_msg_dict = cast(JSONDict, last_msg)
            content_raw: object = last_msg_dict.get("content", "")
            raw_text = str(content_raw) if content_raw else ""
        else:
            raw_text = str(last_msg)
        text = raw_text if raw_text else "No response from agent"
        return AgentOutput(
            text=text, structured=JSONDict(), tool_calls=[],
            token_count=slice_.token_count + len(text) // 3,
            latency_ms=latency_ms, adapter=self.adapter_name,
        )