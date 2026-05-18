"""Unit tests for relay.pipeline_rollback."""

from typing import cast
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.pipeline_rollback import RollbackHandler
from relay.snapshot_protocol import SnapshotStore
from relay.types import Failure, RollbackSuccess, Success, ErrorCode, JSONDict


def create_mock_envelope(step: int, pipeline_id: str = "test-pipeline") -> ContextEnvelope:
    payload: JSONDict = {"step": step}
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload=payload,
        manifest_hash="",
        signature=f"sig{step}",
    )


@pytest.fixture  # type: ignore[misc]
def rollback_handler() -> RollbackHandler:
    return RollbackHandler()


class TestRestoreToPrevious:
    def test_restore_succeeds_when_envelope_is_in_snapshot(self, rollback_handler: RollbackHandler) -> None:
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)
        mock_store.load_snapshot.return_value = Success[ContextEnvelope](env1)  # type: ignore[misc]

        snapshot_ids: dict[int, str] = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, cast(SnapshotStore, mock_store), "Test rollback")

        assert isinstance(result, RollbackSuccess)
        assert result.value == env1
        assert result.reason == "Test rollback"
        cast(MagicMock, mock_store.load_snapshot).assert_called_once_with("snapshot-1")

    def test_fails_when_no_snapshot_registered(self, rollback_handler: RollbackHandler) -> None:
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)

        snapshot_ids: dict[int, str] = {}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, cast(SnapshotStore, mock_store), "Test rollback")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_SNAPSHOT_REGISTERED
        cast(MagicMock, mock_store.load_snapshot).assert_not_called()

    def test_fails_when_snapshot_load_fails(self, rollback_handler: RollbackHandler) -> None:
        mock_store = MagicMock()
        mock_store.load_snapshot.return_value = Failure(reason="Disk error", code=ErrorCode.UNKNOWN_ERROR)  # type: ignore[misc]
        env1 = create_mock_envelope(1)

        snapshot_ids: dict[int, str] = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(env1, snapshot_ids, cast(SnapshotStore, mock_store), "Test rollback")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.UNKNOWN_ERROR
        cast(MagicMock, mock_store.load_snapshot).assert_called_once_with("snapshot-1")

    def test_rollback_result_contains_reason_when_restored(self, rollback_handler: RollbackHandler) -> None:
        mock_store = MagicMock()
        env1 = create_mock_envelope(1)
        mock_store.load_snapshot.return_value = Success[ContextEnvelope](env1)  # type: ignore[misc]

        snapshot_ids: dict[int, str] = {1: "snapshot-1"}
        result = rollback_handler.restore_to_previous(
            env1, snapshot_ids, cast(SnapshotStore, mock_store), "Contradiction detected: hallucination"
        )

        assert isinstance(result, RollbackSuccess)
        assert result.reason == "Contradiction detected: hallucination"
