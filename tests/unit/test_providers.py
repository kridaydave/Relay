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