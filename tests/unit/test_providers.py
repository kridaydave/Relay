"""Unit tests for relay.providers."""

from typing import Protocol, Any

import pytest

from relay.providers import ProviderRegistry, LLMProvider
from relay.types import Success, Failure, Result


class MockProvider:
    """Mock LLMProvider for testing."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return "mock response"


class FailingProvider:
    """Mock provider that raises an exception."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        raise RuntimeError("Provider failed")


class CyclingProvider:
    """Mock provider for circular fallback testing."""

    def __init__(self, fail: bool = True) -> None:
        self._fail = fail

    def complete(self, prompt: str, **kwargs: Any) -> str:
        if self._fail:
            raise RuntimeError("Provider failed")
        return "success"


class TestProviderRegistry:
    def test_registry_registers_provider_successfully(self):
        registry = ProviderRegistry()
        provider = MockProvider()

        result = registry.register("mock", provider)

        assert isinstance(result, Success)
        assert result.value is None
        assert "mock" in registry._providers

    def test_registry_returns_failure_for_unregistered_provider(self):
        registry = ProviderRegistry()

        result = registry.get("nonexistent")

        assert isinstance(result, Failure)
        assert result.code == "PROVIDER_NOT_FOUND"
        assert "nonexistent" in result.reason

    def test_registry_get_returns_registered_provider(self):
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register("mock", provider)

        result = registry.get("mock")

        assert isinstance(result, Success)
        assert result.value is provider

    def test_registry_complete_calls_provider_complete(self):
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register("mock", provider)

        result = registry.complete("mock", "test prompt")

        assert isinstance(result, Success)
        assert result.value == "mock response"

    def test_registry_falls_back_to_fallback_on_primary_failure(self):
        registry = ProviderRegistry()
        primary = FailingProvider()
        fallback = MockProvider()
        registry.register("primary", primary)
        registry.register("fallback", fallback)
        registry.add_fallback("primary", "fallback")

        result = registry.complete("primary", "test prompt")

        assert isinstance(result, Success)
        assert result.value == "mock response"

    def test_registry_fallback_respects_max_depth(self):
        registry = ProviderRegistry(max_fallback_depth=2)
        p1 = FailingProvider()
        p2 = FailingProvider()
        p3 = FailingProvider()
        p4 = MockProvider()
        registry.register("p1", p1)
        registry.register("p2", p2)
        registry.register("p3", p3)
        registry.register("p4", p4)
        registry.add_fallback("p1", "p2")
        registry.add_fallback("p2", "p3")
        registry.add_fallback("p3", "p4")

        result = registry.complete("p1", "test prompt")

        assert isinstance(result, Failure)
        assert result.code == "FALLBACK_DEPTH_EXCEEDED"

    def test_registry_fallback_detects_circular_chain(self):
        registry = ProviderRegistry()
        p1 = FailingProvider()
        p2 = FailingProvider()
        registry.register("p1", p1)
        registry.register("p2", p2)
        registry.add_fallback("p1", "p2")
        registry.add_fallback("p2", "p1")

        result = registry.complete("p1", "test prompt")

        assert isinstance(result, Failure)
        assert result.code == "FALLBACK_CYCLE_DETECTED"