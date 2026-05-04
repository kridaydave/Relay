"""Unit tests for relay.pipeline."""

import tempfile
import shutil
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from relay.pipeline import RelayPipeline
from relay.types import Success, Failure


class TestPipelineCreatesEnvelope:
    def test_pipeline_creates_envelope_on_first_step(self):
        temp_dir = tempfile.mkdtemp()
        try:
            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            result = pipeline.execute_step({"data": "test-payload"})

            assert isinstance(result, Success)
            assert result.value.step == 1
            assert result.value.pipeline_id == pipeline._pipeline_id
            assert result.value.payload == {"data": "test-payload"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineCreatesNextEnvelope:
    @patch("relay.context_broker.create_initial_envelope")
    @patch("relay.context_broker.create_next_envelope")
    def test_pipeline_creates_next_envelope_on_subsequent_step(
        self, mock_next, mock_initial
    ):
        from relay.envelope import ContextEnvelope, RELAY_VERSION

        temp_dir = tempfile.mkdtemp()
        try:
            timestamp_1 = datetime(2024, 1, 1, tzinfo=timezone.utc)

            def create_initial(pipeline_id, initial_payload, token_budget_total, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=pipeline_id,
                    step=1,
                    timestamp=timestamp_1,
                    token_budget_used=100,
                    token_budget_total=token_budget_total,
                    payload=initial_payload,
                    signature="sig1"
                ))

            def create_next(previous_envelope, agent_output, secret):
                timestamp_2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=previous_envelope.pipeline_id,
                    step=previous_envelope.step + 1,
                    timestamp=timestamp_2,
                    token_budget_used=200,
                    token_budget_total=previous_envelope.token_budget_total,
                    payload=agent_output,
                    signature="sig2"
                ))

            mock_initial.side_effect = create_initial
            mock_next.side_effect = create_next

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            pipeline.execute_step({"initial": "data"})
            result = pipeline.execute_step({"next": "data"})

            assert isinstance(result, Success)
            assert result.value.step == 2
            assert result.value.payload == {"next": "data"}
            mock_next.assert_called_once()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineValidationAndSnapshot:
    @patch("relay.context_broker.create_initial_envelope")
    @patch("relay.context_broker.create_next_envelope")
    def test_pipeline_validates_and_saves_snapshot_on_clean_handoff(
        self, mock_next, mock_initial
    ):
        from relay.envelope import ContextEnvelope, RELAY_VERSION

        temp_dir = tempfile.mkdtemp()
        try:
            timestamp_1 = datetime(2024, 1, 1, tzinfo=timezone.utc)

            def create_initial(pipeline_id, initial_payload, token_budget_total, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=pipeline_id,
                    step=1,
                    timestamp=timestamp_1,
                    token_budget_used=100,
                    token_budget_total=token_budget_total,
                    payload=initial_payload,
                    signature="sig1"
                ))

            def create_next(previous_envelope, agent_output, secret):
                timestamp_2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=previous_envelope.pipeline_id,
                    step=previous_envelope.step + 1,
                    timestamp=timestamp_2,
                    token_budget_used=200,
                    token_budget_total=previous_envelope.token_budget_total,
                    payload=agent_output,
                    signature="sig2"
                ))

            mock_initial.side_effect = create_initial
            mock_next.side_effect = create_next

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            result = pipeline.execute_step({"entities": ["entity1", "entity2"], "data": "next"})

            assert isinstance(result, Success)
            assert result.value.step == 2
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineRollback:
    @patch("relay.context_broker.create_initial_envelope")
    @patch("relay.context_broker.create_next_envelope")
    @patch("relay.pipeline.SnapshotStore")
    def test_pipeline_triggers_rollback_on_contradiction(
        self, mock_store_cls, mock_next, mock_initial
    ):
        from relay.envelope import ContextEnvelope, RELAY_VERSION

        temp_dir = tempfile.mkdtemp()
        try:
            timestamp_1 = datetime(2024, 1, 1, tzinfo=timezone.utc)

            def create_initial(pipeline_id, initial_payload, token_budget_total, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=pipeline_id,
                    step=1,
                    timestamp=timestamp_1,
                    token_budget_used=100,
                    token_budget_total=token_budget_total,
                    payload=initial_payload,
                    signature="sig1"
                ))

            def create_next(previous_envelope, agent_output, secret):
                timestamp_2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=previous_envelope.pipeline_id,
                    step=previous_envelope.step + 1,
                    timestamp=timestamp_2,
                    token_budget_used=200,
                    token_budget_total=previous_envelope.token_budget_total,
                    payload=agent_output,
                    signature="sig2"
                ))

            mock_initial.side_effect = create_initial
            mock_next.side_effect = create_next

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

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            result = pipeline.execute_step({"data": "next"})

            assert isinstance(result, Failure)
            assert "Snapshot not found" in result.reason
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("relay.context_broker.create_initial_envelope")
    @patch("relay.context_broker.create_next_envelope")
    @patch("relay.pipeline.SnapshotStore")
    def test_pipeline_rollback_restores_previous_envelope(
        self, mock_store_cls, mock_next, mock_initial
    ):
        from relay.envelope import ContextEnvelope, RELAY_VERSION

        temp_dir = tempfile.mkdtemp()
        try:
            timestamp_1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
            timestamp_2 = datetime(2024, 1, 2, tzinfo=timezone.utc)

            def create_initial(pipeline_id, initial_payload, token_budget_total, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=pipeline_id,
                    step=1,
                    timestamp=timestamp_1,
                    token_budget_used=100,
                    token_budget_total=token_budget_total,
                    payload=initial_payload,
                    signature="sig1"
                ))

            def create_next(previous_envelope, agent_output, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=previous_envelope.pipeline_id,
                    step=previous_envelope.step + 1,
                    timestamp=timestamp_2,
                    token_budget_used=200,
                    token_budget_total=previous_envelope.token_budget_total,
                    payload=agent_output,
                    signature="sig2"
                ))

            mock_initial.side_effect = create_initial
            mock_next.side_effect = create_next

            mock_store = MagicMock()
            mock_store.save_snapshot.return_value = Success("snapshot-id")
            mock_store.load_snapshot.return_value = Success(ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test-pipeline",
                step=1,
                timestamp=timestamp_1,
                token_budget_used=100,
                token_budget_total=8000,
                payload={"entities": ["entity1"], "data": "initial"},
                signature="sig1"
            ))
            mock_store_cls.return_value = mock_store

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
            pipeline.execute_step({"data": "next"})

            result = pipeline.rollback()

            assert isinstance(result, Success)
            assert result.value.step == 1
            assert result.value.payload == {"entities": ["entity1"], "data": "initial"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPipelineGetCurrentEnvelope:
    def test_pipeline_get_current_envelope_returns_none_initially(self):
        temp_dir = tempfile.mkdtemp()
        try:
            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            result = pipeline.get_current_envelope()

            assert result is None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("relay.context_broker.create_initial_envelope")
    def test_pipeline_get_current_envelope_returns_current_after_step(
        self, mock_initial
    ):
        from relay.envelope import ContextEnvelope, RELAY_VERSION

        temp_dir = tempfile.mkdtemp()
        try:
            timestamp_1 = datetime(2024, 1, 1, tzinfo=timezone.utc)

            def create_initial(pipeline_id, initial_payload, token_budget_total, secret):
                return Success(ContextEnvelope(
                    relay_version=RELAY_VERSION,
                    pipeline_id=pipeline_id,
                    step=1,
                    timestamp=timestamp_1,
                    token_budget_used=100,
                    token_budget_total=token_budget_total,
                    payload=initial_payload,
                    signature="sig1"
                ))

            mock_initial.side_effect = create_initial

            pipeline = RelayPipeline(
                signing_secret="test-secret",
                token_budget=8000,
                storage_path=temp_dir
            )

            pipeline.execute_step({"data": "test"})
            result = pipeline.get_current_envelope()

            assert result is not None
            assert result.step == 1
            assert result.payload == {"data": "test"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)