"""Unit tests for relay.slicer module."""

import pytest

from relay.slicer import (
    AgentManifest,
    EmbeddingProvider,
    RecencySlicePacker,
    RelevanceSlicePacker,
    StructuralSlicePacker,
)
from relay.types import Failure, Success, ErrorCode
from tests.conftest import FixedEmbeddingProvider


class TestAgentManifest:
    def test_compute_hash_deterministic(self):
        """Hash must be deterministic across calls and object reconstruction."""
        m1 = AgentManifest("a1", "test task", frozenset({"x", "y"}), frozenset({"z"}), 1000)
        m2 = AgentManifest("a1", "test task", frozenset({"y", "x"}), frozenset({"z"}), 1000)
        assert m1.compute_hash() == m2.compute_hash()
        assert m1.compute_hash() == m1.compute_hash()

    def test_manifest_is_hashable(self):
        """Frozen dataclass with frozenset fields must be hashable."""
        m = AgentManifest("a1", "test task", frozenset({"x"}), frozenset({"y"}), 1000)
        d = {m: "value"}
        assert d[m] == "value"

    def test_compute_hash_differs_for_different_manifests(self):
        """Different manifests must produce different hashes."""
        m1 = AgentManifest("a1", "test task", frozenset({"x"}), frozenset({"y"}), 1000)
        m2 = AgentManifest("a2", "test task different", frozenset({"x"}), frozenset({"y"}), 1000)
        assert m1.compute_hash() != m2.compute_hash()


class TestRecencySlicePacker:
    def test_empty_payload_returns_empty(self):
        """Empty payload returns Success with empty dict."""
        packer = RecencySlicePacker()
        payload: dict[str, str] = {}
        manifest = AgentManifest("a1", "test task", frozenset(), frozenset(), 100)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert result.value == {}
    def test_single_section_exceeds_max_tokens_returns_empty(self):
        """Single section exceeding max_tokens returns empty slice, not truncated."""
        packer = RecencySlicePacker()
        payload = {"section_1": "x" * 10000}
        manifest = AgentManifest("a1", "test task", frozenset(), frozenset(), 100)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert result.value == {}

    def test_selects_sections_until_max_tokens(self):
        """Selects sections in recency order until max_tokens consumed."""
        packer = RecencySlicePacker()
        payload = {
            "section_1": "a",
            "section_2": "b",
            "section_3": "c",
        }
        manifest = AgentManifest("a1", "test task", frozenset(), frozenset(), 20)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert "section_1" in result.value

    def test_selects_most_recent_under_budget_pressure(self):
        """RecencySlicePacker should select highest-numbered sections when budget exceeded."""
        packer = RecencySlicePacker()
        payload = {
            "section_1": "x" * 100,   # ~33 tokens
            "section_2": "x" * 100,   # ~33 tokens
            "section_3": "x" * 100,   # ~33 tokens
            "section_4": "x" * 100,   # ~33 tokens
            "section_5": "x" * 300,   # ~100 tokens - fits alone but pushes out oldest
        }
        manifest = AgentManifest("a1", "task", frozenset(), frozenset(), 130)

        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert "section_5" in result.value
        assert "section_1" not in result.value


class TestStructuralSlicePacker:
    def test_write_to_permitted_section_passes(self):
        """Selecting permitted sections passes without error."""
        packer = StructuralSlicePacker()
        payload = {"section_a": "content", "section_b": "content2"}
        manifest = AgentManifest("a1", "test task", frozenset(["section_a", "section_b"]), frozenset(), 1000)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert result.value == payload

    def test_missing_section_returns_failure(self):
        """Missing declared read section must return Failure."""
        packer = StructuralSlicePacker()
        payload = {"section_a": "content"}
        manifest = AgentManifest("a1", "test task", frozenset(["section_a", "section_b"]), frozenset(), 1000)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Failure)
        assert "section_b" in result.reason
        assert result.code == ErrorCode.MISSING_SECTIONS


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
        manifest = AgentManifest("a1", "test task", frozenset(), frozenset(), 1000)
        result = packer.pack(payload, manifest)
        assert isinstance(result, Success)
        assert len(result.value) == 2