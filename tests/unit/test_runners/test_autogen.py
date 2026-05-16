"""Tests for AutoGenAdapter."""

import sys

import pytest

from relay.runners.autogen import AutoGenAdapter
from .conftest import make_test_manifest, make_test_slice


class _MockProxy:
    def __init__(self, chat_messages: dict[object, list[dict[str, str]]]) -> None:
        self.chat_messages = chat_messages

    def initiate_chat(self, agent: object, message: str, max_turns: int) -> None:
        pass


class _UserProxyFactory:
    def __init__(self, proxy: _MockProxy) -> None:
        self._proxy = proxy

    def __call__(self, **kwargs: object) -> _MockProxy:
        return self._proxy


class _MockAutoGen:
    def __init__(self, proxy: _MockProxy) -> None:
        self.UserProxyAgent = _UserProxyFactory(proxy)


class TestAutoGenAdapter:
    def test_raises_import_error_without_autogen_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "autogen":
                raise ImportError("No module named 'autogen'")
            return real_import(name)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent: object = object()
        with pytest.raises(ImportError, match="relay-middleware\\[autogen\\]"):
            adapter = AutoGenAdapter(agent=mock_agent)
            adapter._make_user_proxy()

    @pytest.mark.asyncio
    async def test_raises_import_error_without_pyautogen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "autogen":
                raise ImportError("No module named 'autogen'")
            return real_import(name)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_agent: object = object()
        with pytest.raises(ImportError, match="relay-middleware\\[autogen\\]"):
            adapter = AutoGenAdapter(agent=mock_agent)
            await adapter.run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_single_turn_extracts_last_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_agent: object = object()
        proxy = _MockProxy(
            chat_messages={
                mock_agent: [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "response text"},
                ]
            }
        )
        mock_autogen = _MockAutoGen(proxy)
        monkeypatch.setitem(sys.modules, "autogen", mock_autogen)
        adapter = AutoGenAdapter(agent=mock_agent)
        output = await adapter.run(make_test_slice(), make_test_manifest())
        assert output.text == "response text"
        assert output.adapter == "autogen"

    @pytest.mark.asyncio
    async def test_returns_fallback_text_when_no_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_agent: object = object()
        proxy = _MockProxy(
            chat_messages={mock_agent: []}
        )
        mock_autogen = _MockAutoGen(proxy)
        monkeypatch.setitem(sys.modules, "autogen", mock_autogen)
        adapter = AutoGenAdapter(agent=mock_agent)
        output = await adapter.run(make_test_slice(), make_test_manifest())
        assert output.text == "No response from agent"
        assert output.adapter == "autogen"