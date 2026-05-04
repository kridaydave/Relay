"""Unit tests for relay.snapshot."""

import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from relay.envelope import ContextEnvelope, RELAY_VERSION, create_initial_envelope
from relay.snapshot import SnapshotStore
from relay.types import Failure, Success


class TestSnapshotStore:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_envelope(
        self,
        pipeline_id: str = "pipeline-123",
        step: int = 1,
        payload: dict = None,
    ) -> ContextEnvelope:
        if payload is None:
            payload = {"data": "test"}
        return ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id=pipeline_id,
            step=step,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload=payload,
            signature="test-signature"
        )

    def test_snapshot_saves_envelope_returns_snapshot_id(self):
        envelope = self._create_envelope()

        result = self.store.save_snapshot(envelope)

        assert isinstance(result, Success)
        assert result.value.startswith("1_")
        assert result.value.endswith(".json") is False

    def test_snapshot_loads_saved_envelope(self):
        envelope = self._create_envelope(pipeline_id="pipeline-456", step=2)
        save_result = self.store.save_snapshot(envelope)
        snapshot_id = save_result.value

        result = self.store.load_snapshot(snapshot_id)

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.pipeline_id == "pipeline-456"

    def test_snapshot_get_latest_returns_most_recent(self):
        pipeline_id = "pipeline-789"
        envelope1 = self._create_envelope(pipeline_id=pipeline_id, step=1)
        envelope2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        envelope3 = self._create_envelope(pipeline_id=pipeline_id, step=3)

        self.store.save_snapshot(envelope1)
        self.store.save_snapshot(envelope2)
        self.store.save_snapshot(envelope3)

        result = self.store.get_latest_snapshot(pipeline_id)

        assert isinstance(result, Success)
        assert result.value.step == 3

    def test_snapshot_list_snapshots_returns_all_ids(self):
        pipeline_id = "pipeline-abc"
        envelope1 = self._create_envelope(pipeline_id=pipeline_id, step=1)
        envelope2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        envelope3 = self._create_envelope(pipeline_id=pipeline_id, step=3)

        self.store.save_snapshot(envelope1)
        self.store.save_snapshot(envelope2)
        self.store.save_snapshot(envelope3)

        result = self.store.list_snapshots(pipeline_id)

        assert isinstance(result, Success)
        assert len(result.value) == 3

    def test_snapshot_fails_on_nonexistent_load(self):
        result = self.store.load_snapshot("nonexistent_id")

        assert isinstance(result, Failure)
        assert result.code == "INVALID_SNAPSHOT_ID"

    def test_snapshot_get_latest_fails_when_no_snapshots(self):
        result = self.store.get_latest_snapshot("nonexistent-pipeline")

        assert isinstance(result, Failure)
        assert result.code == "PIPELINE_NOT_FOUND"