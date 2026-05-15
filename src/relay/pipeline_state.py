"""Pipeline state manager for CoreRelayPipeline.

Owns: pipeline state (_current_envelope, _previous_envelopes, _snapshot_ids, _pipeline_id).
Does NOT: create envelopes, validate handoffs, or manage snapshots.
"""

import threading
from contextlib import contextmanager
from typing import Generator

from relay.envelope import ContextEnvelope


class PipelineState:
    """Thread-safe manager of pipeline state.

    Owns: pipeline state (_current_envelope, _previous_envelopes, _snapshot_ids, _pipeline_id).
    Does NOT: create envelopes, validate handoffs, or manage snapshots.
    """

    def __init__(self, pipeline_id: str) -> None:
        self._pipeline_id = pipeline_id
        self._current_envelope: ContextEnvelope | None = None
        self._previous_envelopes: list[ContextEnvelope] = []
        self._snapshot_ids: dict[int, str] = {}
        self._lock = threading.Lock()
        self._lock_owner: int | None = None

    @property
    def pipeline_id(self) -> str:
        return self._pipeline_id

    @property
    def snapshot_ids(self) -> dict[int, str]:
        self._assert_lock_held()
        return dict(self._snapshot_ids)

    def register_snapshot(self, step: int, snapshot_id: str) -> None:
        self._assert_lock_held()
        self._snapshot_ids[step] = snapshot_id

    def current(self) -> ContextEnvelope | None:
        """Return the current envelope under lock."""
        self._assert_lock_held()
        return self._current_envelope

    def _assert_lock_held(self) -> None:
        if threading.get_ident() != self._lock_owner:
            raise RuntimeError(
                "Lock must be held via transaction() context manager"
            )

    @contextmanager
    def transaction(self) -> Generator[ContextEnvelope | None, None, None]:
        """Context manager for safe lock acquisition and release.

        Yields the current envelope while holding the lock.
        Automatically acquires and releases the lock.
        """
        with self._lock:
            self._lock_owner = threading.get_ident()
            try:
                yield self._current_envelope
            finally:
                self._lock_owner = None

    def get_previous_envelopes(self) -> list[ContextEnvelope]:
        """Return a copy of the previous envelopes list under lock."""
        self._assert_lock_held()
        return list(self._previous_envelopes)

    def set_current(self, envelope: ContextEnvelope) -> None:
        self._assert_lock_held()
        self._current_envelope = envelope

    def push_current_to_history(self) -> None:
        """Move current envelope to history without changing current.

        Used by contradiction rollback to preserve the envelope for
        potential subsequent manual rollback.
        """
        self._assert_lock_held()
        if self._current_envelope is not None:
            self._previous_envelopes.append(self._current_envelope)

    def archive_and_set(self, new_envelope: ContextEnvelope) -> None:
        self._assert_lock_held()
        if self._current_envelope is not None:
            self._previous_envelopes.append(self._current_envelope)
        self._current_envelope = new_envelope

    def peek_last(self) -> ContextEnvelope | None:
        self._assert_lock_held()
        return self._previous_envelopes[-1] if self._previous_envelopes else None

    def consume_last(self) -> ContextEnvelope:
        self._assert_lock_held()
        if not self._previous_envelopes:
            raise IndexError("No previous envelopes to consume")
        return self._previous_envelopes.pop()

    def has_history(self) -> bool:
        """Check if there are previous envelopes to rollback to under lock."""
        self._assert_lock_held()
        return len(self._previous_envelopes) > 0
