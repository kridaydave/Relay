"""Tests for LocalModelAdapter."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from relay.runners.local_model import LocalModelAdapter
from .conftest import make_test_manifest, make_test_slice


class TestLocalModelAdapter:
    def test_strips_trailing_slash_from_base_url(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434/", model="llama3")
        assert adapter.base_url == "http://localhost:11434"

    def test_preserves_url_without_trailing_slash(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.base_url == "http://localhost:11434"

    def test_is_frozen_dataclass(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        with pytest.raises(Exception):
            adapter.model = "changed"  # type: ignore[misc]

    def test_default_adapter_name(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.adapter_name == "local_model"

    def test_default_timeout(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        assert adapter.timeout_seconds == 60.0

    @pytest.mark.asyncio
    async def test_raises_import_error_without_httpx(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="relay-middleware\\[local\\]"):
            await LocalModelAdapter(
                base_url="http://localhost:11434", model="llama3"
            ).run(make_test_slice(), make_test_manifest())

    def test_build_payload_includes_model_and_messages(self):
        adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
        payload = adapter._build_payload(make_test_slice(sections={"key": "val"}))
        assert payload["model"] == "llama3"
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["stream"] is False

    @pytest.mark.asyncio
    async def test_run_returns_agent_output_with_full_response(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}],
            "usage": {"total_tokens": 50},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            result = await adapter.run(make_test_slice(), make_test_manifest())

        assert result.text == "Hello world"
        assert result.token_count == 50
        assert result.adapter == "local_model"
        assert result.structured == {}
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_choices(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [],
            "usage": {"total_tokens": 10},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            with pytest.raises(ValueError, match="text or structured"):
                await adapter.run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_run_falls_back_to_heuristic_token_count(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            result = await adapter.run(make_test_slice(token_count=200), make_test_manifest())

        assert result.text == "hi"
        assert result.token_count == 200  # slice.token_count + len("hi")//4 = 200 + 0

    @pytest.mark.asyncio
    async def test_run_propagates_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = RuntimeError("HTTP 400")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = LocalModelAdapter(base_url="http://localhost:11434", model="llama3")
            with pytest.raises(RuntimeError, match="HTTP 400"):
                await adapter.run(make_test_slice(), make_test_manifest())