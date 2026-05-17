"""Unit tests for relay.snapshot_in_memory."""

from datetime import datetime, timezone

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.snapshot_in_memory import InMemorySnapshotStore
from relay.snapshot_protocol import SnapshotStore
from relay.types import Closeable, ErrorCode, Failure, JSONDict, Success


class TestInMemorySnapshotStore:
    def setup_method(self) -> None:
        self.store = InMemorySnapshotStore()

    def teardown_method(self) -> None:
        self.store.close()

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

    # --- Protocol satisfaction tests ---

    def test_in_memory_store_satisfies_snapshot_store_protocol(self) -> None:
        """InMemorySnapshotStore must satisfy the SnapshotStore Protocol."""
        assert isinstance(self.store, SnapshotStore)

    def test_in_memory_store_satisfies_closeable_protocol(self) -> None:
        """InMemorySnapshotStore must satisfy the Closeable Protocol."""
        assert isinstance(self.store, Closeable)

    # --- Happy path tests ---

    def test_save_snapshot_returns_snapshot_id(self) -> None:
        """Save returns a valid snapshot ID in pipeline_id@step_hex format."""
        envelope = self._create_envelope()
        result = self.store.save_snapshot(envelope)

        assert isinstance(result, Success)
        snapshot_id = result.value
        assert snapshot_id.startswith("pipeline-123@1_")
        assert "@" in snapshot_id
        parts = snapshot_id.split("@")[1].split("_")
        assert len(parts) == 2
        assert len(parts[1]) == 12

    def test_load_snapshot_returns_saved_envelope(self) -> None:
        """Saved envelope can be loaded by its snapshot ID with correct fields."""
        envelope = self._create_envelope(pipeline_id="pipeline-456", step=2)
        save_result = self.store.save_snapshot(envelope)
        assert isinstance(save_result, Success)
        snapshot_id = save_result.value

        result = self.store.load_snapshot(snapshot_id)

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.pipeline_id == "pipeline-456"
        assert result.value.payload == {"data": "test"}

    def test_get_latest_snapshot_returns_most_recent(self) -> None:
        """get_latest_snapshot returns the highest step snapshot."""
        pipeline_id = "pipeline-789"
        env1 = self._create_envelope(pipeline_id=pipeline_id, step=1)
        env2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        env3 = self._create_envelope(pipeline_id=pipeline_id, step=3)

        self.store.save_snapshot(env1)
        self.store.save_snapshot(env2)
        self.store.save_snapshot(env3)

        result = self.store.get_latest_snapshot(pipeline_id)

        assert isinstance(result, Success)
        assert result.value.step == 3

    def test_list_snapshots_returns_all_ids(self) -> None:
        """list_snapshots returns all saved snapshot IDs for a pipeline."""
        pipeline_id = "pipeline-abc"
        env1 = self._create_envelope(pipeline_id=pipeline_id, step=1)
        env2 = self._create_envelope(pipeline_id=pipeline_id, step=2)
        env3 = self._create_envelope(pipeline_id=pipeline_id, step=3)

        s1 = self.store.save_snapshot(env1)
        assert isinstance(s1, Success)
        id1 = s1.value
        s2 = self.store.save_snapshot(env2)
        assert isinstance(s2, Success)
        id2 = s2.value
        s3 = self.store.save_snapshot(env3)
        assert isinstance(s3, Success)
        id3 = s3.value

        result = self.store.list_snapshots(pipeline_id)

        assert isinstance(result, Success)
        assert len(result.value) == 3
        assert id1 in result.value
        assert id2 in result.value
        assert id3 in result.value

    def test_list_snapshots_sorts_by_step(self) -> None:
        """list_snapshots returns IDs sorted numerically by step."""
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

    def test_save_and_load_multiple_pipelines_independently(self) -> None:
        """Snapshots for different pipelines do not interfere."""
        env_a = self._create_envelope(pipeline_id="pipe-a", step=1)
        env_b = self._create_envelope(pipeline_id="pipe-b", step=1)

        save_a = self.store.save_snapshot(env_a)
        assert isinstance(save_a, Success)
        save_b = self.store.save_snapshot(env_b)
        assert isinstance(save_b, Success)

        list_a = self.store.list_snapshots("pipe-a")
        assert isinstance(list_a, Success)
        assert len(list_a.value) == 1
        assert list_a.value[0] == save_a.value

        list_b = self.store.list_snapshots("pipe-b")
        assert isinstance(list_b, Success)
        assert len(list_b.value) == 1
        assert list_b.value[0] == save_b.value

    # --- Error path tests ---

    def test_save_snapshot_fails_on_invalid_pipeline_id(self) -> None:
        """save_snapshot returns INVALID_PIPELINE_ID for empty pipeline_id."""
        envelope = self._create_envelope(pipeline_id="")
        result = self.store.save_snapshot(envelope)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_load_snapshot_fails_on_invalid_snapshot_id(self) -> None:
        """load_snapshot returns INVALID_SNAPSHOT_ID for malformed ID."""
        result = self.store.load_snapshot("not-a-valid-id")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_SNAPSHOT_ID

    def test_load_snapshot_fails_on_not_found(self) -> None:
        """load_snapshot returns SNAPSHOT_NOT_FOUND for unknown but valid ID."""
        result = self.store.load_snapshot("valid-pipe@1_abcdef123456")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.SNAPSHOT_NOT_FOUND

    def test_get_latest_snapshot_fails_on_no_snapshots(self) -> None:
        """get_latest_snapshot returns NO_SNAPSHOTS when index entry is empty."""
        pipeline_id = "pipe-empty"
        self.store._index[pipeline_id] = []

        result = self.store.get_latest_snapshot(pipeline_id)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_SNAPSHOTS

    def test_get_latest_snapshot_fails_on_pipeline_not_found(self) -> None:
        """get_latest_snapshot returns PIPELINE_NOT_FOUND for unknown pipeline."""
        result = self.store.get_latest_snapshot("nonexistent")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.PIPELINE_NOT_FOUND

    # --- Close tests ---

    def test_close_clears_all_data(self) -> None:
        """close() clears all stored snapshots and index entries."""
        envelope = self._create_envelope()
        self.store.save_snapshot(envelope)

        self.store.close()

        assert len(self.store._snapshots) == 0
        assert len(self.store._index) == 0

    def test_close_is_idempotent(self) -> None:
        """Calling close() multiple times does not raise errors."""
        self.store.close()
        self.store.close()

    def test_closed_store_returns_pipeline_not_found(self) -> None:
        """After close, get_latest_snapshot returns PIPELINE_NOT_FOUND."""
        envelope = self._create_envelope()
        self.store.save_snapshot(envelope)
        self.store.close()

        result = self.store.get_latest_snapshot("pipeline-123")

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.PIPELINE_NOT_FOUND
