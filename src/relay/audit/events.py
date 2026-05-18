"""17 typed structured audit event types for Relay pipeline lifecycle.

Owns: AuditOutcome enum, all 17 frozen dataclass event types, AuditEvent type alias.
Does NOT: handle serialization, perform pipeline logic, or capture timing separately from ISO timestamps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AuditOutcome(str, Enum):
    """Outcome of a pipeline operation."""

    SUCCESS = "success"
    FAILURE = "failure"
    ROLLBACK = "rollback"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelineCreated:
    """Emitted when a pipeline is created."""

    event_type: str = field(default="pipeline_created", init=False)
    pipeline_id: str
    step: int = 0
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    relay_version: str = ""
    storage_path: str = ""


@dataclass(frozen=True)
class PipelineClosed:
    """Emitted when a pipeline is closed."""

    event_type: str = field(default="pipeline_closed", init=False)
    pipeline_id: str
    step: int = 0
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0


@dataclass(frozen=True)
class StepExecutionStarted:
    """Emitted when a step begins execution."""

    event_type: str = field(default="step_execution_started", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    adapter_name: str = ""
    agent_name: str = ""


@dataclass(frozen=True)
class StepExecutionSucceeded:
    """Emitted when a step completes successfully."""

    event_type: str = field(default="step_execution_succeeded", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    adapter_name: str = ""
    agent_name: str = ""


@dataclass(frozen=True)
class StepExecutionFailed:
    """Emitted when a step fails."""

    event_type: str = field(default="step_execution_failed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.FAILURE
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    adapter_name: str = ""
    agent_name: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class BudgetCheckPassed:
    """Emitted when a budget check passes."""

    event_type: str = field(default="budget_check_passed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    budget_used: int = 0
    budget_limit: int = 0


@dataclass(frozen=True)
class BudgetCheckFailed:
    """Emitted when a budget check fails."""

    event_type: str = field(default="budget_check_failed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.FAILURE
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    budget_used: int = 0
    budget_limit: int = 0


@dataclass(frozen=True)
class ValidationPassed:
    """Emitted when handoff validation passes."""

    event_type: str = field(default="validation_passed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ValidationContradiction:
    """Emitted when a handoff validation contradiction is detected."""

    event_type: str = field(default="validation_contradiction", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.FAILURE
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    contradiction_type: str = ""
    diff_summary: str = ""


@dataclass(frozen=True)
class RollbackTriggered:
    """Emitted when a rollback is triggered."""

    event_type: str = field(default="rollback_triggered", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.ROLLBACK
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class RollbackCompleted:
    """Emitted when a rollback completes successfully."""

    event_type: str = field(default="rollback_completed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.ROLLBACK
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    restored_step: int = 0
    snapshot_id: str = ""


@dataclass(frozen=True)
class ForkStarted:
    """Emitted when parallel forks begin execution."""

    event_type: str = field(default="fork_started", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    fork_count: int = 0


@dataclass(frozen=True)
class ForkCompleted:
    """Emitted when parallel forks complete execution."""

    event_type: str = field(default="fork_completed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    forks_succeeded: int = 0


@dataclass(frozen=True)
class JoinCompleted:
    """Emitted when a join strategy completes."""

    event_type: str = field(default="join_completed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    join_strategy: str = ""


@dataclass(frozen=True)
class SnapshotSaved:
    """Emitted when a snapshot is saved."""

    event_type: str = field(default="snapshot_saved", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    snapshot_id: str = ""
    snapshot_size_bytes: int = 0


@dataclass(frozen=True)
class SignatureVerificationPassed:
    """Emitted when signature verification passes."""

    event_type: str = field(default="signature_verification_passed", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0


@dataclass(frozen=True)
class SignatureVerificationStale:
    """Emitted when signature verification fails due to stale age."""

    event_type: str = field(default="signature_verification_stale", init=False)
    pipeline_id: str
    step: int
    outcome: AuditOutcome = AuditOutcome.FAILURE
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    latency_ms: float = 0.0
    envelope_age_seconds: float = 0.0
    max_age_seconds: int = 0


type AuditEvent = (
    PipelineCreated
    | PipelineClosed
    | StepExecutionStarted
    | StepExecutionSucceeded
    | StepExecutionFailed
    | BudgetCheckPassed
    | BudgetCheckFailed
    | ValidationPassed
    | ValidationContradiction
    | RollbackTriggered
    | RollbackCompleted
    | ForkStarted
    | ForkCompleted
    | JoinCompleted
    | SnapshotSaved
    | SignatureVerificationPassed
    | SignatureVerificationStale
)

__all__ = [
    "AuditEvent",
    "AuditOutcome",
    "PipelineCreated",
    "PipelineClosed",
    "StepExecutionStarted",
    "StepExecutionSucceeded",
    "StepExecutionFailed",
    "BudgetCheckPassed",
    "BudgetCheckFailed",
    "ValidationPassed",
    "ValidationContradiction",
    "RollbackTriggered",
    "RollbackCompleted",
    "ForkStarted",
    "ForkCompleted",
    "JoinCompleted",
    "SnapshotSaved",
    "SignatureVerificationPassed",
    "SignatureVerificationStale",
]
