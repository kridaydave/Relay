"""Tests for CrewAIAdapter."""

from unittest.mock import MagicMock

import pytest

from relay.runners.crewai import CrewAIAdapter
from .conftest import make_test_manifest, make_test_slice


class TestCrewAIAdapter:
    def test_raises_value_error_when_agent_has_memory_enabled(self):
        mock_agent = MagicMock()
        mock_agent.memory = True
        with pytest.raises(ValueError, match="memory=True"):
            CrewAIAdapter(agent=mock_agent)

    def test_accepts_agent_without_memory(self):
        mock_agent = MagicMock()
        mock_agent.memory = False
        adapter = CrewAIAdapter(agent=mock_agent)
        assert adapter is not None

    def test_accepts_agent_with_no_memory_attribute(self):
        mock_agent = MagicMock(spec=[])
        adapter = CrewAIAdapter(agent=mock_agent)
        assert adapter is not None

    @pytest.mark.asyncio
    async def test_raises_import_error_without_crewai(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "crewai":
                raise ImportError("No module named 'crewai'")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent = MagicMock()
        mock_agent.memory = False
        with pytest.raises(ImportError, match="relay-middleware\\[crewai\\]"):
            await CrewAIAdapter(agent=mock_agent).run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_single_turn_returns_normalised_output(self, monkeypatch):
        mock_task = MagicMock()
        mock_task.execute_sync.return_value = "crewai output"
        monkeypatch.setitem(__import__("sys").modules, "crewai", MagicMock(Task=lambda **kw: mock_task))
        mock_agent = MagicMock()
        mock_agent.memory = False
        output = await CrewAIAdapter(agent=mock_agent).run(make_test_slice(), make_test_manifest())
        assert output.text == "crewai output"
        assert output.adapter == "crewai"

    @pytest.mark.asyncio
    async def test_build_task_description_includes_step(self, monkeypatch):
        mock_task = MagicMock()
        mock_task.execute_sync.return_value = "output"
        monkeypatch.setitem(__import__("sys").modules, "crewai", MagicMock(Task=lambda **kw: mock_task))
        mock_agent = MagicMock()
        mock_agent.memory = False
        adapter = CrewAIAdapter(agent=mock_agent)
        desc = adapter._build_task_description(make_test_slice(step=7, sections={"x": "y"}))
        assert "Step 7" in desc
        assert '"x": "y"' in desc