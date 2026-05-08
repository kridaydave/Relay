"""Unit tests for relay.pipeline_rollback."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.pipeline_rollback import RollbackHandler
from relay.types import Failure, RollbackSuccess, Success


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
def rollback_handler():
    return RollbackHandler()


class TestRestoreToPrevious:
    def test_restores_envelope_from_snapshot(self, rollback_handler):
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)
        mock_store.load_snapshot.return_value = Success(env1)

        snapshot_ids = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, mock_store, "Test rollback")

        assert isinstance(result, RollbackSuccess)
        assert result.value == env1
        assert result.reason == "Test rollback"
        mock_store.load_snapshot.assert_called_once_with("snapshot-1")

    def test_fails_when_no_snapshot_registered(self, rollback_handler):
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)

        snapshot_ids = {}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, mock_store, "Test rollback")

        assert isinstance(result, Failure)
        assert result.code == "NO_SNAPSHOT_REGISTERED"
        mock_store.load_snapshot.assert_not_called()

    def test_fails_when_snapshot_load_fails(self, rollback_handler):
        mock_store = MagicMock()
        mock_store.load_snapshot.return_value = Failure(reason="Disk error", code="DISK_ERROR")
        env1 = create_mock_envelope(1)

        snapshot_ids = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, mock_store, "Test rollback")

        assert isinstance(result, Failure)
        assert result.code == "DISK_ERROR"
        mock_store.load_snapshot.assert_called_once_with("snapshot-1")

    def test_preserves_reason_in_result(self, rollback_handler):
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)
        mock_store.load_snapshot.return_value = Success(env1)

        snapshot_ids = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(
            env1, snapshot_ids, mock_store, "Contradiction detected: hallucination"
        )

        assert isinstance(result, RollbackSuccess)
        assert result.reason == "Contradiction detected: hallucination"
