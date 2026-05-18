"""Structured audit logging for Relay pipeline lifecycle.

Owns: AuditSink Protocol, 17 typed event types, default JSON logging sink, payload redactor.
Does NOT: perform any pipeline logic, capture timing separately from ISO timestamps, or
         handle sink failures (fire-and-forget per D-06).
"""

from relay.audit.events import (
    AuditEvent,
    AuditOutcome,
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
from relay.audit.redactor import PayloadRedactor
from relay.audit.sink import AuditSink, JsonLogSink

__all__ = [
    "AuditEvent",
    "AuditOutcome",
    "AuditSink",
    "JsonLogSink",
    "PayloadRedactor",
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
