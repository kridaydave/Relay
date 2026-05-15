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

from relay.envelope import PIPELINE_ID_PATTERN, ContextEnvelope
from relay.types import ErrorCode, Failure, Result, Success

SNAPSHOT_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9_-]{1,128}@\d+_[a-f0-9]{12}$"
)

__all__ = [
    "SnapshotStore",
]


class InvalidSnapshotIdError(Exception):
    """Raised when snapshot ID format is invalid."""

    pass


def _extract_step_from_snapshot_id(s_id: str) -> int:
    """Extract step number from snapshot ID for sorting.

    Handles format: "pipeline_id@step_uuid".

    Returns:
        Sort key (step number).

    Raises:
        InvalidSnapshotIdError: If snapshot ID format is invalid.
    """
    try:
        if "@" not in s_id:
            raise InvalidSnapshotIdError(f"Invalid snapshot ID format: {s_id}")
        rest = s_id.split("@", 1)[1]
        return int(rest.split("_")[0])
    except (ValueError, IndexError):
        raise InvalidSnapshotIdError(f"Invalid snapshot ID format: {s_id}")


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
        """Save an envelope as a snapshot and return the snapshot ID.

        Trusts that envelope.pipeline_id is valid — validated at construction
        time by create_initial_envelope via _validate_pipeline_id.

        Uses file-first ordering: writes the snapshot file, then updates the index.
        If file write fails, no orphaned index entry is created.
        """
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
        except (OSError, json.JSONDecodeError) as e:
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return Failure(reason=str(e), code=ErrorCode.SNAPSHOT_SAVE_FAILED)

        index_result = self._add_to_index(pipeline_id, snapshot_id)
        if isinstance(index_result, Failure):
            try:
                snapshot_path.unlink(missing_ok=True)
            except OSError:
                pass
            return index_result

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

        snapshot_path = self._storage_path / pipeline_id / f"{snapshot_id}.json"
        try:
            with open(snapshot_path, "r") as f:
                data = json.load(f)
            envelope_result = self._dict_to_envelope(data)
            if isinstance(envelope_result, Failure):
                return envelope_result
            envelope = envelope_result.value

            if envelope.step != step:
                return Failure(
                    reason=(
                        f"Snapshot integrity error: filename indicates step {step} "
                        f"but envelope body contains step {envelope.step}"
                    ),
                    code=ErrorCode.INVALID_SNAPSHOT,
                )

            return Success(envelope)
        except FileNotFoundError:
            return Failure(
                reason=f"Snapshot not found: {snapshot_id}",
                code=ErrorCode.SNAPSHOT_NOT_FOUND,
            )
        except (json.JSONDecodeError, OSError) as e:
            return Failure(reason=str(e), code=ErrorCode.SNAPSHOT_LOAD_FAILED)

    def get_latest_snapshot(self, pipeline_id: str) -> Result[ContextEnvelope]:
        """Get the most recent snapshot for a pipeline."""
        index_result = self._load_index(pipeline_id)
        if isinstance(index_result, Failure):
            if index_result.code == ErrorCode.INDEX_NOT_FOUND:
                return Failure(
                    reason=f"No snapshots found for pipeline: {pipeline_id}",
                    code=ErrorCode.PIPELINE_NOT_FOUND,
                )
            return index_result

        index_data = index_result.value
        snapshots = index_data.get("snapshots", [])
        if not snapshots:
            return Failure(
                reason=f"No snapshots found for pipeline: {pipeline_id}",
                code=ErrorCode.NO_SNAPSHOTS,
            )

        latest_id = snapshots[-1]
        return self.load_snapshot(latest_id)

    def list_snapshots(self, pipeline_id: str) -> Result[list[str]]:
        """List all snapshot IDs for a pipeline."""
        index_result = self._load_index(pipeline_id)
        if isinstance(index_result, Failure):
            if index_result.code == ErrorCode.INDEX_NOT_FOUND:
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
                try:
                    index_data["snapshots"].sort(key=_extract_step_from_snapshot_id)
                except InvalidSnapshotIdError as e:
                    return Failure(
                        reason=f"Corrupted index entry: {e}",
                        code=ErrorCode.CORRUPTED_INDEX,
                    )

            temp_index_path = index_path.parent / "index.tmp"
            try:
                with open(temp_index_path, "w") as f:
                    json.dump(index_data, f, indent=2)
                os.replace(temp_index_path, index_path)
            finally:
                try:
                    temp_index_path.unlink(missing_ok=True)
                except OSError:
                    pass
        except (OSError, json.JSONDecodeError) as e:
            return Failure(
                reason=f"Failed to update index: {e}",
                code=ErrorCode.INDEX_UPDATE_FAILED,
            )

        return Success(None)

    def _load_index(self, pipeline_id: str) -> Result[dict[str, Any]]:
        """Load the index for a pipeline."""
        index_path = self._storage_path / pipeline_id / "index.json"
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return Success(data)
                return Failure(
                    reason="Invalid index format - expected dict",
                    code=ErrorCode.INVALID_INDEX,
                )
        except FileNotFoundError:
            return Failure(
                reason=f"Index not found for pipeline: {pipeline_id}",
                code=ErrorCode.INDEX_NOT_FOUND,
            )
        except json.JSONDecodeError as e:
            return Failure(
                reason=f"Corrupted index JSON: {e}",
                code=ErrorCode.CORRUPTED_INDEX,
            )
        except OSError as e:
            return Failure(
                reason=f"Failed to read index: {e}",
                code=ErrorCode.INDEX_READ_FAILED,
            )

    def _envelope_to_dict(self, envelope: ContextEnvelope) -> dict[str, Any]:
        """Convert envelope to JSON-serializable dict.

        Uses timespec='seconds' so timestamps are consistent across Python 3.11/3.12.
        """
        return {
            "relay_version": envelope.relay_version,
            "pipeline_id": envelope.pipeline_id,
            "step": envelope.step,
            "timestamp": envelope.timestamp.isoformat(timespec="seconds"),
            "token_budget_used": envelope.token_budget_used,
            "token_budget_total": envelope.token_budget_total,
            "payload": envelope.payload,
            "manifest_hash": envelope.manifest_hash,
            "signature": envelope.signature,
            "fork_id": envelope.fork_id,
            "join_strategy": envelope.join_strategy,
            "fork_count": envelope.fork_count,
            "forks_succeeded": envelope.forks_succeeded,
        }

    def _require_str(self, data: dict[str, Any], key: str) -> "Result[str]":
        """Validate and return a string field from data dict."""
        value = data.get(key)
        if value is None or not isinstance(value, str):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _require_int(self, data: dict[str, Any], key: str) -> "Result[int]":
        """Validate and return an int field from data dict."""
        value = data.get(key)
        if value is None or not isinstance(value, int):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _require_dict(self, data: dict[str, Any], key: str) -> "Result[dict[str, Any]]":
        """Validate and return a dict field from data dict."""
        value = data.get(key)
        if value is None or not isinstance(value, dict):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _dict_to_envelope(self, data: dict[str, Any]) -> Result[ContextEnvelope]:
        """Convert dict back to ContextEnvelope."""
        rv_result = self._require_str(data, "relay_version")
        if isinstance(rv_result, Failure):
            return rv_result
        relay_version: str = rv_result.value

        pid_result = self._require_str(data, "pipeline_id")
        if isinstance(pid_result, Failure):
            return pid_result
        pipeline_id: str = pid_result.value

        step_result = self._require_int(data, "step")
        if isinstance(step_result, Failure):
            return step_result
        step: int = step_result.value

        ts_result = self._require_str(data, "timestamp")
        if isinstance(ts_result, Failure):
            return ts_result
        timestamp_str: str = ts_result.value
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return Failure(
                reason="Invalid timestamp format", code=ErrorCode.INVALID_SNAPSHOT
            )

        used_result = self._require_int(data, "token_budget_used")
        if isinstance(used_result, Failure):
            return used_result
        token_budget_used: int = used_result.value

        total_result = self._require_int(data, "token_budget_total")
        if isinstance(total_result, Failure):
            return total_result
        token_budget_total: int = total_result.value

        payload_result = self._require_dict(data, "payload")
        if isinstance(payload_result, Failure):
            return payload_result
        payload: dict[str, Any] = payload_result.value

        hash_result = self._require_str(data, "manifest_hash")
        if isinstance(hash_result, Failure):
            return hash_result
        manifest_hash: str = hash_result.value

        sig_result = self._require_str(data, "signature")
        if isinstance(sig_result, Failure):
            return sig_result
        signature: str = sig_result.value

        fork_id = data.get("fork_id")
        join_strategy = data.get("join_strategy")
        fork_count_raw = data.get("fork_count")
        forks_succ_raw = data.get("forks_succeeded")
        fork_count = int(fork_count_raw) if fork_count_raw is not None else None
        forks_succ = int(forks_succ_raw) if forks_succ_raw is not None else None

        return Success(
            ContextEnvelope(
                relay_version=relay_version,
                pipeline_id=pipeline_id,
                step=step,
                timestamp=timestamp,
                token_budget_used=token_budget_used,
                token_budget_total=token_budget_total,
                payload=payload,
                manifest_hash=manifest_hash,
                signature=signature,
                fork_id=fork_id,
                join_strategy=join_strategy,
                fork_count=fork_count,
                forks_succeeded=forks_succ,
            )
        )
