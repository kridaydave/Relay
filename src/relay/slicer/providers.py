"""Embedding provider protocol and slice packer interface for Relay.

Owns: EmbeddingProvider and SlicePacker contract definitions.
Does NOT: implement embedding models, manage vector stores, or perform packing.
"""

from typing import Any, Protocol, runtime_checkable

from relay.types import Result


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for text embedding implementations.

    Implementations must provide a method to convert text into
    vector embeddings for similarity calculations.
    """

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for the given text."""
        ...


@runtime_checkable
class SlicePacker(Protocol):
    """Protocol for context slice packing strategies.

    Implementations select a subset of payload sections within
    manifest constraints (max_tokens, reads/writes).
    """

    def pack(
        self, payload: dict[str, Any], manifest: Any
    ) -> Result[dict[str, Any]]:
        """Pack context based on strategy.

        Args:
            payload: Dictionary of section_key -> section_content.
            manifest: Agent manifest defining constraints.

        Returns:
            Success with selected subset of payload sections, or Failure on error.
        """
        ...