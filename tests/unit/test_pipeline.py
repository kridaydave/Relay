"""Unit tests for relay.pipeline."""

import tempfile
import shutil
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from relay.pipeline import RelayPipeline
from relay.types import Success, Failure
from relay.envelope import ContextEnvelope, RELAY_VERSION


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def pipeline(temp_storage):
    return RelayPipeline(
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


class TestPipelineCreatesEnvelope:
    def test_pipeline_creates_envelope_on_first_step(self, pipeline):
        result = pipeline.execute_step({"data": "test-payload"})

        assert isinstance(result, Success)
        assert result.value.step == 1
        assert result.value.pipeline_id == pipeline._pipeline_id
        assert result.value.payload == {"data": "test-payload"}


class TestPipelineCreatesNextEnvelope:
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_pipeline_creates_next_envelope_on_subsequent_step(
        self, mock_next, mock_initial, pipeline
    ):
        mock_initial.return_value = Success(create_mock_envelope(1, pipeline._pipeline_id, {"initial": "data"}))
        mock_next.return_value = Success(create_mock_envelope(2, pipeline._pipeline_id, {"next": "data"}))

        pipeline.execute_step({"initial": "data"})
        result = pipeline.execute_step({"next": "data"})

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.payload == {"next": "data"}
        mock_next.assert_called_once()


class TestPipelineValidationAndSnapshot:
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_pipeline_validates_and_saves_snapshot_on_clean_handoff(
        self, mock_next, mock_initial, pipeline
    ):
        mock_initial.return_value = Success(create_mock_envelope(1, pipeline._pipeline_id, {"entities": ["entity1"]}))
        mock_next.return_value = Success(create_mock_envelope(2, pipeline._pipeline_id, {"entities": ["entity1", "entity2"]}))

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step({"entities": ["entity1", "entity2"], "data": "next"})

        assert isinstance(result, Success)
        assert result.value.step == 2


class TestPipelineRollback:
    @patch("relay.pipeline.SnapshotStore")
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_pipeline_triggers_rollback_on_contradiction(
        self, mock_next, mock_initial, mock_store_cls
    ):
        temp_dir = tempfile.mkdtemp()
        try:
            mock_store = MagicMock()
            mock_store.save_snapshot.return_value = Success("snapshot-id")
            mock_store.load_snapshot.return_value = Failure(
                reason="Snapshot not found",
                code="SNAPSHOT_NOT_FOUND"
            )
            mock_store_cls.return_value = mock_store

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            mock_initial.return_value = Success(create_mock_envelope(1, pipeline._pipeline_id, {"entities": ["entity1"]}))
            mock_next.return_value = Success(create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"}))

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            result = pipeline.execute_step({"data": "next"})

            assert isinstance(result, Failure)
            assert "Snapshot not found" in result.reason
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("relay.pipeline.SnapshotStore")
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_pipeline_rollback_restores_previous_envelope(
        self, mock_next, mock_initial, mock_store_cls
    ):
        temp_dir = tempfile.mkdtemp()
        try:
            env1 = create_mock_envelope(1, "", {"entities": ["entity1"], "data": "initial"})
            mock_store = MagicMock()
            mock_store.save_snapshot.return_value = Success("snapshot-id")
            mock_store.load_snapshot.return_value = Success(env1)
            mock_store_cls.return_value = mock_store

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            mock_initial.return_value = Success(create_mock_envelope(1, pipeline._pipeline_id, {"entities": ["entity1"], "data": "initial"}))
            mock_next.return_value = Success(create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"}))

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            pipeline.execute_step({"data": "next"})
            result = pipeline.rollback()

            assert isinstance(result, Success)
            assert result.value.step == 1
            assert result.value.payload == {"entities": ["entity1"], "data": "initial"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineGetCurrentEnvelope:
    def test_pipeline_get_current_envelope_returns_none_initially(self, pipeline):
        result = pipeline.get_current_envelope()
        assert result is None

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    def test_pipeline_get_current_envelope_returns_current_after_step(
        self, mock_initial, pipeline
    ):
        mock_initial.return_value = Success(create_mock_envelope(1, pipeline._pipeline_id, {"data": "test"}))

        pipeline.execute_step({"data": "test"})
        result = pipeline.get_current_envelope()

        assert result is not None
        assert result.step == 1
        assert result.payload == {"data": "test"}
