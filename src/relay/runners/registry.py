"""Adapter registry for named AgentRunner instances.

Owns: mapping adapter names to AgentRunner instances.
Does NOT: construct adapters, manage LLM sessions, or validate adapter behavior.

Framework builders register adapters at pipeline initialisation time.
Steps look up adapters by name at execution time.
Names are case-sensitive strings. Registration is final — re-registering
under the same name raises ValueError (fail fast, no silent overwrites).
"""

import inspect
from dataclasses import dataclass, field

from relay.runners.protocol import AgentRunner
from relay.types import ErrorCode, Failure, Result, Success


@dataclass
class AdapterRegistry:
    """Registry of named AgentRunner instances."""

    _adapters: dict[str, AgentRunner] = field(default_factory=dict, init=False, repr=False)

    def register(self, name: str, adapter: AgentRunner) -> None:
        """Register an adapter under a given name.

        Args:
            name: Case-sensitive identifier used to look up this adapter.
            adapter: Any object satisfying the AgentRunner Protocol.

        Raises:
            ValueError: If name is empty, name is already registered,
                        or adapter does not satisfy AgentRunner protocol.
        """
        if not name:
            raise ValueError("Adapter name cannot be empty")
        if name in self._adapters:
            raise ValueError(
                f"Adapter '{name}' is already registered. "
                "Use a different name or create a new registry."
            )
        if not isinstance(adapter, AgentRunner):
            raise ValueError(
                f"Object of type {type(adapter).__name__} does not satisfy AgentRunner protocol. "
                "Implement: async def run(self, slice: ContextSlice, manifest: AgentManifest) -> AgentOutput"
            )
        run_method = getattr(type(adapter), "run", None)
        if run_method is not None and not inspect.iscoroutinefunction(run_method):
            raise ValueError(
                f"Adapter '{name}' must implement async def run(...), got sync method"
            )
        self._adapters[name] = adapter

    def get(self, name: str) -> Result[AgentRunner]:
        """Look up an adapter by name. Returns Failure if not registered."""
        adapter = self._adapters.get(name)
        if adapter is None:
            return Failure(
                reason=f"No adapter registered under name '{name}'. "
                       f"Registered: {self.list_names()}",
                code=ErrorCode.ADAPTER_NOT_FOUND,
            )
        return Success(adapter)

    def list_names(self) -> list[str]:
        """Return sorted list of registered adapter names."""
        return sorted(self._adapters.keys())
