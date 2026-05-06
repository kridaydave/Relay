"""Unit tests for relay.slicer module."""

from dataclasses import dataclass

import pytest

from relay.slicer.manifest import AgentManifest
from relay.slicer.packers import RecencySlicePacker, RelevanceSlicePacker, StructuralSlicePacker
from relay.slicer.providers import EmbeddingProvider


@dataclass
class FixedEmbeddingProvider:
    """EmbeddingProvider that returns a fixed vector."""

    vector: list[float]

    def embed(self, text: str) -> list[float]:
        return self.vector


class TestAgentManifest:
    def test_compute_hash_is_deterministic(self):
        m1 = AgentManifest("a1", frozenset({"x", "y"}), frozenset({"z"}), 1000)
        m2 = AgentManifest("a1", frozenset({"y", "x"}), frozenset({"z"}), 1000)
        assert m1.compute_hash() == m2.compute_hash()
        assert m1.compute_hash() == m1.compute_hash()

    def test_compute_hash_differs_for_different_reads(self):
        m1 = AgentManifest("a1", frozenset({"x"}), frozenset({"z"}), 1000)
        m2 = AgentManifest("a1", frozenset({"y"}), frozenset({"z"}), 1000)
        assert m1.compute_hash() != m2.compute_hash()


class TestRecencySlicePacker:
    def test_pack_selects_recent_sections(self):
        payload = {
            "section1": {"step": 1, "content": "old"},
            "section2": {"step": 2, "content": "recent"},
        }
        manifest = AgentManifest("agent1", frozenset(), frozenset(), 100)
        packer = RecencySlicePacker()

        result = packer.pack(payload, manifest)

        assert "section1" in result
        assert "section2" in result

    def test_pack_respects_max_tokens(self):
        payload = {
            "section1": {"step": 1, "_est_tokens": 50, "content": "a"},
            "section2": {"step": 2, "_est_tokens": 60, "content": "b"},
        }
        manifest = AgentManifest("agent1", frozenset(), frozenset(), 80)
        packer = RecencySlicePacker()

        result = packer.pack(payload, manifest)

        assert len(result) == 1


class TestStructuralSlicePacker:
    def test_pack_only_selected_sections(self):
        payload = {
            "allowed": {"data": "ok"},
            "forbidden": {"data": "no"},
        }
        manifest = AgentManifest("agent1", frozenset({"allowed"}), frozenset(), 100)
        packer = StructuralSlicePacker()

        result = packer.pack(payload, manifest)

        assert "allowed" in result
        assert "forbidden" not in result

    def test_pack_raises_on_missing_section(self):
        payload = {"other": {"data": "ok"}}
        manifest = AgentManifest("agent1", frozenset({"missing"}), frozenset(), 100)
        packer = StructuralSlicePacker()

        with pytest.raises(KeyError):
            packer.pack(payload, manifest)


class TestRelevanceSlicePacker:
    def test_pack_ranks_by_relevance(self):
        payload = {
            "match": {"content": "apple banana cherry"},
            "no_match": {"content": "xyz abc"},
        }
        manifest = AgentManifest("agent1", frozenset(), frozenset(), 100)
        provider = FixedEmbeddingProvider([1.0, 0.0, 0.0])
        packer = RelevanceSlicePacker(provider)

        result = packer.pack(payload, manifest)

        assert "match" in result

    def test_embedding_provider_protocol(self):
        provider = FixedEmbeddingProvider([1.0, 0.0])
        assert isinstance(provider, EmbeddingProvider)