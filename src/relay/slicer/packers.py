"""Slice packer implementations for context selection strategies.

Owns: RecencySlicePacker, StructuralSlicePacker, RelevanceSlicePacker.
Does NOT: own EmbeddingProvider protocol,
          or count tokens precisely (delegates to envelope.estimate_tokens).
"""

from abc import ABC, abstractmethod
import json
from typing import Any
from math import sqrt

from relay.envelope import estimate_tokens
from relay.slicer.manifest import AgentManifest
from relay.slicer.providers import EmbeddingProvider
from relay.types import ErrorCode, Failure, Result, Success


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors without numpy."""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sqrt(sum(x**2 for x in a))
    magnitude_b = sqrt(sum(x**2 for x in b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0
    return dot_product / (magnitude_a * magnitude_b)


class SlicePacker(ABC):
    """Base class for slice packer strategies."""

    @abstractmethod
    def pack(
        self, payload: dict[str, Any], manifest: AgentManifest
    ) -> Result[dict[str, Any]]:
        """Pack context based on strategy.

        Args:
            payload: Dictionary of section_key -> section_content.
            manifest: Agent manifest defining constraints.

        Returns:
            Success with selected subset of payload sections, or Failure on error.
        """


class RecencySlicePacker(SlicePacker):
    """Selects most recent sections by step order until max_tokens consumed.

    Sections are ordered by their numeric suffix (e.g., section_1, section_2).
    Uses token estimation via simple character count divided by 3.
    """

    def pack(
        self, payload: dict[str, Any], manifest: AgentManifest
    ) -> Result[dict[str, Any]]:
        """Pack context based on recency.

        Approximates token count using character count divided by 3.

        Returns:
            Success with selected subset of payload sections.
        """
        sorted_keys = sorted(
            payload.keys(),
            key=lambda k: (
                int(k.split("_")[-1]) if "_" in k and k.split("_")[-1].isdigit() else 0
            ),
            reverse=True,
        )

        result: dict[str, Any] = {}
        used_tokens = 0

        for key in sorted_keys:
            section_text = payload[key]
            section_tokens = estimate_tokens({key: section_text})

            if used_tokens + section_tokens > manifest.max_tokens:
                if result:
                    continue
                return Success({})

            result[key] = section_text
            used_tokens += section_tokens

        return Success(result)


class StructuralSlicePacker(SlicePacker):
    """Selects only sections named in AgentManifest.reads.

    Returns Failure if reads names a section absent from payload.
    """

    def pack(
        self, payload: dict[str, Any], manifest: AgentManifest
    ) -> Result[dict[str, Any]]:
        """Pack context based on manifest reads.

        Returns:
            Success with selected subset, or Failure if section missing.
        """
        missing = [key for key in manifest.reads if key not in payload]
        if missing:
            return Failure(
                reason=f"Manifest declares read for sections {missing} but they do not exist in payload",
                code=ErrorCode.MISSING_SECTIONS,
            )
        return Success({key: payload[key] for key in sorted(manifest.reads)})


class RelevanceSlicePacker(SlicePacker):
    """Ranks sections by cosine similarity to query, returns top sections within max_tokens.

    Uses token estimation via character count divided by 3.
    Requires injected EmbeddingProvider. Propagates provider exceptions unchanged.
    """

    def __init__(self, provider: EmbeddingProvider):
        self.provider = provider

    def pack(
        self, payload: dict[str, Any], manifest: AgentManifest
    ) -> Result[dict[str, Any]]:
        """Pack context based on relevance scores.

        Approximates token count using character count divided by 3.

        Returns:
            Success with selected subset of payload sections.
        """
        if not payload:
            return Success({})

        query_embedding = self.provider.embed(manifest.task_description)
        section_embeddings = {
            key: self.provider.embed(text) for key, text in payload.items()
        }

        similarities = []
        for key, embedding in section_embeddings.items():
            sim = _cosine_similarity(query_embedding, embedding)
            section_tokens = estimate_tokens({key: payload[key]})
            similarities.append((key, sim, section_tokens))

        similarities.sort(key=lambda x: x[1], reverse=True)

        result: dict[str, Any] = {}
        used_tokens = 0

        for key, _, section_tokens in similarities:
            if used_tokens + section_tokens > manifest.max_tokens:
                if result:
                    continue
                return Success({})
            result[key] = payload[key]
            used_tokens += section_tokens

        return Success(result)
