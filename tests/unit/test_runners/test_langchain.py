"""Tests for LangChainAdapter."""

from unittest.mock import AsyncMock, MagicMock
from typing import cast

import pytest

from relay.runners.langchain import LangChainAdapter
from .conftest import make_test_manifest, make_test_slice
from relay.types import JSONDict


class TestLangChainAdapter:
    @pytest.mark.asyncio
    async def test_calls_ainvoke_when_available(self) -> None:
        """Uses ainvoke when the Runnable supports it."""
        mock_runnable = AsyncMock()
        mock_runnable.ainvoke = AsyncMock(return_value="langchain response")
        output = await LangChainAdapter(runnable=mock_runnable).run(
            make_test_slice(), make_test_manifest()
        )
        assert output.text == "langchain response"
        cast(AsyncMock, mock_runnable.ainvoke).assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_sync_invoke_when_ainvoke_absent(self) -> None:
        """Falls back to to_thread(invoke) when ainvoke not available."""
        class SyncRunnable:
            def invoke(self, input_data: JSONDict) -> str: return "sync response"
        output = await LangChainAdapter(runnable=SyncRunnable()).run(
            make_test_slice(), make_test_manifest()
        )
        assert output.text == "sync response"

    @pytest.mark.asyncio
    async def test_normalises_dict_response_to_text_and_structured(self) -> None:
        mock_runnable = AsyncMock()
        response: JSONDict = {"output": "main text", "score": 0.9}
        mock_runnable.ainvoke = AsyncMock(return_value=response)
        output = await LangChainAdapter(runnable=mock_runnable).run(
            make_test_slice(), make_test_manifest()
        )
        assert output.text == "main text"
        assert output.structured == {"score": 0.9}

    @pytest.mark.asyncio
    async def test_normalises_string_response_to_text_only(self) -> None:
        mock_runnable = AsyncMock()
        mock_runnable.ainvoke = AsyncMock(return_value="plain text")
        output = await LangChainAdapter(runnable=mock_runnable).run(
            make_test_slice(), make_test_manifest()
        )
        assert output.text == "plain text"
        assert output.structured == {}

    @pytest.mark.asyncio
    async def test_normalises_aimessage_with_content_attribute(self) -> None:
        """LangChain AIMessage objects have content attribute."""
        mock_response = MagicMock()
        mock_response.content = "aimessage text"
        mock_runnable = AsyncMock()
        mock_runnable.ainvoke = AsyncMock(return_value=mock_response)
        output = await LangChainAdapter(runnable=mock_runnable).run(
            make_test_slice(), make_test_manifest()
        )
        assert output.text == "aimessage text"

    @pytest.mark.asyncio
    async def test_propagates_runnable_exception(self) -> None:
        mock_runnable = AsyncMock()
        mock_runnable.ainvoke = AsyncMock(side_effect=RuntimeError("LangChain error"))
        with pytest.raises(RuntimeError, match="LangChain error"):
            await LangChainAdapter(runnable=mock_runnable).run(
                make_test_slice(), make_test_manifest()
            )

    @pytest.mark.asyncio
    async def test_build_input_includes_agent_id_and_step(self) -> None:
        mock_runnable = AsyncMock()
        mock_runnable.ainvoke = AsyncMock(return_value="response")
        await LangChainAdapter(runnable=mock_runnable).run(
            make_test_slice(step=5, sections={"key": "val"}), make_test_manifest()
        )
        call_args: dict[str, object] = cast(AsyncMock, mock_runnable.ainvoke).call_args[0][0]  # type: ignore[misc]
        assert isinstance(call_args, dict)
        assert "agent_id" in call_args
        assert "step" in call_args
