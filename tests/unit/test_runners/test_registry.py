"""Tests for AdapterRegistry."""

import pytest

from relay.runners.registry import AdapterRegistry
from relay.types import Failure, Success, ErrorCode


class TestAdapterRegistryRegister:
    def test_registers_and_retrieves_adapter(self):
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        runner = FixedAgentRunner()
        registry.register("agent-1", runner)
        result = registry.get("agent-1")
        assert isinstance(result, Success)
        assert result.value is runner

    def test_returns_failure_for_unknown_name(self):
        result = AdapterRegistry().get("nonexistent")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ADAPTER_NOT_FOUND
        assert "nonexistent" in result.reason

    def test_raises_on_empty_name(self):
        from .conftest import FixedAgentRunner
        with pytest.raises(ValueError, match="cannot be empty"):
            AdapterRegistry().register("", FixedAgentRunner())

    def test_raises_on_duplicate_name(self):
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        registry.register("agent-1", FixedAgentRunner())
        with pytest.raises(ValueError, match="already registered"):
            registry.register("agent-1", FixedAgentRunner())

    def test_raises_on_non_runner_object(self):
        with pytest.raises(ValueError, match="AgentRunner protocol"):
            AdapterRegistry().register("bad", object())

    def test_list_names_returns_sorted(self):
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        registry.register("zebra", FixedAgentRunner())
        registry.register("alpha", FixedAgentRunner())
        assert registry.list_names() == ["alpha", "zebra"]

    def test_list_names_returns_empty_for_new_registry(self):
        assert AdapterRegistry().list_names() == []
