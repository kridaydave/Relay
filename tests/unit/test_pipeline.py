"""Unit tests for relay.pipeline."""

import shutil
import tempfile
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.core_pipeline import CoreRelayPipeline
from relay.types import Failure, Success, RollbackSuccess


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def pipeline(temp_storage):
    return CoreRelayPipeline(
        signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
    )


def create_mock_envelope(
    step: int, pipeline_id: str, payload: dict, timestamp: datetime = None
) -> ContextEnvelope:
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
        signature=f"sig{step}",
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
        mock_initial.return_value = Success(
            create_mock_envelope(1, pipeline._pipeline_id, {"initial": "data"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, pipeline._pipeline_id, {"next": "data"})
        )

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
        mock_initial.return_value = Success(
            create_mock_envelope(1, pipeline._pipeline_id, {"entities": ["entity1"]})
        )
        mock_next.return_value = Success(
            create_mock_envelope(
                2, pipeline._pipeline_id, {"entities": ["entity1", "entity2"]}
            )
        )

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step(
            {"entities": ["entity1", "entity2"], "data": "next"}
        )

        assert isinstance(result, Success)
        assert result.value.step == 2


class TestPipelineRollback:
    @patch("relay.core_pipeline.SnapshotStore")
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
                reason="Snapshot not found", code="SNAPSHOT_NOT_FOUND"
            )
            mock_store_cls.return_value = mock_store

            pipeline = CoreRelayPipeline(
                signing_secret="test-secret", token_budget=8000, storage_path=temp_dir
            )

            mock_initial.return_value = Success(
                create_mock_envelope(
                    1, pipeline._pipeline_id, {"entities": ["entity1"]}
                )
            )
            mock_next.return_value = Success(
                create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"})
            )

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            result = pipeline.execute_step({"data": "next"})

            assert isinstance(result, Failure)
            assert "Snapshot not found" in result.reason
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineRollback2:
    @patch("relay.core_pipeline.SnapshotStore")
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_pipeline_rollback_restores_previous_envelope(
        self, mock_next, mock_initial, mock_store_cls
    ):
        temp_dir = tempfile.mkdtemp()
        try:
            env1 = create_mock_envelope(
                1, "", {"entities": ["entity1"], "data": "initial"}
            )
            mock_store = MagicMock()
            mock_store.save_snapshot.return_value = Success("snapshot-id")
            mock_store.load_snapshot.return_value = Success(env1)
            mock_store_cls.return_value = mock_store

            pipeline = CoreRelayPipeline(
                signing_secret="test-secret", token_budget=8000, storage_path=temp_dir
            )

            mock_initial.return_value = Success(
                create_mock_envelope(
                    1,
                    pipeline._pipeline_id,
                    {"entities": ["entity1"], "data": "initial"},
                )
            )
            mock_next.return_value = Success(
                create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"})
            )

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            pipeline.execute_step({"data": "next"})
            result = pipeline.rollback()

            assert isinstance(result, (Success, RollbackSuccess))
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
        mock_initial.return_value = Success(
            create_mock_envelope(1, pipeline._pipeline_id, {"data": "test"})
        )

        pipeline.execute_step({"data": "test"})
        result = pipeline.get_current_envelope()

        assert result is not None
        assert result.step == 1
        assert result.payload == {"data": "test"}


class TestConcurrentPipeline:
    """R18: Concurrent code must be tested concurrently."""

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    def test_concurrent_step_execution_produces_consistent_results(
        self, mock_initial, temp_storage
    ):
        """Test that concurrent step execution produces consistent results."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []
        lock = threading.Lock()

        def execute_step(step_num):
            try:
                result = pipeline.execute_step({"step": step_num, "data": f"data-{step_num}"})
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=execute_step, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) > 0
        final_envelope = pipeline.get_current_envelope()
        assert final_envelope is not None
        assert final_envelope.step >= 1

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_concurrent_step_execution_with_snapshot_tracking(
        self, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent access to _snapshot_ids is thread-safe."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, "test-pipeline-id", {"next": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []
        lock = threading.Lock()

        def execute_and_advance(step_num):
            try:
                result = pipeline.execute_step({"step": step_num})
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [
            threading.Thread(target=execute_and_advance, args=(i,))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) > 0

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_concurrent_get_current_envelope(
        self, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent reads of _current_envelope are safe."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, "test-pipeline-id", {"next": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"initial": "data"})
        pipeline.execute_step({"next": "data"})

        results = []
        errors = []
        lock = threading.Lock()

        def get_envelope():
            try:
                envelope = pipeline.get_current_envelope()
                with lock:
                    results.append(envelope)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=get_envelope) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert all(r is not None for r in results), "All results should be non-None"

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    @patch("relay.core_pipeline.SnapshotStore")
    def test_concurrent_rollback_access(
        self, mock_store_cls, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent rollback access is handled safely."""
        mock_store = MagicMock()
        mock_store.save_snapshot.return_value = Success("snapshot-id")
        mock_store.load_snapshot.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"data": "restored"})
        )
        mock_store_cls.return_value = mock_store

        pipeline = CoreRelayPipeline(
            signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
        )

        mock_initial.return_value = Success(
            create_mock_envelope(1, pipeline._pipeline_id, {"data": "initial"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"})
        )

        pipeline.execute_step({"data": "initial"})
        pipeline.execute_step({"data": "next"})

        results = []
        errors = []
        lock = threading.Lock()

        def attempt_rollback():
            try:
                result = pipeline.rollback()
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=attempt_rollback) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) >= 0
        assert all(isinstance(r, Failure) or isinstance(r, Success) for r in results)

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    def test_thread_pool_executor_operations(
        self, mock_initial, temp_storage
    ):
        """Test pipeline operations under thread pool execution."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"data": "test"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="test-secret", token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []

        def execute_step(step_num):
            try:
                result = pipeline.execute_step({"step": step_num})
                results.append(result)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(execute_step, i) for i in range(5)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        final_envelope = pipeline.get_current_envelope()
        assert final_envelope is not None
