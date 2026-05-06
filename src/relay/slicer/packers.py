from typing import Any

from relay.slicer.manifest import AgentManifest
from relay.slicer.providers import EmbeddingProvider


class RecencySlicePacker:
    """Selects most recent sections by step order until max_tokens consumed."""

    def pack(
        self,
        envelope_payload: dict[str, Any],
        manifest: AgentManifest,
    ) -> dict[str, Any]:
        """Pack context using recency strategy.

        Selects last N sections by step order until max_tokens consumed.
        Returns an empty dict if a single section exceeds max_tokens.
        """
        total_tokens = 0
        result = {}

        sorted_keys = sorted(envelope_payload.keys(), key=lambda k: envelope_payload.get(k, {}).get("step", 0))

        for key in sorted_keys:
            section = envelope_payload[key]
            section_tokens = section.get("_est_tokens", 0)
            if section_tokens == 0:
                section_tokens = self._estimate_tokens(section)

            if total_tokens + section_tokens > manifest.max_tokens:
                if not result:
                    import warnings

                    warnings.warn(
                        f"Single section '{key}' exceeds max_tokens ({manifest.max_tokens}). Returning empty slice."
                    )
                break

            result[key] = section
            total_tokens += section_tokens

        return result

    def _estimate_tokens(self, section: Any) -> int:
        import json

        json_str = json.dumps(section, sort_keys=True)
        return len(json_str) // 3


class StructuralSlicePacker:
    """Selects only sections named in AgentManifest.reads."""

    def pack(
        self,
        envelope_payload: dict[str, Any],
        manifest: AgentManifest,
    ) -> dict[str, Any]:
        """Pack context using structural strategy.

        Selects only sections named in manifest.reads.
        Raises KeyError if a declared read is missing from payload.
        """
        result = {}
        for key in manifest.reads:
            if key not in envelope_payload:
                raise KeyError(f"Manifest declares read '{key}' but section not found in payload")
            result[key] = envelope_payload[key]
        return result


class RelevanceSlicePacker:
    """Ranks sections by cosine similarity to a query."""

    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._provider = embedding_provider

    def pack(
        self,
        envelope_payload: dict[str, Any],
        manifest: AgentManifest,
    ) -> dict[str, Any]:
        """Pack context using relevance strategy.

        Ranks sections by cosine similarity to a query.
        Requires injected EmbeddingProvider.
        """
        query = manifest.agent_id
        query_embedding = self._provider.embed(query)

        scored = []
        for key, section in envelope_payload.items():
            section_text = str(section)
            section_embedding = self._provider.embed(section_text)
            similarity = self._cosine_similarity(query_embedding, section_embedding)
            section_tokens = self._estimate_tokens(section)
            scored.append((key, section, similarity, section_tokens))

        scored.sort(key=lambda x: x[2], reverse=True)

        total_tokens = 0
        result = {}
        for key, section, similarity, section_tokens in scored:
            if total_tokens + section_tokens > manifest.max_tokens:
                break
            result[key] = section
            total_tokens += section_tokens

        return result

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        return dot_product / (magnitude_a * magnitude_b)

    def _estimate_tokens(self, section: Any) -> int:
        import json

        json_str = json.dumps(section, sort_keys=True)
        return len(json_str) // 3