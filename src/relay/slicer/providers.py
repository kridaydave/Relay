"""Embedding provider protocol for relevance-based slicing."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for text embedding implementations.

    Implementations must provide a method to convert text into
    vector embeddings for similarity calculations.
    """

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for the given text."""
        ...