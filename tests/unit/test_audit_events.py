"""Unit tests for relay.audit.events — 17 event types, AuditOutcome enum."""

from datetime import datetime

import pytest

from relay.audit.events import (
    AuditEvent,
    AuditOutcome,
    BranchReceipt,
    BudgetCheckFailed,
    BudgetCheckPassed,
    ForkCompleted,
    ForkStarted,
    JoinCompleted,
    PipelineClosed,
    PipelineCreated,
    RollbackCompleted,
    RollbackTriggered,
    SignatureVerificationPassed,
    SignatureVerificationStale,
    SnapshotSaved,
    StepExecutionFailed,
    StepExecutionStarted,
    StepExecutionSucceeded,
    ValidationContradiction,
    ValidationPassed,
)


class TestAuditEvents:
    """Verify all 17 event types construct correctly with required fields."""

    def test_pipeline_created_has_correct_event_type_when_constructed(self) -> None:
        """PipelineCreated must have event_type 'pipeline_created'."""
        event = PipelineCreated(pipeline_id="test-123")
        assert event.event_type == "pipeline_created"

    def test_pipeline_created_carries_relay_version_and_storage_path_when_provided(self) -> None:
        """When provided, relay_version and storage_path must be stored."""
        event = PipelineCreated(
            pipeline_id="test-123",
            relay_version="1.0",
            storage_path="./data",
        )
        assert event.relay_version == "1.0"
        assert event.storage_path == "./data"

    def test_pipeline_closed_has_correct_event_type_when_constructed(self) -> None:
        """PipelineClosed must have event_type 'pipeline_closed'."""
        event = PipelineClosed(pipeline_id="test-123")
        assert event.event_type == "pipeline_closed"

    def test_step_execution_started_has_correct_event_type_when_constructed(self) -> None:
        """StepExecutionStarted must have event_type 'step_execution_started'."""
        event = StepExecutionStarted(pipeline_id="test-123", step=1)
        assert event.event_type == "step_execution_started"

    def test_step_execution_started_has_adapter_and_agent_when_provided(self) -> None:
        """StepExecutionStarted must carry adapter_name and agent_name."""
        event = StepExecutionStarted(
            pipeline_id="test-123",
            step=1,
            adapter_name="test-adapter",
            agent_name="test-agent",
        )
        assert event.adapter_name == "test-adapter"
        assert event.agent_name == "test-agent"

    def test_step_execution_succeeded_has_correct_event_type_when_constructed(self) -> None:
        """StepExecutionSucceeded must have event_type 'step_execution_succeeded'."""
        event = StepExecutionSucceeded(pipeline_id="test-123", step=1)
        assert event.event_type == "step_execution_succeeded"

    def test_step_execution_failed_has_correct_event_type_when_constructed(self) -> None:
        """StepExecutionFailed must have event_type 'step_execution_failed'."""
        event = StepExecutionFailed(pipeline_id="test-123", step=1)
        assert event.event_type == "step_execution_failed"

    def test_step_execution_failed_carries_error_code_when_provided(self) -> None:
        """StepExecutionFailed must store error_code when provided."""
        event = StepExecutionFailed(
            pipeline_id="test-123", step=1, error_code="BUDGET_EXCEEDED"
        )
        assert event.error_code == "BUDGET_EXCEEDED"

    def test_budget_check_passed_has_correct_event_type_when_constructed(self) -> None:
        """BudgetCheckPassed must have event_type 'budget_check_passed'."""
        event = BudgetCheckPassed(pipeline_id="test-123", step=1)
        assert event.event_type == "budget_check_passed"

    def test_budget_check_failed_has_correct_event_type_when_constructed(self) -> None:
        """BudgetCheckFailed must have event_type 'budget_check_failed'."""
        event = BudgetCheckFailed(pipeline_id="test-123", step=1)
        assert event.event_type == "budget_check_failed"

    def test_budget_check_failed_carries_budget_used_and_limit_when_constructed(self) -> None:
        """BudgetCheckFailed must store budget_used and budget_limit."""
        event = BudgetCheckFailed(
            pipeline_id="test-123", step=1, budget_used=5000, budget_limit=8000
        )
        assert event.budget_used == 5000
        assert event.budget_limit == 8000

    def test_validation_passed_has_correct_event_type_when_constructed(self) -> None:
        """ValidationPassed must have event_type 'validation_passed'."""
        event = ValidationPassed(pipeline_id="test-123", step=1)
        assert event.event_type == "validation_passed"

    def test_validation_contradiction_has_correct_event_type_when_constructed(self) -> None:
        """ValidationContradiction must have event_type 'validation_contradiction'."""
        event = ValidationContradiction(pipeline_id="test-123", step=1)
        assert event.event_type == "validation_contradiction"

    def test_validation_contradiction_has_diff_summary_when_provided(self) -> None:
        """ValidationContradiction must carry contradiction_type and diff_summary."""
        event = ValidationContradiction(
            pipeline_id="test-123",
            step=1,
            contradiction_type="entity_mismatch",
            diff_summary="Agent output contradicts in 3 fields",
        )
        assert event.contradiction_type == "entity_mismatch"
        assert event.diff_summary == "Agent output contradicts in 3 fields"

    def test_rollback_triggered_has_correct_event_type_when_constructed(self) -> None:
        """RollbackTriggered must have event_type 'rollback_triggered'."""
        event = RollbackTriggered(pipeline_id="test-123", step=1)
        assert event.event_type == "rollback_triggered"

    def test_rollback_completed_has_correct_event_type_when_constructed(self) -> None:
        """RollbackCompleted must have event_type 'rollback_completed'."""
        event = RollbackCompleted(pipeline_id="test-123", step=1)
        assert event.event_type == "rollback_completed"

    def test_rollback_completed_carries_restored_step_and_snapshot_id_when_provided(self) -> None:
        """RollbackCompleted must store restored_step and snapshot_id."""
        event = RollbackCompleted(
            pipeline_id="test-123", step=2, restored_step=1, snapshot_id="snap_abc"
        )
        assert event.restored_step == 1
        assert event.snapshot_id == "snap_abc"

    def test_fork_started_has_correct_event_type_when_constructed(self) -> None:
        """ForkStarted must have event_type 'fork_started'."""
        event = ForkStarted(pipeline_id="test-123", step=1)
        assert event.event_type == "fork_started"

    def test_fork_started_carries_fork_count_when_provided(self) -> None:
        """ForkStarted must store fork_count when provided."""
        event = ForkStarted(pipeline_id="test-123", step=1, fork_count=3)
        assert event.fork_count == 3

    def test_fork_completed_has_correct_event_type_when_constructed(self) -> None:
        """ForkCompleted must have event_type 'fork_completed'."""
        event = ForkCompleted(pipeline_id="test-123", step=1)
        assert event.event_type == "fork_completed"

    def test_join_completed_has_correct_event_type_when_constructed(self) -> None:
        """JoinCompleted must have event_type 'join_completed'."""
        event = JoinCompleted(pipeline_id="test-123", step=1)
        assert event.event_type == "join_completed"

    def test_snapshot_saved_has_correct_event_type_when_constructed(self) -> None:
        """SnapshotSaved must have event_type 'snapshot_saved'."""
        event = SnapshotSaved(pipeline_id="test-123", step=1)
        assert event.event_type == "snapshot_saved"

    def test_snapshot_saved_has_snapshot_id_when_constructed(self) -> None:
        """SnapshotSaved must carry snapshot_id and snapshot_size_bytes."""
        event = SnapshotSaved(
            pipeline_id="test-123",
            step=1,
            snapshot_id="snap_xyz",
            snapshot_size_bytes=1024,
        )
        assert event.snapshot_id == "snap_xyz"
        assert event.snapshot_size_bytes == 1024

    def test_signature_verification_passed_has_correct_event_type_when_constructed(self) -> None:
        """SignatureVerificationPassed must have event_type 'signature_verification_passed'."""
        event = SignatureVerificationPassed(pipeline_id="test-123", step=1)
        assert event.event_type == "signature_verification_passed"

    def test_signature_verification_stale_has_correct_event_type_when_constructed(self) -> None:
        """SignatureVerificationStale must have event_type 'signature_verification_stale'."""
        event = SignatureVerificationStale(pipeline_id="test-123", step=1)
        assert event.event_type == "signature_verification_stale"

    def test_signature_verification_stale_carries_age_fields_when_constructed(self) -> None:
        """SignatureVerificationStale must store envelope_age_seconds and max_age_seconds."""
        event = SignatureVerificationStale(
            pipeline_id="test-123",
            step=1,
            envelope_age_seconds=90000.0,
            max_age_seconds=86400,
        )
        assert event.envelope_age_seconds == 90000.0
        assert event.max_age_seconds == 86400

    def test_event_is_frozen_when_mutation_is_attempted(self) -> None:
        """Frozen dataclass must raise AttributeError on mutation attempt."""
        event = PipelineCreated(pipeline_id="test-123")
        with pytest.raises(AttributeError):
            event.pipeline_id = "changed"  # type: ignore[misc]

    def test_audit_outcome_has_four_members_with_correct_values(self) -> None:
        """AuditOutcome enum must have exactly four members."""
        members = list(AuditOutcome)
        assert len(members) == 4
        assert AuditOutcome.SUCCESS.value == "success"
        assert AuditOutcome.FAILURE.value == "failure"
        assert AuditOutcome.ROLLBACK.value == "rollback"
        assert AuditOutcome.SKIPPED.value == "skipped"

    def test_timestamp_is_valid_iso_8601_format_when_parsed(self) -> None:
        """Timestamp must be a parseable ISO 8601 string."""
        event = PipelineCreated(pipeline_id="test-123")
        parsed = datetime.fromisoformat(event.timestamp)
        assert parsed is not None

    def test_all_events_have_timestamp_when_constructed(self) -> None:
        """Every event type must have a non-empty timestamp string."""
        events: list[AuditEvent] = [
            PipelineCreated(pipeline_id="p"),
            PipelineClosed(pipeline_id="p"),
            StepExecutionStarted(pipeline_id="p", step=1),
            StepExecutionSucceeded(pipeline_id="p", step=1),
            StepExecutionFailed(pipeline_id="p", step=1),
            BudgetCheckPassed(pipeline_id="p", step=1),
            BudgetCheckFailed(pipeline_id="p", step=1),
            ValidationPassed(pipeline_id="p", step=1),
            ValidationContradiction(pipeline_id="p", step=1),
            RollbackTriggered(pipeline_id="p", step=1),
            RollbackCompleted(pipeline_id="p", step=1),
            ForkStarted(pipeline_id="p", step=1),
            ForkCompleted(pipeline_id="p", step=1),
            JoinCompleted(pipeline_id="p", step=1),
            BranchReceipt(pipeline_id="p", step=1, fork_index=0, adapter_name="a"),
            SnapshotSaved(pipeline_id="p", step=1),
            SignatureVerificationPassed(pipeline_id="p", step=1),
            SignatureVerificationStale(pipeline_id="p", step=1),
        ]
        for e in events:
            assert e.timestamp, f"{e.event_type} has empty timestamp"
            datetime.fromisoformat(e.timestamp)

    def test_all_events_have_event_type_string_when_constructed(self) -> None:
        """Every event type must have event_type matching its class name in snake_case."""
        cases: list[tuple[AuditEvent, str]] = [
            (PipelineCreated(pipeline_id="p"), "pipeline_created"),
            (PipelineClosed(pipeline_id="p"), "pipeline_closed"),
            (StepExecutionStarted(pipeline_id="p", step=1), "step_execution_started"),
            (StepExecutionSucceeded(pipeline_id="p", step=1), "step_execution_succeeded"),
            (StepExecutionFailed(pipeline_id="p", step=1), "step_execution_failed"),
            (BudgetCheckPassed(pipeline_id="p", step=1), "budget_check_passed"),
            (BudgetCheckFailed(pipeline_id="p", step=1), "budget_check_failed"),
            (ValidationPassed(pipeline_id="p", step=1), "validation_passed"),
            (ValidationContradiction(pipeline_id="p", step=1), "validation_contradiction"),
            (RollbackTriggered(pipeline_id="p", step=1), "rollback_triggered"),
            (RollbackCompleted(pipeline_id="p", step=1), "rollback_completed"),
            (ForkStarted(pipeline_id="p", step=1), "fork_started"),
            (ForkCompleted(pipeline_id="p", step=1), "fork_completed"),
            (JoinCompleted(pipeline_id="p", step=1), "join_completed"),
            (BranchReceipt(pipeline_id="p", step=1, fork_index=0, adapter_name="a"), "branch_receipt"),
            (SnapshotSaved(pipeline_id="p", step=1), "snapshot_saved"),
            (SignatureVerificationPassed(pipeline_id="p", step=1), "signature_verification_passed"),
            (SignatureVerificationStale(pipeline_id="p", step=1), "signature_verification_stale"),
        ]
        for event, expected in cases:
            assert event.event_type == expected, f"{type(event).__name__}.event_type should be '{expected}', got '{event.event_type}'"

    def test_all_events_have_default_outcome_when_constructed(self) -> None:
        """Every event type must have a reasonable default outcome."""
        assert PipelineCreated(pipeline_id="p").outcome == AuditOutcome.SUCCESS
        assert PipelineClosed(pipeline_id="p").outcome == AuditOutcome.SUCCESS
        assert StepExecutionStarted(pipeline_id="p", step=1).outcome == AuditOutcome.SUCCESS
        assert StepExecutionFailed(pipeline_id="p", step=1).outcome == AuditOutcome.FAILURE
        assert BudgetCheckPassed(pipeline_id="p", step=1).outcome == AuditOutcome.SUCCESS
        assert BudgetCheckFailed(pipeline_id="p", step=1).outcome == AuditOutcome.FAILURE
        assert ValidationContradiction(pipeline_id="p", step=1).outcome == AuditOutcome.FAILURE
        assert RollbackTriggered(pipeline_id="p", step=1).outcome == AuditOutcome.ROLLBACK
        assert RollbackCompleted(pipeline_id="p", step=1).outcome == AuditOutcome.ROLLBACK
        assert SignatureVerificationStale(pipeline_id="p", step=1).outcome == AuditOutcome.FAILURE


class TestParallelAuditEvents:
    """Verify ForkStarted, ForkCompleted, JoinCompleted carry correct metadata."""

    def test_fork_started_event_has_fork_count_when_provided(self) -> None:
        """ForkStarted must carry fork_count metadata."""
        event = ForkStarted(pipeline_id="p", step=1, fork_count=3)
        assert event.event_type == "fork_started"
        assert event.fork_count == 3

    def test_fork_completed_event_has_forks_succeeded_when_provided(self) -> None:
        """ForkCompleted must carry forks_succeeded metadata."""
        event = ForkCompleted(pipeline_id="p", step=1, forks_succeeded=2)
        assert event.forks_succeeded == 2

    def test_join_completed_event_has_join_strategy_when_provided(self) -> None:
        """JoinCompleted must carry join_strategy metadata."""
        event = JoinCompleted(pipeline_id="p", step=1, join_strategy="first_wins")
        assert event.join_strategy == "first_wins"

    def test_parallel_events_are_frozen_when_mutation_attempted(self) -> None:
        """All three parallel event types must be immutable frozen dataclasses."""
        for event in (
            ForkStarted(pipeline_id="p", step=1),
            ForkCompleted(pipeline_id="p", step=1),
            JoinCompleted(pipeline_id="p", step=1),
        ):
            with pytest.raises(AttributeError):
                event.event_type = "mutated"  # type: ignore[misc]


class TestBranchReceipt:
    """Verify BranchReceipt constructs correctly with all fields."""

    def test_branch_receipt_has_correct_event_type_when_constructed(self) -> None:
        """BranchReceipt must have event_type 'branch_receipt'."""
        event = BranchReceipt(
            pipeline_id="p", step=1, fork_index=0, adapter_name="a",
        )
        assert event.event_type == "branch_receipt"

    def test_branch_receipt_carries_all_metadata_when_constructed(self) -> None:
        """BranchReceipt must store all metadata fields when provided."""
        event = BranchReceipt(
            pipeline_id="test-pipeline",
            step=3,
            fork_index=1,
            adapter_name="agent-b",
            parent_snapshot_hash="abc",
            final_snapshot_hash="def",
            agent_id="agent-b",
            policy_hash="manifest-hash-123",
            tools_used=("read_file", "search"),
            sections_read=("context",),
            sections_written=("output",),
            keys_added=("new_key",),
            keys_removed=("old_key",),
            join_strategy="UNION",
            merge_decision="included",
            conflict_keys=(),
            branch_success=True,
        )
        assert event.pipeline_id == "test-pipeline"
        assert event.step == 3
        assert event.fork_index == 1
        assert event.adapter_name == "agent-b"
        assert event.parent_snapshot_hash == "abc"
        assert event.final_snapshot_hash == "def"
        assert event.agent_id == "agent-b"
        assert event.policy_hash == "manifest-hash-123"
        assert event.tools_used == ("read_file", "search")
        assert event.sections_read == ("context",)
        assert event.sections_written == ("output",)
        assert event.keys_added == ("new_key",)
        assert event.keys_removed == ("old_key",)
        assert event.join_strategy == "UNION"
        assert event.merge_decision == "included"
        assert event.conflict_keys == ()
        assert event.branch_success is True
        assert event.branch_error == ""

    def test_branch_receipt_is_frozen_when_mutation_attempted(self) -> None:
        """Frozen dataclass must raise AttributeError on mutation attempt."""
        event = BranchReceipt(
            pipeline_id="p", step=1, fork_index=0, adapter_name="a",
        )
        with pytest.raises(AttributeError):
            event.fork_index = 99  # type: ignore[misc]

    def test_branch_receipt_carries_error_when_branch_failed(self) -> None:
        """BranchReceipt must carry branch_error when branch_success is False."""
        event = BranchReceipt(
            pipeline_id="p", step=1, fork_index=0, adapter_name="a",
            branch_success=False,
            branch_error="BUDGET_EXCEEDED",
        )
        assert event.branch_success is False
        assert event.branch_error == "BUDGET_EXCEEDED"
