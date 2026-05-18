"""Tests for CrewAIAdapter."""

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from relay.runners.crewai import CrewAIAdapter
from .conftest import make_test_manifest, make_test_slice


class TestCrewAIAdapter:
    def test_raises_value_error_when_agent_has_memory_enabled(self) -> None:
        mock_agent = MagicMock()
        mock_agent.memory = True
        with pytest.raises(ValueError, match="memory=True"):
            CrewAIAdapter(agent=mock_agent)

    def test_crewai_adapter_accepts_agent_when_memory_is_disabled(self) -> None:
        mock_agent = MagicMock()
        mock_agent.memory = False
        adapter = CrewAIAdapter(agent=mock_agent)
        assert adapter is not None

    def test_accepts_agent_with_no_memory_attribute(self) -> None:
        _no_memory_spec: list[str] = []
        mock_agent = MagicMock(spec=_no_memory_spec)
        adapter = CrewAIAdapter(agent=mock_agent)
        assert adapter is not None

    @pytest.mark.asyncio
    async def test_raises_import_error_without_crewai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "crewai":
                raise ImportError("No module named 'crewai'")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent = MagicMock()
        mock_agent.memory = False
        with pytest.raises(ImportError, match="relay-middleware\\[crewai\\]"):
            await CrewAIAdapter(agent=mock_agent).run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_single_turn_returns_normalised_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_task = MagicMock()
        mock_task.execute_sync.return_value = "crewai output"  # type: ignore[misc]
        mock_crewai = MagicMock()
        mock_crewai.Task = MagicMock(return_value=mock_task)
        monkeypatch.setitem(sys.modules, "crewai", mock_crewai)
        mock_agent = MagicMock()
        mock_agent.memory = False
        adapter = CrewAIAdapter(agent=mock_agent)
        desc = adapter._build_task_description(make_test_slice(step=7, sections={"x": "y"}))
        assert "Step 7" in desc
        assert '"x": "y"' in desc
