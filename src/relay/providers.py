"""Multi-provider management for Relay.

Owns: provider registration, routing logic, fallback chain.
Does NOT: execute LLM calls, manage context, or validate responses.
"""

from typing import Protocol, Any, Dict

from relay.types import Result, Success, Failure


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    def complete(self, prompt: str, **kwargs: Any) -> str: ...


class ProviderRegistry:
    """Registry and router for LLM providers."""

    def __init__(self, max_fallback_depth: int = 3) -> None:
        self._providers: Dict[str, LLMProvider] = {}
        self._fallbacks: Dict[str, str] = {}
        self._max_fallback_depth = max_fallback_depth

    def register(self, name: str, provider: LLMProvider) -> Result[None]:
        """Register a provider by name."""
        self._providers[name] = provider
        return Success(None)

    def get(self, name: str) -> Result[LLMProvider]:
        """Get a provider by name."""
        provider = self._providers.get(name)
        if provider is None:
            return Failure(reason=f"Provider '{name}' not found", code="PROVIDER_NOT_FOUND")
        return Success(provider)

    def complete(
        self,
        provider_name: str,
        prompt: str,
        _depth: int = 0,
        _visited: set[str] | None = None,
        **kwargs: Any
    ) -> Result[str]:
        """Complete a prompt using provider, falling back on failure."""
        if _visited is None:
            _visited = set()

        if provider_name in _visited:
            return Failure(
                reason=f"Circular fallback chain detected: {provider_name}",
                code="FALLBACK_CYCLE_DETECTED"
            )

        if _depth >= self._max_fallback_depth:
            return Failure(
                reason=f"Max fallback depth ({self._max_fallback_depth}) exceeded",
                code="FALLBACK_DEPTH_EXCEEDED"
            )

        result = self.get(provider_name)
        if isinstance(result, Failure):
            return result
        provider = result.value

        new_visited = _visited | {provider_name}
        try:
            output = provider.complete(prompt, **kwargs)
            return Success(output)
        except Exception as e:
            fallback = self._fallbacks.get(provider_name)
            if fallback is None:
                return Failure(reason=str(e), code="COMPLETION_FAILED")
            return self.complete(fallback, prompt, _depth=_depth + 1, _visited=new_visited, **kwargs)

    def add_fallback(self, primary: str, fallback: str) -> None:
        """Add a fallback provider chain."""
        self._fallbacks[primary] = fallback