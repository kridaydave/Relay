"""Snapshot persistence layer for Relay.

Owns: checkpoint lifecycle, rollback restore, storage cleanup.
Does NOT: execute agents or manage pipeline state.
"""

import json
import logging
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

from relay.envelope import PIPELINE_ID_PATTERN, ContextEnvelope, validate_pipeline_id, verify_signature
from relay.snapshot_protocol import SNAPSHOT_ID_PATTERN, InvalidSnapshotIdError, extract_step_from_snapshot_id
from relay.snapshot_protocol import SnapshotStore as SnapshotStore  # noqa: F811 — re-export Protocol
from relay.types import ErrorCode, Failure, INITIAL_KEY_ID, JSONDict, Result, Success

MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024  # 100 MB

__all__ = [
    "LocalFileSnapshotStore",
    "SnapshotStore",
]


class LocalFileSnapshotStore:
    """Persists and retrieves envelope checkpoints on the local filesystem.

    Owns: checkpoint lifecycle, rollback restore, storage cleanup.
    Does NOT: execute agents or manage pipeline state.
    """

    def __init__(self, storage_path: str = "./relay_data/snapshots", signing_secret: str | None = None) -> None:
        """Initialize the snapshot store with the given storage path.

        Args:
            storage_path: Root directory for snapshot storage.
            signing_secret: Optional HMAC signing secret. If provided,
                signatures are verified on every load_snapshot call.
        """
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._signing_secret: str | None = signing_secret

    def close(self) -> None:
        """Release any resources held by the snapshot store.

        No-op for the filesystem-based implementation since file handles
        are not kept open between operations.
        """
        ...

    def delete_snapshot(self, snapshot_id: str) -> Result[None]:
        """Delete a snapshot by ID.

        Removes the snapshot file and its index entry. Returns Failure
        if the snapshot does not exist or the file cannot be removed.
        """
        if not SNAPSHOT_ID_PATTERN.match(snapshot_id):
            return Failure(
                reason="Invalid snapshot ID format",
                code=ErrorCode.INVALID_SNAPSHOT_ID,
            )
        pipeline_id, _rest = snapshot_id.split("@", 1)
        snapshot_path = self._storage_path / pipeline_id / f"{snapshot_id}.json"
        try:
            snapshot_path.unlink(missing_ok=False)
        except FileNotFoundError:
            return Failure(
                reason=f"Snapshot not found: {snapshot_id}",
                code=ErrorCode.SNAPSHOT_NOT_FOUND,
            )
        except OSError as e:
            return Failure(
                reason=f"Failed to delete snapshot: {e}",
                code=ErrorCode.SNAPSHOT_SAVE_FAILED,
            )

        index_result = self._remove_from_index(pipeline_id, snapshot_id)
        if isinstance(index_result, Failure):
            logger.warning("Snapshot file deleted but index update failed: %s", index_result.reason)
        return Success(None)

    def _remove_from_index(self, pipeline_id: str, snapshot_id: str) -> Result[None]:
        """Remove a snapshot ID from the pipeline's index."""
        index_path = self._storage_path / pipeline_id / "index.json"
        if not index_path.exists():
            return Success(None)

        try:
            with open(index_path, "r") as f:
                data: object = json.load(f)
                index_data = cast(JSONDict, data) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return Success(None)

        snapshots: list[str] = []
        existing = index_data.get("snapshots", [])
        if isinstance(existing, list):
            for s in existing:
                if isinstance(s, str) and s != snapshot_id:
                    snapshots.append(s)
        index_data["snapshots"] = snapshots

        temp_index_path = index_path.parent / "index.tmp"
        try:
            with open(temp_index_path, "w") as f:
                json.dump(index_data, f, indent=2)
            os.replace(temp_index_path, index_path)
        except (OSError, TypeError) as e:
            logger.warning("Failed to update index after delete: %s", e)
            return Failure(
                reason=f"Failed to update index: {e}",
                code=ErrorCode.INDEX_UPDATE_FAILED,
            )
        finally:
            try:
                temp_index_path.unlink(missing_ok=True)
            except OSError:
                pass
        return Success(None)

    def save_snapshot(self, envelope: ContextEnvelope) -> Result[str]:
        """Save an envelope as a snapshot and return the snapshot ID.

        Validates pipeline_id at the boundary to defend against manually
        constructed envelopes with invalid or malicious pipeline_ids
        (defense-in-depth per Rule 4.1).

        Uses file-first ordering: writes the snapshot file, then updates the index.
        If file write fails, no orphaned index entry is created.
        """
        pipeline_id = envelope.pipeline_id
        if not pipeline_id or not PIPELINE_ID_PATTERN.match(pipeline_id):
            return Failure(
                reason=f"Invalid pipeline_id: {pipeline_id}",
                code=ErrorCode.INVALID_PIPELINE_ID,
            )
        pipeline_path = self._storage_path / pipeline_id
        if pipeline_path.is_symlink():
            return Failure(
                reason=f"Pipeline path is a symlink, refusing to write: {pipeline_path}",
                code=ErrorCode.SNAPSHOT_SAVE_FAILED,
            )
        pipeline_path.mkdir(parents=True, exist_ok=True)
        if pipeline_path.is_symlink():
            return Failure(
                reason=f"Pipeline path is a symlink after creation: {pipeline_path}",
                code=ErrorCode.SNAPSHOT_SAVE_FAILED,
            )

        snapshot_id = f"{pipeline_id}@{envelope.step}_{uuid.uuid4().hex[:12]}"

        snapshot_file = f"{snapshot_id}.json"
        snapshot_path = pipeline_path / snapshot_file
        temp_path = pipeline_path / f"{snapshot_id}.tmp"

        try:
            json_str = json.dumps(self._envelope_to_dict(envelope), indent=2)
            if len(json_str) > MAX_SNAPSHOT_BYTES:
                return Failure(
                    reason=f"Snapshot exceeds maximum size of {MAX_SNAPSHOT_BYTES} bytes",
                    code=ErrorCode.SNAPSHOT_SAVE_FAILED,
                )
            _O_NOFOLLOW = cast(int, getattr(os, 'O_NOFOLLOW', 0))
            fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w") as f:
                f.write(json_str)
            os.replace(temp_path, snapshot_path)
        except (OSError, TypeError) as e:
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Failed to clean up temp file: %s", temp_path)
            return Failure(reason=str(e), code=ErrorCode.SNAPSHOT_SAVE_FAILED)

        index_result = self._add_to_index(pipeline_id, snapshot_id)
        if isinstance(index_result, Failure):
            try:
                snapshot_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to clean up snapshot file: %s", snapshot_path)
            return index_result

        return Success(snapshot_id)

    def load_snapshot(self, snapshot_id: str) -> Result[ContextEnvelope]:
        """Load an envelope from a snapshot by ID.

        If this store was initialized with a signing_secret, the envelope
        signature is verified before returning.
        """
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
            stat_result = snapshot_path.stat()
            if stat_result.st_size > MAX_SNAPSHOT_BYTES:
                return Failure(
                    reason=f"Snapshot file exceeds maximum size of {MAX_SNAPSHOT_BYTES} bytes",
                    code=ErrorCode.SNAPSHOT_LOAD_FAILED,
                )
            with open(snapshot_path, "r") as f:
                data: object = json.load(f)
            if not isinstance(data, dict):
                return Failure(reason="Invalid snapshot data format", code=ErrorCode.INVALID_SNAPSHOT)
            envelope_result = self._dict_to_envelope(cast(JSONDict, data))
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

            if envelope.pipeline_id != pipeline_id:
                return Failure(
                    reason=(
                        f"Snapshot integrity error: filename indicates pipeline "
                        f"{pipeline_id} but envelope body contains pipeline "
                        f"{envelope.pipeline_id}"
                    ),
                    code=ErrorCode.INVALID_SNAPSHOT,
                )

            if self._signing_secret is not None and not verify_signature(envelope, self._signing_secret):
                return Failure(
                    reason=f"Invalid signature for snapshot: {snapshot_id}",
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
        snapshots_raw: object = index_data.get("snapshots", [])
        snapshots: list[str] = snapshots_raw if isinstance(snapshots_raw, list) else []
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

        snapshots_data: object = index_result.value.get("snapshots", [])
        if isinstance(snapshots_data, list):
            snapshots_list: list[str] = []
            for s in snapshots_data:
                if isinstance(s, str):
                    snapshots_list.append(s)
            snapshots_result: list[str] = snapshots_list
        else:
            snapshots_result = []
        return Success(snapshots_result)

    def _add_to_index(self, pipeline_id: str, snapshot_id: str) -> Result[None]:
        """Add a snapshot ID to the pipeline's index."""
        index_path = self._storage_path / pipeline_id / "index.json"
        try:
            snapshots_list: list[str] = []
            index_data: JSONDict = {"snapshots": []}
            if index_path.exists():
                with open(index_path, "r") as f:
                    loaded: object = json.load(f)
                if isinstance(loaded, dict):
                    index_data = cast(JSONDict, loaded)
                    existing: object = index_data.get("snapshots", [])
                    if isinstance(existing, list):
                        for s in existing:
                            if isinstance(s, str):
                                snapshots_list.append(s)
                else:
                    snapshots_list = []
        except json.JSONDecodeError as e:
            return Failure(
                reason=f"Corrupted index JSON: {e}",
                code=ErrorCode.CORRUPTED_INDEX,
            )
        except (OSError, TypeError) as e:
            return Failure(
                reason=f"Failed to update index: {e}",
                code=ErrorCode.INDEX_UPDATE_FAILED,
            )

        if snapshot_id not in snapshots_list:
            snapshots_list.append(snapshot_id)
            try:
                snapshots_list.sort(key=extract_step_from_snapshot_id)
            except InvalidSnapshotIdError as e:
                return Failure(
                    reason=f"Corrupted index entry: {e}",
                    code=ErrorCode.CORRUPTED_INDEX,
                )
        index_data["snapshots"] = snapshots_list

        temp_index_path = index_path.parent / "index.tmp"
        try:
            with open(temp_index_path, "w") as f:
                json.dump(index_data, f, indent=2)
            os.replace(temp_index_path, index_path)
        except (OSError, TypeError) as e:
            return Failure(
                reason=f"Failed to update index: {e}",
                code=ErrorCode.INDEX_UPDATE_FAILED,
            )
        finally:
            try:
                temp_index_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to clean up temp index: %s", temp_index_path)

        return Success(None)

    def _load_index(self, pipeline_id: str) -> Result[JSONDict]:
        """Load the index for a pipeline."""
        index_path = self._storage_path / pipeline_id / "index.json"
        try:
            with open(index_path, "r") as f:
                data: object = json.load(f)
                if isinstance(data, dict):
                    data_dict: JSONDict = {}
                    for k, v in data.items():
                        if isinstance(k, str):
                            data_dict[k] = v
                        else:
                            logger.warning("Non-string key '%s' dropped from index", k)
                    return Success(data_dict)
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

    def _envelope_to_dict(self, envelope: ContextEnvelope) -> JSONDict:
        """Convert envelope to JSON-serializable dict.

        Uses timespec='seconds' so timestamps are consistent across Python 3.11/3.12.
        """
        result: JSONDict = {
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
            "key_id": envelope.key_id,
            "nonce": envelope.nonce,
            "sequence_number": envelope.sequence_number,
        }
        return result

    def _require_str(self, data: JSONDict, key: str) -> "Result[str]":
        """Validate and return a string field from data dict."""
        value = data.get(key)
        if not isinstance(value, str):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _require_int(self, data: JSONDict, key: str) -> "Result[int]":
        """Validate and return an int field from data dict."""
        value = data.get(key)
        if not isinstance(value, int):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _require_dict(self, data: JSONDict, key: str) -> "Result[JSONDict]":
        """Validate and return a dict field from data dict."""
        value = data.get(key)
        if not isinstance(value, dict):
            return Failure(
                reason=f"Missing or invalid {key}", code=ErrorCode.INVALID_SNAPSHOT
            )
        return Success(value)

    def _dict_to_envelope(self, data: JSONDict) -> Result[ContextEnvelope]:
        """Convert dict back to ContextEnvelope."""
        rv_result = self._require_str(data, "relay_version")
        if isinstance(rv_result, Failure):
            return rv_result
        relay_version: str = rv_result.value

        pid_result = self._require_str(data, "pipeline_id")
        if isinstance(pid_result, Failure):
            return pid_result
        pipeline_id: str = pid_result.value

        pid_validation = validate_pipeline_id(pipeline_id)
        if isinstance(pid_validation, Failure):
            return pid_validation

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
        payload: JSONDict = payload_result.value

        hash_result = self._require_str(data, "manifest_hash")
        if isinstance(hash_result, Failure):
            return hash_result
        manifest_hash: str = hash_result.value

        sig_result = self._require_str(data, "signature")
        if isinstance(sig_result, Failure):
            return sig_result
        signature: str = sig_result.value

        fork_id_raw: object = data.get("fork_id")
        fork_id: str | None = fork_id_raw if isinstance(fork_id_raw, str) else None
        join_strategy_raw: object = data.get("join_strategy")
        join_strategy: str | None = join_strategy_raw if isinstance(join_strategy_raw, str) else None

        fork_count: int | None = None
        if "fork_count" in data and data.get("fork_count") is not None:
            fc_result = self._require_int(data, "fork_count")
            if isinstance(fc_result, Failure):
                return fc_result
            fork_count = fc_result.value

        forks_succeeded: int | None = None
        if "forks_succeeded" in data and data.get("forks_succeeded") is not None:
            fs_result = self._require_int(data, "forks_succeeded")
            if isinstance(fs_result, Failure):
                return fs_result
            forks_succeeded = fs_result.value

        key_id_raw: object = data.get("key_id")
        key_id: str = key_id_raw if isinstance(key_id_raw, str) else INITIAL_KEY_ID
        if "key_id" not in data or not isinstance(data.get("key_id"), str):
            logger.warning("Snapshot missing key_id field — defaulting to %r", INITIAL_KEY_ID)

        nonce_raw: object = data.get("nonce")
        nonce: str = nonce_raw if isinstance(nonce_raw, str) else ""
        if "nonce" not in data or not isinstance(data.get("nonce"), str):
            logger.warning("Snapshot missing nonce field — defaulting to empty string")

        sequence_raw: object = data.get("sequence_number")
        sequence_number: int = 0
        if isinstance(sequence_raw, int):
            sequence_number = sequence_raw
        else:
            logger.warning("Snapshot missing sequence_number field — defaulting to 0")

        try:
            envelope = ContextEnvelope(
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
                forks_succeeded=forks_succeeded,
                key_id=key_id,
                nonce=nonce,
                sequence_number=sequence_number,
            )
        except ValueError as e:
            return Failure(reason=str(e), code=ErrorCode.INVALID_SNAPSHOT)
        return Success(envelope)
