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
from typing import Any

from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer.manifest import AgentManifest


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
        base_url = self.base_url.rstrip("/")
        object.__setattr__(self, "base_url", base_url)

    def _build_payload(self, slice: ContextSlice) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": json.dumps(slice.sections, indent=2)}],
            "stream": False,
        }

    async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for LocalModelAdapter. "
                "Install with: pip install relay-middleware[local]"
            )
        payload = self._build_payload(slice)
        url = f"{self.base_url}/v1/chat/completions"
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        latency_ms = int((time.monotonic() - start) * 1000)
        choices = data.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = data.get("usage", {})
        token_count = usage.get("total_tokens") or (slice.token_count + len(text) // 4)
        return AgentOutput(
            text=text, structured={}, tool_calls=[],
            token_count=token_count, latency_ms=latency_ms,
            adapter=self.adapter_name,
        )