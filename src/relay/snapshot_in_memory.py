"""In-memory snapshot store for Relay testing and lightweight pipelines.

Owns: in-memory snapshot storage, Protocol compliance verification.
Does NOT: persist data across process restarts, provide transactional guarantees.
"""

import threading
import uuid
from copy import deepcopy

from relay.envelope import PIPELINE_ID_PATTERN, ContextEnvelope
from relay.snapshot_protocol import SNAPSHOT_ID_PATTERN, _extract_step_from_snapshot_id
from relay.types import ErrorCode, Failure, Result, Success

__all__ = ["InMemorySnapshotStore"]


class InMemorySnapshotStore:
    """In-memory snapshot store for testing and lightweight pipelines.

    Owns: in-memory snapshot storage, Protocol compliance verification.
    Does NOT: persist data across process restarts, provide transactional guarantees.
    Thread safety: uses threading.Lock for per-method atomicity but does not provide snapshot-level atomicity across method calls.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory snapshot store."""
        self._lock = threading.Lock()
        self._snapshots: dict[str, dict[str, ContextEnvelope]] = {}
        self._index: dict[str, list[str]] = {}

    def _validate_pipeline_id(self, pipeline_id: str) -> bool:
        """Validate pipeline_id format against PIPELINE_ID_PATTERN."""
        return bool(PIPELINE_ID_PATTERN.match(pipeline_id))

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID.

        Validates pipeline_id at the boundary to defend against manually
        constructed envelopes with invalid or malicious pipeline_ids
        (defense-in-depth per Rule 4.1).

        Maintains a sorted index by step extracted from the snapshot ID.
        """
        pipeline_id = envelope.pipeline_id
        if not pipeline_id or not self._validate_pipeline_id(pipeline_id):
            return Failure(
                reason=f"Invalid pipeline_id: {pipeline_id}",
                code=ErrorCode.INVALID_PIPELINE_ID,
            )

        snapshot_id = f"{pipeline_id}@{envelope.step}_{uuid.uuid4().hex[:12]}"

        with self._lock:
            if pipeline_id not in self._snapshots:
                self._snapshots[pipeline_id] = {}
                self._index[pipeline_id] = []

            self._snapshots[pipeline_id][snapshot_id] = deepcopy(envelope)

            if snapshot_id not in self._index[pipeline_id]:
                self._index[pipeline_id].append(snapshot_id)
                self._index[pipeline_id].sort(key=_extract_step_from_snapshot_id)

        return Success(snapshot_id)

    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by ID."""
        if not SNAPSHOT_ID_PATTERN.match(snapshot_id):
            return Failure(
                reason="Invalid snapshot ID format",
                code=ErrorCode.INVALID_SNAPSHOT_ID,
            )

        pipeline_id, rest = snapshot_id.split("@", 1)
        parts = rest.rsplit("_", 1)
        step = int(parts[0])

        with self._lock:
            pipeline_snapshots = self._snapshots.get(pipeline_id)
            if pipeline_snapshots is None:
                return Failure(
                    reason=f"Snapshot not found: {snapshot_id}",
                    code=ErrorCode.SNAPSHOT_NOT_FOUND,
                )

            envelope = pipeline_snapshots.get(snapshot_id)
            if envelope is None:
                return Failure(
                    reason=f"Snapshot not found: {snapshot_id}",
                    code=ErrorCode.SNAPSHOT_NOT_FOUND,
                )

            if envelope.step != step:
                return Failure(
                    reason=(
                        f"Snapshot integrity error: snapshot ID indicates step {step} "
                        f"but envelope body contains step {envelope.step}"
                    ),
                    code=ErrorCode.INVALID_SNAPSHOT,
                )

            return Success(deepcopy(envelope))

    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
        """Get the most recent snapshot for a pipeline.

        Returns the last entry in the sorted index for the given pipeline.
        """
        with self._lock:
            if pipeline_id not in self._index:
                return Failure(
                    reason=f"No snapshots found for pipeline: {pipeline_id}",
                    code=ErrorCode.PIPELINE_NOT_FOUND,
                )

            index_entries = self._index[pipeline_id]
            if not index_entries:
                return Failure(
                    reason=f"No snapshots found for pipeline: {pipeline_id}",
                    code=ErrorCode.NO_SNAPSHOTS,
                )

            latest_id = index_entries[-1]
            pipeline_snapshots = self._snapshots.get(pipeline_id)
            if pipeline_snapshots is None or latest_id not in pipeline_snapshots:
                return Failure(
                    reason=f"Snapshot not found: {latest_id}",
                    code=ErrorCode.SNAPSHOT_NOT_FOUND,
                )

            return Success(deepcopy(pipeline_snapshots[latest_id]))

    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]:
        """List all snapshot IDs for a pipeline in step-sorted order."""
        with self._lock:
            if pipeline_id not in self._index:
                return Success([])

            return Success(list(self._index[pipeline_id]))

    def delete_snapshot(self, snapshot_id: str) -> Result[None]:
        """Delete a snapshot by ID from in-memory storage."""
        if not SNAPSHOT_ID_PATTERN.match(snapshot_id):
            return Failure(
                reason="Invalid snapshot ID format",
                code=ErrorCode.INVALID_SNAPSHOT_ID,
            )

        pipeline_id, _rest = snapshot_id.split("@", 1)

        with self._lock:
            pipeline_snapshots = self._snapshots.get(pipeline_id)
            if pipeline_snapshots is None or snapshot_id not in pipeline_snapshots:
                return Failure(
                    reason=f"Snapshot not found: {snapshot_id}",
                    code=ErrorCode.SNAPSHOT_NOT_FOUND,
                )

            del pipeline_snapshots[snapshot_id]

            if pipeline_id in self._index:
                self._index[pipeline_id] = [s for s in self._index[pipeline_id] if s != snapshot_id]

        return Success(None)

    def close(self) -> None:
        """Release any resources held by the snapshot store.

        Clears all in-memory storage. Idempotent — calling close() multiple
        times is safe.
        """
        with self._lock:
            self._snapshots.clear()
            self._index.clear()
