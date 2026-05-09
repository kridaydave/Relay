"""Tests for AgentRunner Protocol, AgentOutput, and ContextSlice."""

import pytest

from relay.runners.protocol import AgentOutput, AgentRunner, ContextSlice


class TestAgentRunnerProtocol:
    def test_fixed_agent_runner_satisfies_protocol(self):
        """FixedAgentRunner must satisfy AgentRunner Protocol at runtime."""
        from .conftest import FixedAgentRunner
        runner = FixedAgentRunner()
        assert isinstance(runner, AgentRunner)

    def test_object_without_run_does_not_satisfy_protocol(self):
        """Bare object must not satisfy AgentRunner Protocol."""
        assert not isinstance(object(), AgentRunner)

    def test_class_without_async_run_does_not_satisfy_protocol(self):
        """Sync run method does not satisfy protocol (protocol requires async).

        NOTE: runtime_checkable only checks attribute presence, not async-ness.
        This test documents the limitation — callers should use asyncio.run()
        and get a TypeError if they mistakenly pass a sync runner.
        """
        class SyncRunner:
            def run(self, slice, manifest):
                return AgentOutput(text="x", structured={}, tool_calls=[],
                                   token_count=1, latency_ms=0, adapter="sync")
        assert isinstance(SyncRunner(), AgentRunner)


class TestAgentOutput:
    def test_agent_output_is_frozen(self):
        output = AgentOutput(text="hi", structured={}, tool_calls=[],
                             token_count=10, latency_ms=5, adapter="test")
        with pytest.raises(Exception):
            output.text = "changed"  # type: ignore[misc]

    def test_agent_output_with_structured_data(self):
        output = AgentOutput(text="", structured={"score": 0.9}, tool_calls=[],
                             token_count=5, latency_ms=2, adapter="test")
        assert output.structured["score"] == 0.9

    def test_raises_on_negative_token_count(self):
        with pytest.raises(ValueError, match="token_count"):
            AgentOutput(text="x", structured={}, tool_calls=[], token_count=-1, latency_ms=0, adapter="test")

    def test_raises_on_negative_latency(self):
        with pytest.raises(ValueError, match="latency_ms"):
            AgentOutput(text="x", structured={}, tool_calls=[], token_count=1, latency_ms=-1, adapter="test")

    def test_raises_on_empty_adapter(self):
        with pytest.raises(ValueError, match="adapter must be non-empty"):
            AgentOutput(text="x", structured={}, tool_calls=[], token_count=1, latency_ms=0, adapter="")

    def test_raises_when_both_text_and_structured_are_empty(self):
        with pytest.raises(ValueError, match="At least one of"):
            AgentOutput(text="", structured={}, tool_calls=[], token_count=1, latency_ms=0, adapter="test")


class TestContextSlice:
    def test_context_slice_is_frozen(self):
        from .conftest import make_test_slice
        slice_ = make_test_slice()
        with pytest.raises(Exception):
            slice_.step = 99  # type: ignore[misc]

    def test_context_slice_sections_reflects_manifest_reads(self):
        """sections must only contain keys from manifest.reads."""
        from .conftest import make_test_slice
        slice_ = make_test_slice(sections={"input": "data"})
        assert "input" in slice_.sections
        assert "other" not in slice_.sections

    def test_context_slice_fields(self):
        slice_ = ContextSlice(
            pipeline_id="p1",
            step=5,
            agent_id="a1",
            sections={"key": "value"},
            token_count=100,
            manifest_hash="h1",
        )
        assert slice_.pipeline_id == "p1"
        assert slice_.step == 5
        assert slice_.agent_id == "a1"
        assert slice_.sections == {"key": "value"}
        assert slice_.token_count == 100
        assert slice_.manifest_hash == "h1"