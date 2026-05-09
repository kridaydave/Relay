"""Tests for LocalModelAdapter."""

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