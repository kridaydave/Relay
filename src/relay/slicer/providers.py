from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for generating embeddings from text.

    No concrete implementation ships with Relay - bring your own embedding model.
    """

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for the given text."""
        ...