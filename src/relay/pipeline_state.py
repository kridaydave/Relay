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

    @property
    def pipeline_id(self) -> str:
        return self._pipeline_id

    @property
    def snapshot_ids(self) -> dict[int, str]:
        return self._snapshot_ids

    def _assert_lock_held(self) -> None:
        """Assert _lock is held by the calling thread. Active only when __debug__ is True.

        Call at the top of every method that requires the lock.
        Disappears under python -O. Cost-free in tests.
        """
        if __debug__:
            if not self._lock.locked():
                raise AssertionError(
                    f"{self.__class__.__name__} mutation called without holding _lock. "
                    "Wrap the call site in `with self._state.transaction()`."
                )

    def current(self) -> ContextEnvelope | None:
        """Return the current envelope (no lock needed for read of None check)."""
        return self._current_envelope

    @contextmanager
    def transaction(self) -> Generator[ContextEnvelope | None, None, None]:
        """Context manager for safe lock acquisition and release.

        Yields the current envelope while holding the lock.
        Automatically acquires and releases the lock.
        """
        with self._lock:
            try:
                yield self._current_envelope
            finally:
                pass

    def get_previous_envelopes(self) -> list[ContextEnvelope]:
        """Return a copy of the previous envelopes list."""
        return list(self._previous_envelopes)

    def set_current(self, envelope: ContextEnvelope) -> None:
        """Set the current envelope (internal, caller holds lock)."""
        self._assert_lock_held()
        self._current_envelope = envelope

    def archive_and_set(self, new_envelope: ContextEnvelope) -> None:
        """Archive current envelope and set new one. Caller holds lock."""
        self._assert_lock_held()
        if self._current_envelope is not None:
            self._previous_envelopes.append(self._current_envelope)
        self._current_envelope = new_envelope

    def peek_last(self) -> ContextEnvelope | None:
        """Peek at the last envelope in history without removing it."""
        self._assert_lock_held()
        return self._previous_envelopes[-1] if self._previous_envelopes else None

    def consume_last(self) -> ContextEnvelope:
        """Remove and return the last envelope from history. Must be called AFTER successful restore."""
        self._assert_lock_held()
        return self._previous_envelopes.pop()

    def has_history(self) -> bool:
        """Check if there are previous envelopes to rollback to."""
        return len(self._previous_envelopes) > 0
