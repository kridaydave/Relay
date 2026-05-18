"""AuditSink Protocol and default JSON logging sink for Relay audit events.

Owns: AuditSink Protocol definition, JsonLogSink default implementation.
Does NOT: handle pipeline logic, perform payload redaction, or manage event types.
"""

import json
import logging
from typing import Protocol, cast, runtime_checkable

from relay.audit.events import AuditEvent
from relay.types import Closeable, JSONDict

logger = logging.getLogger(__name__)


@runtime_checkable
class AuditSink(Closeable, Protocol):
    """Protocol for audit event sinks.

    Implementations write events to a destination (log file, stdout,
    test buffer, etc.). All emit calls are fire-and-forget — errors
    must not propagate to the caller.
    """

    def emit(self, event: AuditEvent) -> None:
        """Write an audit event.

        Args:
            event: The fully-constructed audit event to record.

        Must NOT raise exceptions. On failure, log via
        logging.getLogger(__name__).error() and return.
        """
        ...

    def close(self) -> None:
        """Release any resources held by this sink."""
        ...


class JsonLogSink:
    """Default audit sink: JSON-formatted lines via stdlib logging.

    Formats each event as a single-line JSON object with ISO 8601
    timestamps. Uses json.dumps with default=str for dataclass fields.
    """

    def __init__(self, logger_name: str = "relay.audit") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, event: AuditEvent) -> None:
        """Serialize event to JSON and log at INFO level.

        Fire-and-forget per D-06. On failure, log at ERROR level
        and return without propagating.
        """
        try:
            record = json.dumps(cast(JSONDict, vars(event)), default=str, sort_keys=True)
            self._logger.info(record)
        except Exception:
            logger.error(
                "Failed to serialize audit event: %s",
                type(event).__name__,
                exc_info=True,
            )

    def close(self) -> None:
        """No-op for the default logging sink."""
        pass


__all__ = [
    "AuditSink",
    "JsonLogSink",
]
