"""Universal adapter layer for Relay — Layer 3 (Agent Runner).

Owns: AgentRunner protocol, AgentOutput/ContextSlice data models,
      AdapterRegistry, and all bundled adapter implementations.
Does NOT: execute agents directly, manage LLM sessions, or own pipeline state.

Import-safe: all framework dependencies (langchain, crewai, autogen, httpx)
are lazy-imported. RawSDKAdapter is safe to import eagerly (stdlib only).
"""

import importlib
import sys

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice
from relay.runners.registry import AdapterRegistry
from relay.runners.raw_sdk import RawSDKAdapter

__all__ = [
    "AgentOutput",
    "AgentRunner",
    "ContextSlice",
    "AdapterRegistry",
    "RawSDKAdapter",
    "LangChainAdapter",
    "CrewAIAdapter",
    "AutoGenAdapter",
    "LocalModelAdapter",
]

_LAZY_ADAPTERS: dict[str, str] = {
    "LangChainAdapter": "relay.runners.langchain",
    "CrewAIAdapter": "relay.runners.crewai",
    "AutoGenAdapter": "relay.runners.autogen",
    "LocalModelAdapter": "relay.runners.local_model",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_ADAPTERS:
        module = importlib.import_module(_LAZY_ADAPTERS[name])
        adapter = getattr(module, name)
        setattr(sys.modules[__name__], name, adapter)
        return adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")