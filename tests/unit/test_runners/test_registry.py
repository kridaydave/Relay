"""Tests for AdapterRegistry."""

import pytest

from relay.runners.registry import AdapterRegistry
from relay.types import Failure, Success, ErrorCode


from typing import cast
from relay.runners.protocol import AgentRunner


class TestAdapterRegistryRegister:
    def test_registry_succeeds_and_registers_and_retrieves_adapter(self) -> None:
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        runner = FixedAgentRunner()
        registry.register("agent-1", runner)
        result = registry.get("agent-1")
        assert isinstance(result, Success)
        assert result.value is runner

    def test_returns_failure_for_unknown_name(self) -> None:
        result = AdapterRegistry().get("nonexistent")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ADAPTER_NOT_FOUND
        assert "nonexistent" in result.reason

    def test_raises_on_empty_name(self) -> None:
        from .conftest import FixedAgentRunner
        with pytest.raises(ValueError, match="cannot be empty"):
            AdapterRegistry().register("", FixedAgentRunner())

    def test_raises_on_duplicate_name(self) -> None:
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        registry.register("agent-1", FixedAgentRunner())
        with pytest.raises(ValueError, match="already registered"):
            registry.register("agent-1", FixedAgentRunner())

    def test_raises_on_non_runner_object(self) -> None:
        with pytest.raises(ValueError, match="AgentRunner protocol"):
            AdapterRegistry().register("bad", cast(AgentRunner, object()))

    def test_raises_on_sync_run_method(self) -> None:
        """Adapter with sync run() is rejected at registration time (Issue #2)."""
        class SyncRunner:
            def run(self, slice: object, manifest: object) -> None:
                return None

        with pytest.raises(ValueError, match="async def run"):
            AdapterRegistry().register("sync", cast(AgentRunner, SyncRunner()))

    def test_list_names_returns_sorted(self) -> None:
        from .conftest import FixedAgentRunner
        registry = AdapterRegistry()
        registry.register("zebra", FixedAgentRunner())
        registry.register("alpha", FixedAgentRunner())
        assert registry.list_names() == ["alpha", "zebra"]

    def test_list_names_returns_empty_for_new_registry(self) -> None:
        assert AdapterRegistry().list_names() == []
