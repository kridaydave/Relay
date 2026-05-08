"""Unit tests for relay.pipeline_snapshot."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.pipeline_snapshot import SnapshotManager
from relay.types import Failure, Success


def create_mock_envelope(step: int, pipeline_id: str = "test-pipeline") -> ContextEnvelope:
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload={"step": step},
        manifest_hash="",
        signature=f"sig{step}",
    )


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def snapshot_manager(mock_store):
    return SnapshotManager(mock_store)


class TestSave:
    def test_saves_snapshot(self, snapshot_manager, mock_store):
        mock_store.save_snapshot.return_value = Success("snapshot-abc")
        env = create_mock_envelope(1)

        result = snapshot_manager.save(env)

        assert isinstance(result, Success)
        assert result.value == "snapshot-abc"
        mock_store.save_snapshot.assert_called_once_with(env)

    def test_propagates_failure(self, snapshot_manager, mock_store):
        mock_store.save_snapshot.return_value = Failure(reason="IO error", code="IO_ERROR")
        env = create_mock_envelope(1)

        result = snapshot_manager.save(env)

        assert isinstance(result, Failure)
        assert result.code == "IO_ERROR"


class TestLoad:
    def test_loads_envelope_from_snapshot_id(self, snapshot_manager, mock_store):
        mock_store.load_snapshot.return_value = Success(create_mock_envelope(1))

        result = snapshot_manager.load("snapshot-abc")

        assert isinstance(result, Success)
        mock_store.load_snapshot.assert_called_once_with("snapshot-abc")

    def test_propagates_failure_when_not_found(self, snapshot_manager, mock_store):
        mock_store.load_snapshot.return_value = Failure(reason="Not found", code="SNAPSHOT_NOT_FOUND")

        result = snapshot_manager.load("nonexistent")

        assert isinstance(result, Failure)
        assert result.code == "SNAPSHOT_NOT_FOUND"