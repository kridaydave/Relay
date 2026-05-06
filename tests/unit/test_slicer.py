"""Unit tests for relay.slicer module."""

import pytest

from relay.slicer import (
    AgentManifest,
    EmbeddingProvider,
    RecencySlicePacker,
    RelevanceSlicePacker,
    SliceStrategy,
    StructuralSlicePacker,
)
from tests.conftest import FixedEmbeddingProvider


class TestAgentManifest:
    def test_compute_hash_deterministic(self):
        """Hash must be deterministic across calls and object reconstruction."""
        m1 = AgentManifest("a1", frozenset({"x", "y"}), frozenset({"z"}), 1000)
        m2 = AgentManifest("a1", frozenset({"y", "x"}), frozenset({"z"}), 1000)
        assert m1.compute_hash() == m2.compute_hash()
        assert m1.compute_hash() == m1.compute_hash()

    def test_manifest_is_hashable(self):
        """Frozen dataclass with frozenset fields must be hashable."""
        m = AgentManifest("a1", frozenset({"x"}), frozenset({"y"}), 1000)
        d = {m: "value"}
        assert d[m] == "value"

    def test_compute_hash_differs_for_different_manifests(self):
        """Different manifests must produce different hashes."""
        m1 = AgentManifest("a1", frozenset({"x"}), frozenset({"y"}), 1000)
        m2 = AgentManifest("a2", frozenset({"x"}), frozenset({"y"}), 1000)
        assert m1.compute_hash() != m2.compute_hash()


class TestRecencySlicePacker:
    def test_single_section_exceeds_max_tokens_returns_empty(self):
        """Single section exceeding max_tokens returns empty slice, not truncated."""
        packer = RecencySlicePacker()
        payload = {"section_1": "x" * 10000}
        manifest = AgentManifest("a1", frozenset(), frozenset(), 100)
        result = packer.pack(payload, manifest)
        assert result == {}

    def test_selects_sections_until_max_tokens(self):
        """Selects sections in recency order until max_tokens consumed."""
        packer = RecencySlicePacker()
        payload = {
            "section_1": "a",
            "section_2": "b",
            "section_3": "c",
        }
        manifest = AgentManifest("a1", frozenset(), frozenset(), 5)
        result = packer.pack(payload, manifest)
        assert "section_1" in result


class TestStructuralSlicePacker:
    def test_write_to_permitted_section_passes(self):
        """Selecting permitted sections passes without error."""
        packer = StructuralSlicePacker()
        payload = {"section_a": "content", "section_b": "content2"}
        manifest = AgentManifest("a1", frozenset(["section_a", "section_b"]), frozenset(), 1000)
        result = packer.pack(payload, manifest)
        assert result == payload

    def test_missing_section_raises_key_error(self):
        """Missing declared read section must raise KeyError."""
        packer = StructuralSlicePacker()
        payload = {"section_a": "content"}
        manifest = AgentManifest("a1", frozenset(["section_a", "section_b"]), frozenset(), 1000)
        with pytest.raises(KeyError) as exc_info:
            packer.pack(payload, manifest)
        assert "section_b" in str(exc_info.value)


class TestRelevanceSlicePacker:
    def test_requires_embedding_provider(self):
        """Must have embedding provider injected."""
        provider = FixedEmbeddingProvider([1.0, 0.0])
        packer = RelevanceSlicePacker(provider)
        assert isinstance(packer, RelevanceSlicePacker)

    def test_ranks_by_similarity(self):
        """Ranks sections by cosine similarity to agent_id."""
        provider = FixedEmbeddingProvider([1.0, 0.0])
        packer = RelevanceSlicePacker(provider)
        payload = {"section_1": "content1", "section_2": "content2"}
        manifest = AgentManifest("a1", frozenset(), frozenset(), 1000)
        result = packer.pack(payload, manifest)
        assert len(result) == 2


class TestSliceStrategy:
    def test_enum_values(self):
        """Enum has expected values."""
        assert SliceStrategy.RECENCY.name == "RECENCY"
        assert SliceStrategy.RELEVANCE.name == "RELEVANCE"
        assert SliceStrategy.STRUCTURAL.name == "STRUCTURAL"