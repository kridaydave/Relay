"""Snapshot manager for CoreRelayPipeline.

Owns: snapshot save/load/cleanup logic.
Does NOT: own snapshot_id state — callers update their own registries.
"""

import json
from typing import Any

from relay.envelope import ContextEnvelope
from relay.snapshot import SnapshotStore
from relay.types import ErrorCode, Failure, Result, Success


def serialize_payload(payload: dict[str, Any]) -> str:
    """Serialize payload to JSON string.

    Args:
        payload: The payload dictionary to serialize.

    Returns:
        JSON string representation of the payload.
    """
    return json.dumps(payload)


class SnapshotManager:
    """Manages snapshot persistence for the pipeline.

    Owns: snapshot save/load logic.
    Does NOT: own snapshot_id state — callers update their own registries.
    """

    def __init__(self, snapshot_store: SnapshotStore) -> None:
        """Initialize with a snapshot store.

        Args:
            snapshot_store: The underlying snapshot store.
        """
        self._snapshot_store = snapshot_store

    def save(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope snapshot.

        Args:
            envelope: The envelope to snapshot.

        Returns:
            Success with the snapshot ID, or Failure on error.
            Caller is responsible for registering the ID.
        """
        return self._snapshot_store.save_snapshot(envelope)

    def load(self, snapshot_id: str) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by ID.

        Args:
            snapshot_id: The snapshot ID to load.

        Returns:
            The envelope from the snapshot, or Failure if not found.
        """
        return self._snapshot_store.load_snapshot(snapshot_id)
