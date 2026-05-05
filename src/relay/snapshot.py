"""Snapshot persistence layer for Relay.

Owns: checkpoint lifecycle, rollback restore, storage cleanup.
Does NOT: validate data, sign envelopes, execute agents.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from relay.envelope import ContextEnvelope
from relay.types import Failure, Result, Success


class SnapshotStore:
    """Persists and retrieves envelope checkpoints.

    Owns: checkpoint lifecycle, rollback restore, storage cleanup.
    Does NOT: validate data, sign envelopes, execute agents.
    """

    def __init__(self, storage_path: str = "./relay_data/snapshots") -> None:
        """Initialize the snapshot store with the given storage path."""
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID."""
        pipeline_id = envelope.pipeline_id
        pipeline_path = self._storage_path / pipeline_id
        pipeline_path.mkdir(parents=True, exist_ok=True)

        snapshot_id = f"{pipeline_id}@{envelope.step}_{uuid.uuid4().hex[:12]}"
        snapshot_file = f"{snapshot_id}.json"
        snapshot_path = pipeline_path / snapshot_file
        temp_path = pipeline_path / f"{snapshot_id}.tmp"

        try:
            with open(temp_path, "w") as f:
                json.dump(self._envelope_to_dict(envelope), f, indent=2)
            os.replace(temp_path, snapshot_path)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            return Failure(reason=str(e), code="SNAPSHOT_SAVE_FAILED")

        self._add_to_index(pipeline_id, snapshot_id)
        return Success(snapshot_id)

    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by ID."""
        if "@" not in snapshot_id:
            return Failure(
                reason="Invalid snapshot ID format, missing pipeline_id",
                code="INVALID_SNAPSHOT_ID",
            )

        pipeline_id, rest = snapshot_id.split("@", 1)
        parts = rest.rsplit("_", 1)
        if len(parts) != 2:
            return Failure(
                reason="Invalid snapshot ID format", code="INVALID_SNAPSHOT_ID"
            )

        try:
            step = int(parts[0])
        except ValueError:
            return Failure(
                reason="Invalid step in snapshot ID", code="INVALID_SNAPSHOT_ID"
            )

        snapshot_path = self._storage_path / pipeline_id / f"{snapshot_id}.json"
        if not snapshot_path.exists():
            return Failure(
                reason=f"Snapshot not found: {snapshot_id}", code="SNAPSHOT_NOT_FOUND"
            )

        try:
            with open(snapshot_path, "r") as f:
                data = json.load(f)
            return Success(self._dict_to_envelope(data))
        except Exception as e:
            return Failure(reason=str(e), code="SNAPSHOT_LOAD_FAILED")

    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
        """Get the most recent snapshot for a pipeline."""
        index_data = self._load_index(pipeline_id)
        if index_data is None:
            return Failure(
                reason=f"No snapshots found for pipeline: {pipeline_id}",
                code="PIPELINE_NOT_FOUND",
            )

        snapshots = index_data.get("snapshots", [])
        if not snapshots:
            return Failure(
                reason=f"No snapshots found for pipeline: {pipeline_id}",
                code="NO_SNAPSHOTS",
            )

        latest_id = snapshots[-1]
        return self.load_snapshot(latest_id)

    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]:
        """List all snapshot IDs for a pipeline."""
        index_data = self._load_index(pipeline_id)
        if index_data is None:
            return Success([])
        return Success(index_data.get("snapshots", []))

    def _add_to_index(self, pipeline_id: str, snapshot_id: str) -> None:
        """Add a snapshot ID to the pipeline's index."""
        index_path = self._storage_path / pipeline_id / "index.json"
        try:
            index_data: dict[str, Any]
            if index_path.exists():
                with open(index_path, "r") as f:
                    loaded = json.load(f)
                    index_data = (
                        loaded if isinstance(loaded, dict) else {"snapshots": []}
                    )
            else:
                index_data = {"snapshots": []}

            if snapshot_id not in index_data["snapshots"]:
                index_data["snapshots"].append(snapshot_id)

                # Sort numerically by step to avoid lexicographical bug (e.g. 10 sorting before 2)
                def sort_key(s_id: str) -> int:
                    if "@" in s_id:
                        rest = s_id.split("@", 1)[1]
                        return int(rest.split("_")[0])
                    return int(s_id.split("_")[0])

                index_data["snapshots"].sort(key=sort_key)

            temp_index_path = index_path.parent / "index.tmp"
            with open(temp_index_path, "w") as f:
                json.dump(index_data, f, indent=2)
            os.replace(temp_index_path, index_path)
        except Exception as e:
            raise RuntimeError(f"Failed to update index: {e}")

    def _load_index(self, pipeline_id: str) -> dict[str, Any] | None:
        """Load the index for a pipeline."""
        index_path = self._storage_path / pipeline_id / "index.json"
        if not index_path.exists():
            return None
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _envelope_to_dict(self, envelope: ContextEnvelope) -> dict[str, Any]:
        """Convert envelope to JSON-serializable dict."""
        return {
            "relay_version": envelope.relay_version,
            "pipeline_id": envelope.pipeline_id,
            "step": envelope.step,
            "timestamp": envelope.timestamp.isoformat(),
            "token_budget_used": envelope.token_budget_used,
            "token_budget_total": envelope.token_budget_total,
            "payload": envelope.payload,
            "signature": envelope.signature,
        }

    def _dict_to_envelope(self, data: dict[str, Any]) -> ContextEnvelope:
        """Convert dict back to ContextEnvelope."""
        return ContextEnvelope(
            relay_version=data["relay_version"],
            pipeline_id=data["pipeline_id"],
            step=data["step"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            token_budget_used=data["token_budget_used"],
            token_budget_total=data["token_budget_total"],
            payload=data["payload"],
            signature=data["signature"],
        )
