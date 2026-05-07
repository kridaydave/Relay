"""Slice packer implementations for context selection strategies."""

import numpy as np

from relay.slicer.manifest import AgentManifest
from relay.slicer.providers import EmbeddingProvider


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors without numpy."""
    dot_product = np.dot(a, b)
    magnitude_a = np.linalg.norm(a)
    magnitude_b = np.linalg.norm(b)
    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0
    return dot_product / (magnitude_a * magnitude_b)


class SlicePacker:
    """Base class for slice packer strategies."""

    def pack(self, payload: dict[str, str], manifest: AgentManifest) -> dict[str, str]:
        """Pack context based on strategy.

        Args:
            payload: Dictionary of section_key -> section_content.
            manifest: Agent manifest defining constraints.

        Returns:
            Selected subset of payload sections.
        """
        raise NotImplementedError


class RecencySlicePacker(SlicePacker):
    """Selects most recent sections by step order until max_tokens consumed.

    Sections are ordered by their numeric suffix (e.g., section_1, section_2).
    Returns empty slice if a single section exceeds max_tokens.
    """

    def pack(self, payload: dict[str, str], manifest: AgentManifest) -> dict[str, str]:
        sorted_keys = sorted(
            payload.keys(),
            key=lambda k: (
                int(k.split("_")[-1]) if "_" in k and k.split("_")[-1].isdigit() else 0
            ),
        )

        result = {}
        used_tokens = 0

        for key in sorted_keys:
            section_text = payload[key]
            section_tokens = len(section_text) // 3

            if used_tokens + section_tokens > manifest.max_tokens:
                if result:
                    continue
                return {}

            result[key] = section_text
            used_tokens += section_tokens

        return result


class StructuralSlicePacker(SlicePacker):
    """Selects only sections named in AgentManifest.reads.

    Raises KeyError if reads names a section absent from payload.
    """

    def pack(self, payload: dict[str, str], manifest: AgentManifest) -> dict[str, str]:
        result = {}
        for key in manifest.reads:
            if key not in payload:
                raise KeyError(
                    f"Manifest declares read for section '{key}' but it does not exist in payload"
                )
            result[key] = payload[key]
        return result


class RelevanceSlicePacker(SlicePacker):
    """Ranks sections by cosine similarity to query, returns top sections within max_tokens.

    Requires injected EmbeddingProvider. Propagates provider exceptions unchanged.
    """

    def __init__(self, provider: EmbeddingProvider):
        self.provider = provider

    def pack(self, payload: dict[str, str], manifest: AgentManifest) -> dict[str, str]:
        if not payload:
            return {}

        query_embedding = self.provider.embed(manifest.agent_id)
        section_embeddings = {
            key: self.provider.embed(text) for key, text in payload.items()
        }

        similarities = []
        for key, embedding in section_embeddings.items():
            sim = _cosine_similarity(query_embedding, embedding)
            similarities.append((key, sim, len(payload[key]) // 3))

        similarities.sort(key=lambda x: x[1], reverse=True)

        result = {}
        used_tokens = 0

        for key, _, section_tokens in similarities:
            if used_tokens + section_tokens > manifest.max_tokens:
                if result:
                    continue
                return {}
            result[key] = payload[key]
            used_tokens += section_tokens

        return result
