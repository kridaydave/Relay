"""Tests for RawSDKAdapter."""

import pytest

from relay.runners.raw_sdk import RawSDKAdapter
from .conftest import make_test_manifest, make_test_slice


class TestRawSDKAdapter:
    @pytest.mark.asyncio
    async def test_calls_sync_callable_and_returns_output(self):
        def fn(messages): return "response"
        output = await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())
        assert output.text == "response"
        assert output.adapter == "raw_sdk"
        assert output.token_count > 0
        assert output.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_calls_async_callable(self):
        async def async_fn(messages): return "async response"
        output = await RawSDKAdapter(fn=async_fn).run(make_test_slice(), make_test_manifest())
        assert output.text == "async response"

    @pytest.mark.asyncio
    async def test_propagates_callable_exception(self):
        def failing_fn(messages): raise ValueError("sdk crashed")
        with pytest.raises(ValueError, match="sdk crashed"):
            await RawSDKAdapter(fn=failing_fn).run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_token_count_includes_output_length(self):
        def fn(messages): return "x" * 400  # 400 chars / 4 = 100 tokens
        output = await RawSDKAdapter(fn=fn).run(
            make_test_slice(token_count=50), make_test_manifest()
        )
        assert output.token_count >= 50

    @pytest.mark.asyncio
    async def test_structured_is_empty_dict(self):
        output = await RawSDKAdapter(fn=lambda m: "hi").run(
            make_test_slice(), make_test_manifest()
        )
        assert output.structured == {}

    @pytest.mark.asyncio
    async def test_tool_calls_is_empty_list(self):
        output = await RawSDKAdapter(fn=lambda m: "hi").run(
            make_test_slice(), make_test_manifest()
        )
        assert output.tool_calls == []

    @pytest.mark.asyncio
    async def test_build_messages_formats_sections_as_json(self):
        captured_messages: list[list[dict[str, str]]] = []
        def fn(messages):
            captured_messages.append(messages)
            return "response"
        await RawSDKAdapter(fn=fn).run(
            make_test_slice(sections={"key": "value"}), make_test_manifest()
        )
        assert len(captured_messages) == 1
        msg = captured_messages[0][0]
        assert msg["role"] == "user"
        assert '"key": "value"' in msg["content"]