"""SnapshotStore protocol for Relay's snapshot persistence layer.

Owns: the contract for snapshot persistence (save, load, list, get latest).
Does NOT: contain file-based or any concrete implementation of snapshot storage.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from relay.envelope import ContextEnvelope
from relay.types import Closeable, Result


@runtime_checkable
class SnapshotStore(Closeable, Protocol):
    """Protocol for snapshot storage backends.

    Defines the interface for persisting and retrieving context envelope
    checkpoints. All snapshot store implementations must satisfy this protocol.
    """

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID.

        Args:
            envelope: The context envelope to persist.

        Returns:
            Success with the snapshot ID string, or Failure if the save operation
            could not be completed.
        """
        ...

    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by ID.

        Args:
            snapshot_id: The unique identifier of the snapshot to load.

        Returns:
            Success with the loaded ContextEnvelope, or Failure if the snapshot
            does not exist or cannot be read.
        """
        ...

    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
        """Get the most recent snapshot for a pipeline.

        Args:
            pipeline_id: The pipeline identifier to look up.

        Returns:
            Success with the most recent ContextEnvelope, or Failure if no
            snapshots exist for the given pipeline.
        """
        ...

    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]:
        """List all snapshot IDs for a pipeline.

        Args:
            pipeline_id: The pipeline identifier to query.

        Returns:
            Success with a list of snapshot ID strings, or Failure if the
            operation could not be completed.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the snapshot store."""
        ...


__all__ = ["SnapshotStore"]
