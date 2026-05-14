"""Unit tests for relay.snapshot."""

import shutil
import tempfile
from datetime import datetime, timezone

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope, create_initial_envelope
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
        payload: dict | None = None,
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
            manifest_hash="",
            signature="test-signature",
        )

    def test_snapshot_saves_envelope_returns_snapshot_id(self):
        envelope = self._create_envelope()

        result = self.store.save_snapshot(envelope)

        assert isinstance(result, Success)
        assert result.value.startswith("pipeline-123@1_")
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

        id1 = self.store.save_snapshot(envelope1).value
        id2 = self.store.save_snapshot(envelope2).value
        id3 = self.store.save_snapshot(envelope3).value

        result = self.store.list_snapshots(pipeline_id)

        assert isinstance(result, Success)
        assert len(result.value) == 3
        assert id1 in result.value
        assert id2 in result.value
        assert id3 in result.value

    def test_load_snapshot_fails_when_body_step_mismatches_filename(self):
        """Tampered snapshot where body step differs from filename is rejected."""
        import json
        from pathlib import Path

        env = self._create_envelope(step=1)
        snapshot_id = self.store.save_snapshot(env).value

        path = Path(self.temp_dir) / env.pipeline_id / f"{snapshot_id}.json"
        data = json.loads(path.read_text())
        data["step"] = 99
        path.write_text(json.dumps(data))

        result = self.store.load_snapshot(snapshot_id)
        assert isinstance(result, Failure)
        assert result.code == "INVALID_SNAPSHOT"

    def test_snapshot_index_sorts_numerically(self):
        pipeline_id = "pipeline-sort"
        # Create envelopes in arbitrary order, but their steps matter
        env2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        env10 = self._create_envelope(pipeline_id=pipeline_id, step=10)
        env1 = self._create_envelope(pipeline_id=pipeline_id, step=1)

        self.store.save_snapshot(env2)
        self.store.save_snapshot(env10)
        self.store.save_snapshot(env1)

        result = self.store.list_snapshots(pipeline_id)
        assert isinstance(result, Success)
        # Should be sorted 1, 2, 10
        assert "pipeline-sort@1_" in result.value[0]
        assert "pipeline-sort@2_" in result.value[1]
        assert "pipeline-sort@10_" in result.value[2]

    def test_snapshot_fails_on_nonexistent_load(self):
        result = self.store.load_snapshot("nonexistent_id")

        assert isinstance(result, Failure)
        assert result.code == "INVALID_SNAPSHOT_ID"

    def test_load_snapshot_rejects_path_traversal_attempt(self):
        result = self.store.load_snapshot("../etc/passwd")

        assert isinstance(result, Failure)
        assert result.code == "INVALID_SNAPSHOT_ID"

    def test_snapshot_get_latest_fails_when_no_snapshots(self):
        result = self.store.get_latest_snapshot("nonexistent-pipeline")

        assert isinstance(result, Failure)
        assert result.code == "PIPELINE_NOT_FOUND"

    def test_list_snapshots_returns_empty_for_unknown_pipeline(self):
        result = self.store.list_snapshots("does-not-exist")

        assert isinstance(result, Success)
        assert result.value == []


class TestContextEnvelope:
    def test_context_envelope_is_frozen_dataclass(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test-pipeline",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"key": "value"},
            manifest_hash="",
            signature="sig-123",
        )

        assert envelope.pipeline_id == "test-pipeline"
        assert envelope.step == 1
        assert envelope.signature == "sig-123"

        with pytest.raises(Exception):
            envelope.pipeline_id = "changed"
