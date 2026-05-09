"""Universal adapter layer for Relay — Layer 3 (Agent Runner).

Owns: AgentRunner protocol, AgentOutput/ContextSlice data models,
      AdapterRegistry, and all bundled adapter implementations.
Does NOT: execute agents directly, manage LLM sessions, or own pipeline state.

Import-safe: all framework dependencies (langchain, crewai, autogen, httpx)
are lazy-imported inside adapter methods. This module can be imported in any
environment without those packages installed.
"""

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice
from relay.runners.registry import AdapterRegistry
from relay.runners.raw_sdk import RawSDKAdapter
from relay.runners.langchain import LangChainAdapter
from relay.runners.crewai import CrewAIAdapter
from relay.runners.autogen import AutoGenAdapter
from relay.runners.local_model import LocalModelAdapter

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