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
def snapshot_ids():
    return {}


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def snapshot_manager(mock_store, snapshot_ids):
    return SnapshotManager(mock_store, snapshot_ids)


class TestSaveAndRegister:
    def test_saves_and_registers_snapshot(self, snapshot_manager, mock_store, snapshot_ids):
        mock_store.save_snapshot.return_value = Success("snapshot-abc")
        env = create_mock_envelope(1)

        result = snapshot_manager.save_and_register(env)

        assert isinstance(result, Success)
        assert result.value == "snapshot-abc"
        assert snapshot_ids[1] == "snapshot-abc"
        mock_store.save_snapshot.assert_called_once_with(env)

    def test_propagates_failure(self, snapshot_manager, mock_store, snapshot_ids):
        mock_store.save_snapshot.return_value = Failure(reason="IO error", code="IO_ERROR")
        env = create_mock_envelope(1)

        result = snapshot_manager.save_and_register(env)

        assert isinstance(result, Failure)
        assert result.code == "IO_ERROR"


class TestAdvance:
    def test_saves_new_envelope_and_cleans_up_oldest(self, snapshot_manager, mock_store, snapshot_ids):
        mock_store.save_snapshot.return_value = Success("snapshot-new")
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        snapshot_ids[1] = "old-snapshot"

        result = snapshot_manager.advance(env2, env1)

        assert isinstance(result, Success)
        assert snapshot_ids[2] == "snapshot-new"
        assert 1 not in snapshot_ids

    def test_propagates_failure_on_save(self, snapshot_manager, mock_store, snapshot_ids):
        mock_store.save_snapshot.return_value = Failure(reason="Disk full", code="DISK_FULL")
        env2 = create_mock_envelope(2)
        env1 = create_mock_envelope(1)

        result = snapshot_manager.advance(env2, env1)

        assert isinstance(result, Failure)
        assert result.code == "DISK_FULL"

    def test_no_previous_envelope_skips_cleanup(self, snapshot_manager, mock_store, snapshot_ids):
        mock_store.save_snapshot.return_value = Success("snapshot-new")
        env2 = create_mock_envelope(2)
        snapshot_ids[1] = "keep-this"

        result = snapshot_manager.advance(env2, None)

        assert isinstance(result, Success)
        assert 1 in snapshot_ids


class TestLoad:
    def test_loads_envelope_from_registered_step(self, snapshot_manager, mock_store, snapshot_ids):
        env = create_mock_envelope(1)
        snapshot_ids[1] = "snapshot-1"
        mock_store.load_snapshot.return_value = Success(env)

        result = snapshot_manager.load(1)

        assert isinstance(result, Success)
        assert result.value == env
        mock_store.load_snapshot.assert_called_once_with("snapshot-1")

    def test_fails_when_step_not_registered(self, snapshot_manager, snapshot_ids):
        result = snapshot_manager.load(99)

        assert isinstance(result, Failure)
        assert result.code == "NO_SNAPSHOT_REGISTERED"
