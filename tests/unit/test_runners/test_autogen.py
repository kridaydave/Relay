"""Tests for AutoGenAdapter."""

from unittest.mock import MagicMock

import pytest

from relay.runners.autogen import AutoGenAdapter
from .conftest import make_test_manifest, make_test_slice


class TestAutoGenAdapter:
    def test_raises_import_error_without_autogen_installed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "autogen":
                raise ImportError("No module named 'autogen'")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent = MagicMock()
        with pytest.raises(ImportError, match="relay-middleware\\[autogen\\]"):
            adapter = AutoGenAdapter(agent=mock_agent)
            adapter._make_user_proxy()

    @pytest.mark.asyncio
    async def test_raises_import_error_without_pyautogen(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "autogen":
                raise ImportError("No module named 'autogen'")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent = MagicMock()
        with pytest.raises(ImportError, match="relay-middleware\\[autogen\\]"):
            adapter = AutoGenAdapter(agent=mock_agent)
            await adapter.run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_single_turn_extracts_last_message(self, monkeypatch):
        mock_agent = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.chat_messages = {
            mock_agent: [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "response text"},
            ]
        }
        mock_autogen = MagicMock(
            UserProxyAgent=MagicMock(return_value=mock_proxy)
        )
        monkeypatch.setitem(__import__("sys").modules, "autogen", mock_autogen)
        adapter = AutoGenAdapter(agent=mock_agent)
        output = await adapter.run(make_test_slice(), make_test_manifest())
        assert output.text == "response text"
        assert output.adapter == "autogen"

    @pytest.mark.asyncio
    async def test_returns_fallback_text_when_no_history(self, monkeypatch):
        mock_agent = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.chat_messages = {mock_agent: []}
        mock_autogen = MagicMock(
            UserProxyAgent=MagicMock(return_value=mock_proxy)
        )
        monkeypatch.setitem(__import__("sys").modules, "autogen", mock_autogen)
        adapter = AutoGenAdapter(agent=mock_agent)
        output = await adapter.run(make_test_slice(), make_test_manifest())
        assert output.text == "No response from agent"
        assert output.adapter == "autogen"