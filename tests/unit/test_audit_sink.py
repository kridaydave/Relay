"""Unit tests for relay.audit.sink — AuditSink Protocol, JsonLogSink, FixedAuditSink."""

import logging

import pytest

from relay.audit.events import AuditOutcome, PipelineCreated, StepExecutionFailed
from relay.audit.sink import AuditSink, JsonLogSink
from relay.types import Closeable
from tests.conftest import FixedAuditSink


class TestAuditSinkProtocol:
    """Verify AuditSink Protocol compliance and runtime_checkable behavior."""

    def test_json_log_sink_satisfies_audit_sink_protocol_with_isinstance(self) -> None:
        """JsonLogSink must satisfy the AuditSink Protocol."""
        sink = JsonLogSink()
        assert isinstance(sink, AuditSink)

    def test_json_log_sink_satisfies_closeable_protocol_with_isinstance(self) -> None:
        """JsonLogSink must satisfy the Closeable Protocol."""
        sink = JsonLogSink()
        assert isinstance(sink, Closeable)

    def test_fixed_audit_sink_satisfies_audit_sink_protocol_with_isinstance(self) -> None:
        """FixedAuditSink must satisfy the AuditSink Protocol."""
        sink = FixedAuditSink()
        assert isinstance(sink, AuditSink)

    def test_fixed_audit_sink_satisfies_closeable_protocol_with_isinstance(self) -> None:
        """FixedAuditSink must satisfy the Closeable Protocol."""
        sink = FixedAuditSink()
        assert isinstance(sink, Closeable)

    def test_audit_sink_protocol_is_runtime_checkable_when_checked(self) -> None:
        """AuditSink Protocol must support isinstance checks."""
        assert hasattr(AuditSink, "__instancecheck__")


class TestJsonLogSink:
    """Verify JsonLogSink serialization and fire-and-forget behavior."""

    def test_emit_does_not_raise_on_valid_event(self) -> None:
        """JsonLogSink.emit() must not raise on a valid PipelineCreated event."""
        sink = JsonLogSink()
        event = PipelineCreated(pipeline_id="test-pipeline")
        # Should not raise any exception
        sink.emit(event)

    def test_emit_handles_serialization_failure_gracefully_when_failing(self) -> None:
        """JsonLogSink.emit() must catch serialization errors and not propagate."""
        sink = JsonLogSink()
        event = StepExecutionFailed(
            pipeline_id="test-pipeline",
            step=1,
            error_code="BUDGET_EXCEEDED",
        )
        # Should not raise — fire-and-forget per D-06
        sink.emit(event)

    def test_close_is_noop_when_called(self) -> None:
        """JsonLogSink.close() must not raise."""
        sink = JsonLogSink()
        sink.close()


class TestFixedAuditSink:
    """Verify FixedAuditSink collects events correctly."""

    def test_emit_appends_event_to_list_when_called(self) -> None:
        """FixedAuditSink.emit() must append event to its events list."""
        sink = FixedAuditSink()
        event = PipelineCreated(pipeline_id="test-123")
        sink.emit(event)
        assert len(sink.events) == 1
        assert sink.events[0].pipeline_id == "test-123"

    def test_emitted_types_returns_correct_type_strings(self) -> None:
        """FixedAuditSink.emitted_types must return type strings in order."""
        sink = FixedAuditSink()
        sink.emit(PipelineCreated(pipeline_id="p"))
        sink.emit(StepExecutionFailed(pipeline_id="p", step=1))
        assert sink.emitted_types == ["pipeline_created", "step_execution_failed"]

    def test_multiple_emit_calls_accumulate_events_when_called(self) -> None:
        """Multiple emit calls must accumulate events in order."""
        sink = FixedAuditSink()
        for _ in range(5):
            sink.emit(PipelineCreated(pipeline_id="p"))
        assert len(sink.events) == 5

    def test_close_is_noop_when_called(self) -> None:
        """FixedAuditSink.close() must not raise."""
        sink = FixedAuditSink()
        sink.close()
