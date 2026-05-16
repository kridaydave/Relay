"""Tests for RawSDKAdapter."""

from collections.abc import Callable

import pytest

from relay.runners.raw_sdk import RawSDKAdapter
from .conftest import make_test_manifest, make_test_slice


class TestRawSDKAdapter:
    @pytest.mark.asyncio
    async def test_calls_sync_callable_and_returns_output(self) -> None:
        def fn(messages: list[dict[str, str]]) -> str:
            return "response"
        output = await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())
        assert output.text == "response"
        assert output.adapter == "raw_sdk"
        assert output.token_count > 0
        assert output.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_calls_async_callable(self) -> None:
        async def fn(messages: list[dict[str, str]]) -> str:
            return "async response"
        output = await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())
        assert output.text == "async response"
        assert output.adapter == "raw_sdk"

    @pytest.mark.asyncio
    async def test_propagates_callable_exception(self) -> None:
        def fn(messages: list[dict[str, str]]) -> str:
            raise ValueError("fn error")
        with pytest.raises(ValueError, match="fn error"):
            await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())

    @pytest.mark.asyncio
    async def test_token_count_includes_output_length(self) -> None:
        captured_messages: list[list[dict[str, str]]] = []
        async def fn(messages: list[dict[str, str]]) -> str:
            captured_messages.append(messages)
            return "response"
        slice_ = make_test_slice(token_count=50)
        output = await RawSDKAdapter(fn=fn).run(slice_, make_test_manifest())
        assert output.token_count == 50 + len("response") // 3
        assert len(captured_messages) == 1

    @pytest.mark.asyncio
    async def test_structured_is_empty_dict(self) -> None:
        def fn(messages: list[dict[str, str]]) -> str:
            return "test"
        output = await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())
        assert not output.structured

    @pytest.mark.asyncio
    async def test_tool_calls_is_empty_list(self) -> None:
        def fn(messages: list[dict[str, str]]) -> str:
            return "test"
        output = await RawSDKAdapter(fn=fn).run(make_test_slice(), make_test_manifest())
        assert not output.tool_calls

    @pytest.mark.asyncio
    async def test_build_messages_formats_sections_as_json(self) -> None:
        captured_messages: list[list[dict[str, str]]] = []
        async def fn(messages: list[dict[str, str]]) -> str:
            captured_messages.append(messages)
            return "response"
        slice_ = make_test_slice(sections={"key": "value"})
        await RawSDKAdapter(fn=fn).run(slice_, make_test_manifest())
        assert len(captured_messages) == 1
        msg = captured_messages[0][0]
        assert msg["role"] == "user"
        assert '"key": "value"' in msg["content"]