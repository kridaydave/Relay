"""Embedding provider protocol for relevance-based slice selection.

Owns: EmbeddingProvider contract definition for text-to-vector conversion.
Does NOT: implement embedding models, manage vector stores, or perform similarity search.
"""

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