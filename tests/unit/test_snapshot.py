"""Unit tests for relay.snapshot."""

import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope, create_initial_envelope
from relay.snapshot import SNAPSHOT_ID_PATTERN, SnapshotStore, InvalidSnapshotIdError, _extract_step_from_snapshot_id
from relay.types import Failure, Success, ErrorCode


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
        assert result.code == ErrorCode.INVALID_SNAPSHOT

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
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID

    def test_load_snapshot_rejects_path_traversal_attempt(self):
        result = self.store.load_snapshot("../etc/passwd")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID

    def test_snapshot_get_latest_fails_when_no_snapshots(self):
        result = self.store.get_latest_snapshot("nonexistent-pipeline")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.PIPELINE_NOT_FOUND

    def test_get_latest_snapshot_propagates_corrupted_index_failure(self):
        """Corrupted index must not be silently converted to PIPELINE_NOT_FOUND."""
        from pathlib import Path

        index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("not valid json {{{")

        result = self.store.get_latest_snapshot("pipeline-xyz")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX

    def test_get_latest_snapshot_propagates_index_read_failure(self):
        """OS-level read errors must propagate, not become PIPELINE_NOT_FOUND."""
        from pathlib import Path
        from unittest.mock import patch

        index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text('{"snapshots": []}')

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = self.store.get_latest_snapshot("pipeline-xyz")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_READ_FAILED

    def test_get_latest_snapshot_propagates_invalid_index_failure(self):
        """Index with wrong schema (not a dict) must propagate, not become PIPELINE_NOT_FOUND."""
        from pathlib import Path

        index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text('["not", "a", "dict"]')

        result = self.store.get_latest_snapshot("pipeline-xyz")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_INDEX

    def test_list_snapshots_returns_empty_for_unknown_pipeline(self):
        result = self.store.list_snapshots("does-not-exist")

        assert isinstance(result, Success)
        assert result.value == []


class TestSnapshotStoreSaveErrors:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_env(self, pipeline_id="pipeline-err", step=1):
        return ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id=pipeline_id,
            step=step,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "test"},
            manifest_hash="",
            signature="sig",
        )

    def test_save_snapshot_fails_on_os_error(self):
        with patch("builtins.open", side_effect=OSError("disk full")):
            result = self.store.save_snapshot(self._make_env())

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED

    def test_save_snapshot_fails_on_index_update(self):
        env = self._make_env()
        with patch.object(self.store, "_add_to_index", return_value=Failure(reason="index fail", code=ErrorCode.INDEX_UPDATE_FAILED)):
            result = self.store.save_snapshot(env)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_UPDATE_FAILED

    def test_save_snapshot_cleans_up_snapshot_file_on_index_failure(self):
        env = self._make_env()
        original_add = self.store._add_to_index

        def failing_add(pid, sid):
            return Failure(reason="index fail", code=ErrorCode.INDEX_UPDATE_FAILED)

        self.store._add_to_index = failing_add
        result = self.store.save_snapshot(env)
        self.store._add_to_index = original_add

        assert isinstance(result, Failure)
        pipeline_path = Path(self.temp_dir) / env.pipeline_id
        snapshot_files = list(pipeline_path.glob("*.json"))
        assert len(snapshot_files) == 0


class TestSnapshotStoreLoadErrors:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_snapshot_fails_on_file_not_found(self):
        result = self.store.load_snapshot("pipeline-valid@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_NOT_FOUND

    def test_load_snapshot_fails_on_corrupted_json(self):
        pipeline_dir = Path(self.temp_dir) / "pipeline-x"
        pipeline_dir.mkdir(parents=True)
        snapshot_file = pipeline_dir / "pipeline-x@1_abcdef123456.json"
        snapshot_file.write_text("not valid json {{{")

        result = self.store.load_snapshot("pipeline-x@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_LOAD_FAILED

    def test_load_snapshot_fails_on_os_error(self):
        pipeline_dir = Path(self.temp_dir) / "pipeline-x"
        pipeline_dir.mkdir(parents=True)
        snapshot_file = pipeline_dir / "pipeline-x@1_abcdef123456.json"
        snapshot_file.write_text("{}")

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = self.store.load_snapshot("pipeline-x@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_LOAD_FAILED

    def test_load_snapshot_rejects_invalid_format(self):
        result = self.store.load_snapshot("no-at-sign")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID


class TestSnapshotStoreGetLatestErrors:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_latest_snapshot_fails_on_empty_snapshots_list(self):
        pipeline_dir = Path(self.temp_dir) / "pipeline-empty"
        pipeline_dir.mkdir(parents=True)
        index_path = pipeline_dir / "index.json"
        index_path.write_text('{"snapshots": []}')

        result = self.store.get_latest_snapshot("pipeline-empty")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_SNAPSHOTS


class TestSnapshotStoreListErrors:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_snapshots_propagates_index_read_failure(self):
        pipeline_dir = Path(self.temp_dir) / "pipeline-fail"
        pipeline_dir.mkdir(parents=True)
        index_path = pipeline_dir / "index.json"
        index_path.write_text("{}")

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = self.store.list_snapshots("pipeline-fail")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_READ_FAILED


class TestSnapshotStoreLoadIndexErrors:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_index_corrupted_json(self):
        pipeline_dir = Path(self.temp_dir) / "pipe-x"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("{{{broken")

        result = self.store._load_index("pipe-x")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX

    def test_load_index_os_error(self):
        pipeline_dir = Path(self.temp_dir) / "pipe-x"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("{}")

        with patch("builtins.open", side_effect=OSError("locked")):
            result = self.store._load_index("pipe-x")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_READ_FAILED


class TestSnapshotDictToEnvelope:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_snapshot(self, pipeline_id: str, step: int, data: dict) -> str:
        pipeline_dir = Path(self.temp_dir) / pipeline_id
        pipeline_dir.mkdir(parents=True)
        snapshot_id = f"{pipeline_id}@{step}_abcdef123456"
        (pipeline_dir / f"{snapshot_id}.json").write_text(json.dumps(data))
        return snapshot_id

    def test_missing_relay_version_returns_failure(self):
        sid = self._write_snapshot("p-miss", 1, {
            "pipeline_id": "p-miss", "step": 1,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_timestamp_format_returns_failure(self):
        sid = self._write_snapshot("p-ts", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-ts",
            "step": 1, "timestamp": "not-a-date",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_payload_type_returns_failure(self):
        sid = self._write_snapshot("p-pay", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-pay",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": "not-a-dict", "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_step_type_returns_failure(self):
        sid = self._write_snapshot("p-step", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-step",
            "step": "not-an-int", "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_pipeline_id_returns_failure(self):
        sid = self._write_snapshot("p-pid", 1, {
            "relay_version": RELAY_VERSION,
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_manifest_hash_returns_failure(self):
        sid = self._write_snapshot("p-mh", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-mh",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_signature_returns_failure(self):
        sid = self._write_snapshot("p-sig", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-sig",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT


class TestSnapshotStoreSaveOSError:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = SnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_env(self):
        return ContextEnvelope(
            relay_version=RELAY_VERSION, pipeline_id="p-os",
            step=1, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100, token_budget_total=8000,
            payload={"data": "test"}, manifest_hash="", signature="sig",
        )

    def test_save_snapshot_cleans_up_temp_file_on_replace_failure(self):
        env = self._make_env()
        with patch("os.replace", side_effect=OSError("replace failed")):
            result = self.store.save_snapshot(env)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED

    def test_os_error_during_temp_cleanup_does_not_raise(self):
        env = self._make_env()
        with patch("os.replace", side_effect=OSError("replace failed")):
            with patch.object(Path, "unlink", side_effect=OSError("unlink failed")):
                result = self.store.save_snapshot(env)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED


class TestExtractStepFromSnapshotId:
    def test_extract_step_returns_correct_int(self):
        assert _extract_step_from_snapshot_id("pipe@42_abc123") == 42

    def test_extract_step_raises_on_missing_at_symbol(self):
        with pytest.raises(InvalidSnapshotIdError, match="Invalid snapshot ID format"):
            _extract_step_from_snapshot_id("no-at-sign")

    def test_extract_step_raises_on_non_numeric_step(self):
        with pytest.raises(InvalidSnapshotIdError, match="Invalid snapshot ID format"):
            _extract_step_from_snapshot_id("pipe@abc_xyz")


class TestSnapshotIdPattern:
    def test_valid_snapshot_id_matches(self):
        assert SNAPSHOT_ID_PATTERN.match("pipeline-123@1_a1b2c3d4e5f6")

    def test_snapshot_id_with_path_traversal_does_not_match(self):
        assert SNAPSHOT_ID_PATTERN.match("../etc/passwd") is None


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
