"""Shared test fixtures and test doubles for Relay tests."""

from dataclasses import dataclass


@dataclass
class FixedCounter:
    """TokenCounter that always returns a fixed value."""

    value: int

    def count(self, text: str) -> int:
        return self.value


@dataclass
class FixedEmbeddingProvider:
    """EmbeddingProvider that always returns a fixed vector."""

    vector: list[float]

    def embed(self, text: str) -> list[float]:
        return self.vector