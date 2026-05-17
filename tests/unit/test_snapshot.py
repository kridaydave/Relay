"""Unit tests for relay.snapshot."""

import inspect
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope, create_initial_envelope
from relay.snapshot import SNAPSHOT_ID_PATTERN, LocalFileSnapshotStore, InvalidSnapshotIdError, _extract_step_from_snapshot_id
from relay.snapshot_protocol import SnapshotStore
from relay.types import Closeable, Failure, Success, ErrorCode, JSONDict


class TestSnapshotStore:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_envelope(
        self,
        pipeline_id: str = "pipeline-123",
        step: int = 1,
        payload: JSONDict | None = None,
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

    def test_snapshot_saves_envelope_returns_snapshot_id_when_successful(self) -> None:
        envelope = self._create_envelope()

        result = self.store.save_snapshot(envelope)

        assert isinstance(result, Success)
        assert result.value.startswith("pipeline-123@1_")
        assert result.value.endswith(".json") is False

    def test_snapshot_loads_saved_envelope_from_storage_when_requested(self) -> None:
        envelope = self._create_envelope(pipeline_id="pipeline-456", step=2)
        save_result = self.store.save_snapshot(envelope)
        assert isinstance(save_result, Success)
        snapshot_id = save_result.value

        result = self.store.load_snapshot(snapshot_id)

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.pipeline_id == "pipeline-456"

    def test_snapshot_get_latest_returns_most_recent_one(self) -> None:
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

    def test_snapshot_list_snapshots_returns_all_ids_for_pipeline(self) -> None:
        pipeline_id = "pipeline-abc"
        envelope1 = self._create_envelope(pipeline_id=pipeline_id, step=1)
        envelope2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        envelope3 = self._create_envelope(pipeline_id=pipeline_id, step=3)

        s1 = self.store.save_snapshot(envelope1)
        assert isinstance(s1, Success)
        id1 = s1.value
        s2 = self.store.save_snapshot(envelope2)
        assert isinstance(s2, Success)
        id2 = s2.value
        s3 = self.store.save_snapshot(envelope3)
        assert isinstance(s3, Success)
        id3 = s3.value

        result = self.store.list_snapshots(pipeline_id)

        assert isinstance(result, Success)
        assert len(result.value) == 3
        assert id1 in result.value
        assert id2 in result.value
        assert id3 in result.value

    def test_load_snapshot_fails_when_body_step_mismatches_filename(self) -> None:
        """Tampered snapshot where body step differs from filename is rejected."""
        import json
        from pathlib import Path

        env = self._create_envelope(step=1)
        save_result = self.store.save_snapshot(env)
        assert isinstance(save_result, Success)
        snapshot_id = save_result.value

        path = Path(self.temp_dir) / env.pipeline_id / f"{snapshot_id}.json"
        read_data: JSONDict = json.loads(path.read_text())
        read_data["step"] = 99
        path.write_text(json.dumps(read_data))

        result = self.store.load_snapshot(snapshot_id)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_load_snapshot_fails_when_body_pipeline_id_is_invalid(self) -> None:
        """Snapshot where body pipeline_id is malicious is rejected (Issue #1)."""
        import json
        from pathlib import Path

        pipeline_id = "valid-pid"
        env = self._create_envelope(pipeline_id=pipeline_id, step=1)
        save_result = self.store.save_snapshot(env)
        assert isinstance(save_result, Success)
        snapshot_id = save_result.value

        path = Path(self.temp_dir) / pipeline_id / f"{snapshot_id}.json"
        read_data: JSONDict = json.loads(path.read_text())
        read_data["pipeline_id"] = "../../../etc"
        path.write_text(json.dumps(read_data))

        result = self.store.load_snapshot(snapshot_id)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_snapshot_index_sorts_ids_numerically_for_consistency(self) -> None:
        pipeline_id = "pipeline-sort"
        env2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        env10 = self._create_envelope(pipeline_id=pipeline_id, step=10)
        env1 = self._create_envelope(pipeline_id=pipeline_id, step=1)

        self.store.save_snapshot(env2)
        self.store.save_snapshot(env10)
        self.store.save_snapshot(env1)

        result = self.store.list_snapshots(pipeline_id)
        assert isinstance(result, Success)
        assert "pipeline-sort@1_" in result.value[0]
        assert "pipeline-sort@2_" in result.value[1]
        assert "pipeline-sort@10_" in result.value[2]

    def test_snapshot_fails_on_nonexistent_load(self) -> None:
        result = self.store.load_snapshot("nonexistent_id")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID

    def test_load_snapshot_rejects_path_traversal_attempt_when_called(self) -> None:
        result = self.store.load_snapshot("../etc/passwd")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID

    def test_snapshot_get_latest_fails_when_no_snapshots(self) -> None:
        result = self.store.get_latest_snapshot("nonexistent-pipeline")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.PIPELINE_NOT_FOUND

    def test_get_latest_snapshot_propagates_corrupted_index_failure_returns_error(self) -> None:
        """Corrupted index must not be silently converted to PIPELINE_NOT_FOUND."""
        from pathlib import Path

        index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("not valid json {{{")

        result = self.store.get_latest_snapshot("pipeline-xyz")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX

    def test_get_latest_snapshot_propagates_index_read_failure_returns_error(self) -> None:
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

    def test_get_latest_snapshot_propagates_invalid_index_failure_returns_error(self) -> None:
        """Index with wrong schema (not a dict) must propagate, not become PIPELINE_NOT_FOUND."""
        from pathlib import Path

        index_path = Path(self.temp_dir) / "pipeline-xyz" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text('["not", "a", "dict"]')

        result = self.store.get_latest_snapshot("pipeline-xyz")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_INDEX

    def test_list_snapshots_fails_on_invalid_index_format(self) -> None:
        """Index with wrong schema (not a dict) returns INVALID_INDEX."""
        pipeline_dir = Path(self.temp_dir) / "invalid-index"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text('["not", "a", "dict"]')

        result = self.store.list_snapshots("invalid-index")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_INDEX

    def test_list_snapshots_returns_empty_for_unknown_pipeline(self) -> None:
        result = self.store.list_snapshots("does-not-exist")

        assert isinstance(result, Success)
        assert result.value == []


class TestSnapshotStoreSaveErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_env(
        self, pipeline_id: str = "pipeline-err", step: int = 1
    ) -> ContextEnvelope:
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

    def test_save_snapshot_fails_on_os_error(self) -> None:
        with patch("builtins.open", side_effect=OSError("disk full")):
            result = self.store.save_snapshot(self._make_env())

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED

    def test_save_snapshot_fails_on_index_update(self) -> None:
        env = self._make_env()
        with patch.object(self.store, "_add_to_index", return_value=Failure(reason="index fail", code=ErrorCode.INDEX_UPDATE_FAILED)):
            result = self.store.save_snapshot(env)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_UPDATE_FAILED

    def test_save_snapshot_cleans_up_snapshot_file_on_index_failure(self) -> None:
        env = self._make_env()
        with patch.object(self.store, "_add_to_index", return_value=Failure(
            reason="index fail", code=ErrorCode.INDEX_UPDATE_FAILED,
        )):
            result = self.store.save_snapshot(env)

        assert isinstance(result, Failure)
        pipeline_path = Path(self.temp_dir) / env.pipeline_id
        snapshot_files = list(pipeline_path.glob("*.json"))
        assert len(snapshot_files) == 0


class TestSnapshotStoreLoadErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_snapshot_fails_on_file_not_found(self) -> None:
        result = self.store.load_snapshot("pipeline-valid@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_NOT_FOUND

    def test_load_snapshot_fails_on_corrupted_json(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipeline-x"
        pipeline_dir.mkdir(parents=True)
        snapshot_file = pipeline_dir / "pipeline-x@1_abcdef123456.json"
        snapshot_file.write_text("not valid json {{{")

        result = self.store.load_snapshot("pipeline-x@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_LOAD_FAILED

    def test_load_snapshot_fails_on_os_error(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipeline-x"
        pipeline_dir.mkdir(parents=True)
        snapshot_file = pipeline_dir / "pipeline-x@1_abcdef123456.json"
        snapshot_file.write_text("{}")

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = self.store.load_snapshot("pipeline-x@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_LOAD_FAILED

    def test_load_snapshot_fails_on_invalid_format(self) -> None:
        result = self.store.load_snapshot("no-at-sign")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID


class TestSnapshotStoreGetLatestErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_latest_snapshot_fails_on_empty_snapshots_list(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipeline-empty"
        pipeline_dir.mkdir(parents=True)
        index_path = pipeline_dir / "index.json"
        index_path.write_text('{"snapshots": []}')

        result = self.store.get_latest_snapshot("pipeline-empty")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_SNAPSHOTS


class TestSnapshotStoreListErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_snapshots_fails_when_index_read_propagates_failure(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipeline-fail"
        pipeline_dir.mkdir(parents=True)
        index_path = pipeline_dir / "index.json"
        index_path.write_text("{}")

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = self.store.list_snapshots("pipeline-fail")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_READ_FAILED

    def test_list_snapshots_fails_on_corrupted_index(self) -> None:
        """Corrupted index JSON returns CORRUPTED_INDEX."""
        pipeline_dir = Path(self.temp_dir) / "corrupted-index"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("not valid json {{{")

        result = self.store.list_snapshots("corrupted-index")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX


class TestSnapshotStoreLoadIndexErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_index_fails_on_corrupted_json(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipe-x"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("{{{broken")

        result = self.store._load_index("pipe-x")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX

    def test_load_index_fails_on_os_error(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipe-x"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("{}")

        with patch("builtins.open", side_effect=OSError("locked")):
            result = self.store._load_index("pipe-x")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_READ_FAILED

    def test_load_index_fails_when_index_not_found(self) -> None:
        pipeline_dir = Path(self.temp_dir) / "pipe-x"
        pipeline_dir.mkdir(parents=True)

        result = self.store._load_index("pipe-x")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_NOT_FOUND

class TestSnapshotStoreAddIndexErrors:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_to_index_fails_on_corrupted_json(self) -> None:
        """If index JSON is corrupted, _add_to_index should return CORRUPTED_INDEX."""
        pipeline_id = "pipe-corrupt"
        pipeline_dir = Path(self.temp_dir) / pipeline_id
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "index.json").write_text("{{{broken")

        result = self.store._add_to_index(pipeline_id, "some-id")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.CORRUPTED_INDEX

    def test_add_to_index_fails_on_write_os_error(self) -> None:
        """If index write fails, it returns INDEX_UPDATE_FAILED."""
        pipeline_id = "pipe-os"
        pipeline_dir = Path(self.temp_dir) / pipeline_id
        pipeline_dir.mkdir(parents=True)

        valid_snapshot_id = f"{pipeline_id}@1_abcdef123456"

        with patch("builtins.open", side_effect=OSError("disk full")):
            result = self.store._add_to_index(pipeline_id, valid_snapshot_id)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INDEX_UPDATE_FAILED


class TestSnapshotDictToEnvelope:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_snapshot(self, pipeline_id: str, step: int, data: dict[str, object]) -> str:
        pipeline_dir = Path(self.temp_dir) / pipeline_id
        pipeline_dir.mkdir(parents=True)
        snapshot_id = f"{pipeline_id}@{step}_abcdef123456"
        (pipeline_dir / f"{snapshot_id}.json").write_text(json.dumps(data))
        return snapshot_id

    def test_missing_relay_version_returns_failure(self) -> None:
        sid = self._write_snapshot("p-miss", 1, {
            "pipeline_id": "p-miss", "step": 1,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_timestamp_format_returns_failure(self) -> None:
        sid = self._write_snapshot("p-ts", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-ts",
            "step": 1, "timestamp": "not-a-date",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_payload_type_returns_failure(self) -> None:
        sid = self._write_snapshot("p-pay", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-pay",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": "not-a-dict", "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_invalid_step_type_returns_failure(self) -> None:
        sid = self._write_snapshot("p-step", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-step",
            "step": "not-an-int", "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_pipeline_id_returns_failure(self) -> None:
        sid = self._write_snapshot("p-pid", 1, {
            "relay_version": RELAY_VERSION,
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_manifest_hash_returns_failure(self) -> None:
        sid = self._write_snapshot("p-mh", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-mh",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "signature": "s",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_missing_signature_returns_failure(self) -> None:
        sid = self._write_snapshot("p-sig", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-sig",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_corrupted_fork_count_type_returns_failure(self) -> None:
        """Fork metadata with wrong types must be caught by _dict_to_envelope."""
        sid = self._write_snapshot("p-fork", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-fork",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
            "fork_id": "uuid-1", "join_strategy": "UNION",
            "fork_count": "not-an-int", "forks_succeeded": 2,
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT

    def test_corrupted_forks_succeeded_type_returns_failure(self) -> None:
        sid = self._write_snapshot("p-fs", 1, {
            "relay_version": RELAY_VERSION, "pipeline_id": "p-fs",
            "step": 1, "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100, "token_budget_total": 8000,
            "payload": {"k": "v"}, "manifest_hash": "", "signature": "s",
            "fork_id": "uuid-2", "join_strategy": "VOTE",
            "fork_count": 3, "forks_succeeded": "wrong",
        })
        result = self.store.load_snapshot(sid)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT


class TestSnapshotStoreSaveOSError:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalFileSnapshotStore(storage_path=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_env(self) -> ContextEnvelope:
        return ContextEnvelope(
            relay_version=RELAY_VERSION, pipeline_id="p-os",
            step=1, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100, token_budget_total=8000,
            payload={"data": "test"}, manifest_hash="", signature="sig",
        )

    def test_save_snapshot_cleans_up_temp_file_on_replace_failure(self) -> None:
        env = self._make_env()
        with patch("os.replace", side_effect=OSError("replace failed")):
            result = self.store.save_snapshot(env)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED

    def test_os_error_during_temp_cleanup_succeeds_and_does_not_raise(self) -> None:
        env = self._make_env()
        with patch("os.replace", side_effect=OSError("replace failed")):
            with patch.object(Path, "unlink", side_effect=OSError("unlink failed")):
                result = self.store.save_snapshot(env)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED


class TestExtractStepFromSnapshotId:
    def test_extract_step_returns_correct_int(self) -> None:
        assert _extract_step_from_snapshot_id("pipe@42_abc123") == 42

    def test_extract_step_raises_on_missing_at_symbol(self) -> None:
        with pytest.raises(InvalidSnapshotIdError, match="Invalid snapshot ID format"):
            _extract_step_from_snapshot_id("no-at-sign")

    def test_extract_step_raises_on_non_numeric_step(self) -> None:
        with pytest.raises(InvalidSnapshotIdError, match="Invalid snapshot ID format"):
            _extract_step_from_snapshot_id("pipe@abc_xyz")


class TestSnapshotIdPattern:
    def test_valid_snapshot_id_matches_pattern_for_validation(self) -> None:
        assert SNAPSHOT_ID_PATTERN.match("pipeline-123@1_a1b2c3d4e5f6")

    def test_snapshot_id_with_path_traversal_does_not_match(self) -> None:
        assert SNAPSHOT_ID_PATTERN.match("../etc/passwd") is None


class TestPreV04SnapshotCompat:
    def test_loading_snapshot_without_fork_fields_succeeds(self) -> None:
        """Pre-v0.4 snapshot (no fork keys in JSON) loads with fork fields as None."""
        import tempfile
        import shutil
        store = LocalFileSnapshotStore(storage_path=tempfile.mkdtemp())
        snapshot_data: dict[str, object] = {
            "relay_version": "0.3.3",
            "pipeline_id": "test-pipe",
            "step": 1,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "token_budget_used": 100,
            "token_budget_total": 8000,
            "payload": {"data": "x"},
            "manifest_hash": "",
            "signature": "sig",
        }
        result = store._dict_to_envelope(snapshot_data)
        assert isinstance(result, Success)
        env = result.value
        assert env.fork_id is None
        assert env.join_strategy is None
        assert env.fork_count is None
        assert env.forks_succeeded is None

    def test_envelope_to_dict_includes_fork_fields_when_serialized(self) -> None:
        """_envelope_to_dict serializes all four fork fields."""
        import tempfile
        store = LocalFileSnapshotStore(storage_path=tempfile.mkdtemp())
        env = ContextEnvelope(
            relay_version=RELAY_VERSION, pipeline_id="test", step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100, token_budget_total=8000,
            payload={"data": "x"}, manifest_hash="", signature="sig",
            fork_id="uuid-1", join_strategy="UNION",
            fork_count=2, forks_succeeded=2,
        )
        d = store._envelope_to_dict(env)
        assert d["fork_id"] == "uuid-1"
        assert d["join_strategy"] == "UNION"
        assert d["fork_count"] == 2
        assert d["forks_succeeded"] == 2

    def test_roundtrip_envelope_with_fork_fields(self) -> None:
        """Save and load envelope with fork fields preserves all values."""
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp()
        try:
            store = LocalFileSnapshotStore(storage_path=tmp)
            env = ContextEnvelope(
                relay_version=RELAY_VERSION, pipeline_id="test", step=2,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=200, token_budget_total=8000,
                payload={"data": "y"}, manifest_hash="hash", signature="sig",
                fork_id="uuid-2", join_strategy="VOTE",
                fork_count=3, forks_succeeded=1,
            )
            save_result = store.save_snapshot(env)
            assert isinstance(save_result, Success)
            load_result = store.load_snapshot(save_result.value)
            assert isinstance(load_result, Success)
            loaded = load_result.value
            assert loaded.fork_id == "uuid-2"
            assert loaded.join_strategy == "VOTE"
            assert loaded.fork_count == 3
            assert loaded.forks_succeeded == 1
            assert loaded.step == 2
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSnapshotStoreProtocol:
    """Tests that SnapshotStore Protocol contract is satisfied by LocalFileSnapshotStore."""

    def test_snapshot_store_is_runtime_checkable_when_decorated(self) -> None:
        """SnapshotStore must be a @runtime_checkable Protocol."""
        # @runtime_checkable decorator adds __instancecheck__ to Protocol classes
        assert hasattr(SnapshotStore, "__instancecheck__")

    def test_local_file_snapshot_store_passes_isinstance_check_when_checked_against_snapshot_store_protocol(self) -> None:
        """isinstance(LocalFileSnapshotStore(...), SnapshotStore) must be True."""
        store = LocalFileSnapshotStore(storage_path=tempfile.mkdtemp())
        try:
            assert isinstance(store, SnapshotStore)
        finally:
            try:
                shutil.rmtree(store._storage_path, ignore_errors=True)
            except OSError:
                pass

    def test_local_file_snapshot_store_passes_isinstance_check_when_checked_against_closeable_protocol(self) -> None:
        """LocalFileSnapshotStore must satisfy the Closeable Protocol."""
        store = LocalFileSnapshotStore(storage_path=tempfile.mkdtemp())
        try:
            assert isinstance(store, Closeable)
        finally:
            try:
                shutil.rmtree(store._storage_path, ignore_errors=True)
            except OSError:
                pass

    def test_snapshot_store_protocol_exposes_expected_methods_when_inspected(self) -> None:
        """SnapshotStore Protocol must have exactly the 5 expected methods."""
        expected_methods = {
            "save_snapshot",
            "load_snapshot",
            "get_latest_snapshot",
            "list_snapshots",
            "close",
        }
        protocol_methods = {
            name
            for name, member in inspect.getmembers(SnapshotStore)
            if not name.startswith("_") and callable(member)
        }
        assert expected_methods.issubset(protocol_methods), (
            f"Missing methods: {expected_methods - protocol_methods}"
        )

    def test_local_file_snapshot_store_has_close_method_when_checked(self) -> None:
        """LocalFileSnapshotStore must have a close() method matching Closeable."""
        assert hasattr(LocalFileSnapshotStore, "close")
        assert callable(LocalFileSnapshotStore.close)
