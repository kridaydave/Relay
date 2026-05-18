"""Shared test fixtures and test doubles for Relay tests."""

from dataclasses import dataclass, field

from relay.audit.events import AuditEvent


@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""

    value: int

    def count(self, text: str) -> int:
        return self.value

    def close(self) -> None:
        pass

    def __enter__(self) -> "FixedCounter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass
class FixedAuditSink:
    """AuditSink that collects events for test assertions."""

    events: list[AuditEvent] = field(default_factory=list)

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass

    @property
    def emitted_types(self) -> list[str]:
        return [e.event_type for e in self.events]


@dataclass
class FixedEmbeddingProvider:
    """EmbeddingProvider that always returns a fixed vector."""

    vector: list[float]

    def embed(self, text: str) -> list[float]:
        return self.vector