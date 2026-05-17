"""Rollback handler for CoreRelayPipeline.

Owns: rollback logic, snapshot-based restoration.
Does NOT: manage pipeline state, create envelopes, or validate handoffs.
"""

from relay.envelope import ContextEnvelope
from relay.snapshot_protocol import SnapshotStore
from relay.types import ErrorCode, Failure, Result, RollbackSuccess


class RollbackHandler:
    """Handles rollback logic by restoring envelopes from snapshots.

    Owns: rollback logic, snapshot-based restoration.
    Does NOT: manage pipeline state, create envelopes, or validate handoffs.
    """

    def restore_to_previous(
        self,
        previous_envelope: ContextEnvelope,
        snapshot_ids: dict[int, str],
        snapshot_store: SnapshotStore,
        reason: str,
    ) -> Result[ContextEnvelope]:
        """Restore to a previous envelope from its snapshot.

        Args:
            previous_envelope: The envelope to restore to (from history).
            snapshot_ids: Map of step number to snapshot ID.
            snapshot_store: The snapshot store to load from.
            reason: Human-readable reason for the rollback.

        Returns:
            RollbackSuccess with the restored envelope, or Failure if unavailable.
        """
        snapshot_id = snapshot_ids.get(previous_envelope.step)
        if snapshot_id is None:
            return Failure(
                reason="No snapshot registered for step",
                code=ErrorCode.NO_SNAPSHOT_REGISTERED,
            )

        restore_result = snapshot_store.load_snapshot(snapshot_id)
        if isinstance(restore_result, Failure):
            return restore_result

        return RollbackSuccess(value=restore_result.value, reason=reason)
