"""LocalModelAdapter — targets any OpenAI-compatible REST endpoint.

Owns: HTTP request construction and response normalisation.
Does NOT: manage model loading, GPU resources, or server lifecycle.

Compatible with any server that implements /v1/chat/completions
(Ollama >=0.1.14, vLLM >=0.4.0). No streaming in v0.3.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import cast

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest
from relay.types import JSONDict


@dataclass(frozen=True)
class LocalModelAdapter:
    """Adapter for OpenAI-compatible REST endpoints (Ollama, vLLM, etc.).

    Args:
        base_url: Base URL of the model server (trailing slash stripped automatically).
        model: Model name to send in requests.
        adapter_name: Name for this adapter in AgentOutput.
        timeout_seconds: Request timeout in seconds.

    Raises:
        ImportError: If httpx is not installed (raised at call time).
    """

    base_url: str
    model: str
    adapter_name: str = "local_model"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @classmethod
    def create(
        cls,
        base_url: str,
        model: str,
        adapter_name: str = "local_model",
        timeout_seconds: float = 60.0,
    ) -> "LocalModelAdapter":
        """Factory method — strips trailing slash from base_url before construction."""
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            adapter_name=adapter_name,
            timeout_seconds=timeout_seconds,
        )

    def _build_payload(self, slice_: ContextSlice) -> JSONDict:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": json.dumps(slice_.sections, indent=2)}],
            "stream": False,
        }

    async def run(self, slice_: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for LocalModelAdapter. "
                "Install with: pip install relay-middleware[local]"
            )
        payload = self._build_payload(slice_)
        url = f"{self.base_url}/v1/chat/completions"
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data_raw: object = response.json()
        latency_ms = int((time.monotonic() - start) * 1000)
        if not isinstance(data_raw, dict):
            data_raw = {}
        data = cast(JSONDict, data_raw)
        choices_raw: object = data.get("choices", [])
        if isinstance(choices_raw, list) and choices_raw:
            first_choice = choices_raw[0]
            if isinstance(first_choice, dict):
                message_raw: object = first_choice.get("message", {})
                if isinstance(message_raw, dict):
                    text = str(cast(JSONDict, message_raw).get("content", ""))
                else:
                    text = ""
            else:
                text = ""
        else:
            text = ""
        usage_raw: object = data.get("usage", {})
        if isinstance(usage_raw, dict):
            usage = cast(JSONDict, usage_raw)
            total_tokens_raw: object = usage.get("total_tokens")
        else:
            total_tokens_raw = None
        if isinstance(total_tokens_raw, int):
            token_count = total_tokens_raw
        else:
            token_count = slice_.token_count + len(text) // 3
        return AgentOutput(
            text=text, structured=JSONDict(), tool_calls=[],
            token_count=token_count, latency_ms=latency_ms,
            adapter=self.adapter_name,
        )