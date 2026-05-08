"""Snapshot manager for CoreRelayPipeline.

Owns: snapshot save/load/cleanup logic.
Does NOT: manage pipeline state, create envelopes, or validate handoffs.
"""

from relay.envelope import ContextEnvelope
from relay.snapshot import SnapshotStore
from relay.types import Failure, Result


class SnapshotManager:
    """Manages snapshot persistence for the pipeline.

    Owns: snapshot save/load/cleanup logic.
    Does NOT: manage pipeline state, create envelopes, or validate handoffs.
    """

    def __init__(self, snapshot_store: SnapshotStore, snapshot_ids: dict[int, str]) -> None:
        """Initialize with a snapshot store and step-to-id registry.

        Args:
            snapshot_store: The underlying snapshot store.
            snapshot_ids: Mutable map of step number to snapshot ID.
                         Managed externally so PipelineState can own it.
        """
        self._snapshot_store = snapshot_store
        self._snapshot_ids = snapshot_ids

    def save_and_register(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope snapshot and register its ID.

        Args:
            envelope: The envelope to snapshot.

        Returns:
            Success with the snapshot ID, or Failure on error.
        """
        result = self._snapshot_store.save_snapshot(envelope)
        if isinstance(result, Failure):
            return result

        self._snapshot_ids[envelope.step] = result.value
        return result

    def advance(
        self,
        new_envelope: ContextEnvelope,
        previous_envelope: ContextEnvelope | None,
    ) -> Result[None]:
        """Save the new envelope snapshot and clean up the oldest snapshot.

        Args:
            new_envelope: The new current envelope.
            previous_envelope: The previous envelope (oldest in history) to clean up.

        Returns:
            Success if saved, Failure if snapshot could not be saved.
        """
        save_result = self._snapshot_store.save_snapshot(new_envelope)
        if isinstance(save_result, Failure):
            return save_result

        self._snapshot_ids[new_envelope.step] = save_result.value

        if previous_envelope is not None:
            self._snapshot_ids.pop(previous_envelope.step, None)

        return save_result

    def load(self, step: int) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by step number.

        Args:
            step: The step number of the snapshot.

        Returns:
            The envelope from the snapshot, or Failure if not found.
        """
        snapshot_id = self._snapshot_ids.get(step)
        if snapshot_id is None:
            return Failure(
                reason="No snapshot registered for step",
                code="NO_SNAPSHOT_REGISTERED",
            )

        return self._snapshot_store.load_snapshot(snapshot_id)
