"""Tests for LocalModelAdapter."""

import sys
from typing import cast

import pytest

from relay.runners.local_model import LocalModelAdapter
from relay.types import JSONDict
from .conftest import make_test_manifest, make_test_slice


class _MockResponse:
    def __init__(self, json_data: JSONDict | None = None) -> None:
        self._json_data = json_data or {}
        self._raise_error: BaseException | None = None

    def raise_for_status(self) -> None:
        if self._raise_error is not None:
            raise self._raise_error

    def json(self) -> object:
        return self._json_data


class _MockClient:
    """AsyncClient mock that delegates to _MockHttpx.last_response."""
    def __init__(self, **kwargs: object) -> None:
        self._response = _MockHttpx.last_response or _MockResponse()

    async def post(self, url: str, json: JSONDict) -> _MockResponse:
        return self._response

    async def __aenter__(self) -> "_MockClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class _MockHttpx:
    """Stand-in for the httpx module with configurable response."""
    last_response: _MockResponse | None = None

    class AsyncClient(_MockClient):
        pass


class TestLocalModelAdapter:
    def test_local_model_adapter_strips_trailing_slash_from_base_url_when_initialized(self) -> None:
        adapter = LocalModelAdapter(base_url="http://localhost:11434/", model="llama3")
        assert adapter.base_url == "http://localhost:11434"

    def test_local_model_adapter_preserves_url_without_trailing_slash_when_initialized(self) -> None:
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.base_url == "http://localhost:11434"

    def test_local_model_adapter_uses_default_adapter_name_when_unspecified(self) -> None:
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.adapter_name == "local_model"

    def test_local_model_adapter_uses_default_timeout_when_unspecified(self) -> None:
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.timeout_seconds == 60.0

    @pytest.mark.asyncio
    async def test_raises_import_error_without_httpx(self) -> None:
        import builtins
        real_import = builtins.__import__
        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "httpx":
                raise ImportError
            return real_import(name)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(builtins, "__import__", mock_import)
            with pytest.raises(ImportError, match="relay-middleware\\[local\\]"):
                await LocalModelAdapter(
                    base_url="http://localhost:11434", model="llama3"
                ).run(make_test_slice(), make_test_manifest())

    def test_local_model_adapter_build_payload_includes_model_and_messages_when_called(self) -> None:
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        payload = adapter._build_payload(make_test_slice(sections={"key": "val"}))
        assert payload["model"] == "llama3"
        messages = cast(list[JSONDict], payload["messages"])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert payload["stream"] is False

    @pytest.mark.asyncio
    async def test_run_returns_agent_output_with_full_response(self) -> None:
        _MockHttpx.last_response = _MockResponse(
            json_data={
                "choices": [{"message": {"content": "Hello world"}}],
                "usage": {"total_tokens": 50},
            }
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "httpx", _MockHttpx)
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            result = await adapter.run(make_test_slice(), make_test_manifest())
        assert result.text == "Hello world"
        assert result.token_count == 50
        assert result.adapter == "local_model"
        assert result.structured == {}
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_choices(self) -> None:
        _MockHttpx.last_response = _MockResponse(
            json_data={
                "choices": [],
                "usage": {"total_tokens": 10},
            }
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "httpx", _MockHttpx)
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            with pytest.raises(ValueError, match="text or structured"):
                await adapter.run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_run_falls_back_to_heuristic_token_count(self) -> None:
        _usage: dict[str, object] = {}
        _MockHttpx.last_response = _MockResponse(
            json_data={
                "choices": [{"message": {"content": "hi"}}],
                "usage": _usage,
            }
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "httpx", _MockHttpx)
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            result = await adapter.run(make_test_slice(token_count=200), make_test_manifest())
        assert result.text == "hi"
        assert result.token_count == 200

    @pytest.mark.asyncio
    async def test_run_propagates_http_error(self) -> None:
        mock_response = _MockResponse()
        mock_response._raise_error = RuntimeError("HTTP 400")
        _MockHttpx.last_response = mock_response
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "httpx", _MockHttpx)
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            with pytest.raises(RuntimeError, match="HTTP 400"):
                await adapter.run(make_test_slice(), make_test_manifest())
