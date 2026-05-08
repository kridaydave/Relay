"""Snapshot persistence layer for Relay.

Owns: checkpoint lifecycle, rollback restore, storage cleanup.
Does NOT: execute agents or manage pipeline state.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

from relay.envelope import ContextEnvelope
from relay.types import Failure, Result, Success


class InvalidSnapshotIdError(Exception):
    """Raised when snapshot ID format is invalid."""
    pass


def _extract_step_from_snapshot_id(s_id: str) -> int:
    """Extract step number from snapshot ID for sorting.

    Handles formats: "pipeline_id@step_uuid" and "pipeline_id_step".

    Returns:
        Sort key (step number).

    Raises:
        InvalidSnapshotIdError: If snapshot ID format is invalid.
    """
    try:
        if "@" in s_id:
            rest = s_id.split("@", 1)[1]
            return int(rest.split("_")[0])
        return int(s_id.split("_")[0])
    except (ValueError, IndexError):
        raise InvalidSnapshotIdError(
            f"Invalid snapshot ID format: {s_id}"
        )


class SnapshotStore:
    """Persists and retrieves envelope checkpoints.

    Owns: checkpoint lifecycle, rollback restore, storage cleanup.
    Does NOT: execute agents or manage pipeline state.
    """

    def __init__(self, storage_path: str = "./relay_data/snapshots") -> None:
        """Initialize the snapshot store with the given storage path."""
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID."""
        pipeline_id = envelope.pipeline_id
        if not PIPELINE_ID_PATTERN.match(pipeline_id):
            return Failure(
                reason="Invalid pipeline_id: must match pattern ^[a-zA-Z0-9_-]{1,128}$",
                code="INVALID_PIPELINE_ID",
            )
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

        index_result = self._add_to_index(pipeline_id, snapshot_id)
        if isinstance(index_result, Failure):
            return index_result
        
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
        try:
            with open(snapshot_path, "r") as f:
                data = json.load(f)
            envelope_result = self._dict_to_envelope(data)
            if isinstance(envelope_result, Failure):
                return envelope_result
            return Success(envelope_result.value)
        except FileNotFoundError:
            return Failure(
                reason=f"Snapshot not found: {snapshot_id}", code="SNAPSHOT_NOT_FOUND"
            )
        except Exception as e:
            return Failure(reason=str(e), code="SNAPSHOT_LOAD_FAILED")

    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
        """Get the most recent snapshot for a pipeline."""
        index_result = self._load_index(pipeline_id)
        if isinstance(index_result, Failure):
            return Failure(
                reason=f"No snapshots found for pipeline: {pipeline_id}",
                code="PIPELINE_NOT_FOUND",
            )

        index_data = index_result.value
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
        index_result = self._load_index(pipeline_id)
        if isinstance(index_result, Failure):
            if index_result.code == "INDEX_NOT_FOUND":
                return Success([])
            return Failure(reason=index_result.reason, code=index_result.code)

        return Success(index_result.value.get("snapshots", []))

    def _add_to_index(self, pipeline_id: str, snapshot_id: str) -> Result[None]:
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
                index_data["snapshots"].sort(key=_extract_step_from_snapshot_id)

            temp_index_path = index_path.parent / "index.tmp"
            with open(temp_index_path, "w") as f:
                json.dump(index_data, f, indent=2)
            os.replace(temp_index_path, index_path)
        except Exception as e:
            return Failure(reason=f"Failed to update index: {e}", code="INDEX_UPDATE_FAILED")
        
        return Success(None)

    def _load_index(self, pipeline_id: str) -> Result[dict[str, Any]]:
        """Load the index for a pipeline."""
        index_path = self._storage_path / pipeline_id / "index.json"
        if not index_path.exists():
            return Failure(
                reason=f"Index not found for pipeline: {pipeline_id}",
                code="INDEX_NOT_FOUND",
            )
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return Success(data)
                return Failure(
                    reason="Invalid index format - expected dict",
                    code="INVALID_INDEX",
                )
        except json.JSONDecodeError as e:
            return Failure(
                reason=f"Corrupted index JSON: {e}",
                code="CORRUPTED_INDEX",
            )
        except OSError as e:
            return Failure(
                reason=f"Failed to read index: {e}",
                code="INDEX_READ_FAILED",
            )

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
            "manifest_hash": envelope.manifest_hash,
            "signature": envelope.signature,
        }

    def _require_field(self, data: dict[str, Any], key: str, expected_type: type) -> Any:
        """Validate and return a field from data dict."""
        value = data.get(key)
        if value is None or not isinstance(value, expected_type):
            return Failure(reason=f"Missing or invalid {key}", code="INVALID_SNAPSHOT")
        return value

    def _dict_to_envelope(self, data: dict[str, Any]) -> Result[ContextEnvelope]:
        """Convert dict back to ContextEnvelope."""
        relay_version = self._require_field(data, "relay_version", str)
        if isinstance(relay_version, Failure):
            return relay_version

        pipeline_id = self._require_field(data, "pipeline_id", str)
        if isinstance(pipeline_id, Failure):
            return pipeline_id

        step = self._require_field(data, "step", int)
        if isinstance(step, Failure):
            return step

        timestamp_str = self._require_field(data, "timestamp", str)
        if isinstance(timestamp_str, Failure):
            return timestamp_str
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return Failure(reason="Invalid timestamp format", code="INVALID_SNAPSHOT")

        token_budget_used = self._require_field(data, "token_budget_used", int)
        if isinstance(token_budget_used, Failure):
            return token_budget_used

        token_budget_total = self._require_field(data, "token_budget_total", int)
        if isinstance(token_budget_total, Failure):
            return token_budget_total

        payload = self._require_field(data, "payload", dict)
        if isinstance(payload, Failure):
            return payload

        raw_hash = data.get("manifest_hash", "")
        manifest_hash = raw_hash if isinstance(raw_hash, str) else ""

        signature = self._require_field(data, "signature", str)
        if isinstance(signature, Failure):
            return signature

        return Success(ContextEnvelope(
            relay_version=relay_version,
            pipeline_id=pipeline_id,
            step=step,
            timestamp=timestamp,
            token_budget_used=token_budget_used,
            token_budget_total=token_budget_total,
            payload=payload,
            manifest_hash=manifest_hash,
            signature=signature,
        ))
