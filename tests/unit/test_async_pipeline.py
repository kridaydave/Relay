"""Unit tests for relay.async_pipeline."""

import asyncio
import tempfile
import shutil
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from relay.async_pipeline import AsyncRelayPipeline
from relay.types import Success, Failure
from relay.envelope import ContextEnvelope, RELAY_VERSION


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def async_pipeline(temp_storage):
    return AsyncRelayPipeline(
        signing_secret="test-secret",
        token_budget=8000,
        storage_path=temp_storage
    )


def create_mock_envelope(step: int, pipeline_id: str, payload: dict, timestamp: datetime = None) -> ContextEnvelope:
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=timestamp,
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload=payload,
        signature=f"sig{step}"
    )


class TestAsyncPipelineExecutorCleanup:
    def test_pipeline_has_executor(self, async_pipeline):
        assert async_pipeline._executor is not None
        assert not async_pipeline._executor._shutdown

    def test_close_shuts_down_executor(self, async_pipeline):
        async_pipeline.close()
        assert async_pipeline._executor._shutdown

    def test_context_manager_cleanup(self, temp_storage):
        pipeline = AsyncRelayPipeline(
            signing_secret="test-secret",
            token_budget=8000,
            storage_path=temp_storage
        )
        with pipeline:
            pass
        assert pipeline._executor._shutdown


class TestAsyncPipelineCreatesEnvelope:
    @pytest.mark.asyncio
    async def test_async_pipeline_creates_envelope_on_first_step(self, async_pipeline):
        result = await async_pipeline.execute_step_async({"data": "test-payload"})

        assert isinstance(result, Success)
        assert result.value.step == 1
        assert result.value.pipeline_id == async_pipeline._pipeline_id


class TestAsyncPipelineGetCurrentEnvelope:
    @pytest.mark.asyncio
    async def test_get_current_envelope_async_returns_none_initially(self, async_pipeline):
        result = await async_pipeline.get_current_envelope_async()
        assert result is None
        async_pipeline.close()