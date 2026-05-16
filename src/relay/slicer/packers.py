"""Slice packer implementations for context selection strategies.

Owns: RecencySlicePacker, StructuralSlicePacker, RelevanceSlicePacker.
Does NOT: own EmbeddingProvider protocol or count tokens precisely.
"""

import json
from math import sqrt

from relay.envelope import estimate_tokens
from relay.slicer.manifest import AgentManifest
from relay.slicer.providers import EmbeddingProvider
from relay.types import ErrorCode, Failure, JSONDict, Result, Success


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors without numpy."""
    if len(a) != len(b):
        raise ValueError(
            f"Vector dimension mismatch: {len(a)} vs {len(b)}. "
            "Embedding providers must return consistent dimensions."
        )

    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sqrt(sum(x**2 for x in a))
    magnitude_b = sqrt(sum(x**2 for x in b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0
    return dot_product / (magnitude_a * magnitude_b)


class RecencySlicePacker:
    """Selects most recent sections by step order, slicing until max_tokens.

    Sections are ordered by their numeric suffix (e.g., section_1, section_2)
    and only the newest sections that fit within the token budget are returned.
    Uses token estimation via simple character count divided by 3.
    """

    def pack(
        self, payload: JSONDict, manifest: AgentManifest
    ) -> Result[JSONDict]:
        """Slice the payload to retain only the most recent sections by recency.

        Approximates token count using character count divided by 3.

        Returns:
            Success with selected subset of payload sections.
        """
        def _recency_sort_key(k: str) -> tuple[int, int, str]:
            if "_" in k and k.split("_")[-1].isdigit():
                return (0, int(k.split("_")[-1]), k)
            return (1, 0, k)

        sorted_keys = sorted(payload.keys(), key=_recency_sort_key, reverse=True)

        result: JSONDict = {}
        used_tokens = 0

        for key in sorted_keys:
            section_text: object = payload[key]
            section_tokens = estimate_tokens(dict[str, object]({key: section_text}))

            if manifest.max_tokens is not None and used_tokens + section_tokens > manifest.max_tokens:
                break

            result[key] = section_text
            used_tokens += section_tokens

        return Success(result)


class StructuralSlicePacker:
    """Selects only sections named in AgentManifest.reads.

    Returns Failure if reads names a section absent from payload.
    """

    def pack(
        self, payload: JSONDict, manifest: AgentManifest
    ) -> Result[JSONDict]:
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
        return Success(dict[str, object]({key: payload[key] for key in sorted(manifest.reads)}))


class RelevanceSlicePacker:
    """Ranks sections by cosine similarity to query, returns top sections within max_tokens.

    Uses token estimation via character count divided by 3.
    Requires injected EmbeddingProvider. Propagates provider exceptions unchanged.
    """

    def __init__(self, provider: EmbeddingProvider):
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError(
                f"Expected an EmbeddingProvider, got {type(provider).__name__}. "
                "The provider must satisfy the EmbeddingProvider protocol."
            )
        self.provider = provider

    def pack(
        self, payload: JSONDict, manifest: AgentManifest
    ) -> Result[JSONDict]:
        """Pack context based on relevance scores.

        Approximates token count using character count divided by 3.

        Returns:
            Success with selected subset of payload sections.
        """
        if not payload:
            return Success(JSONDict())

        query_embedding = self.provider.embed(manifest.task_description)
        section_embeddings: dict[str, list[float]] = {
            key: self.provider.embed(
                json.dumps(text) if not isinstance(text, str) else text
            )
            for key, text in payload.items()
        }

        similarities: list[tuple[str, float, int]] = []
        for key, embedding in section_embeddings.items():
            sim = _cosine_similarity(query_embedding, embedding)
            section_tokens = estimate_tokens(dict[str, object]({key: payload[key]}))
            similarities.append((key, sim, section_tokens))

        def _sort_key(x: tuple[str, float, int]) -> float:
            return x[1]
        similarities.sort(key=_sort_key, reverse=True)

        result: JSONDict = {}
        used_tokens = 0

        for key, _, section_tokens in similarities:
            if manifest.max_tokens is not None and used_tokens + section_tokens > manifest.max_tokens:
                break

            result[key] = payload[key]
            used_tokens += section_tokens

        return Success(result)
