"""Relay context pipeline for signed, reversible agent orchestration.

Owns: pipeline orchestration, snapshot management, budget enforcement.
Does NOT: define agent behaviour, manage prompts, implement LLMs, or implement slicing.
"""

from relay.budget import HardCapEnforcer, TokenCounter
from relay.context_broker import ContextBroker, create_context_broker
from relay.core_pipeline import CoreRelayPipeline
from relay.envelope import ContextEnvelope
from relay.parallel import ForkResult, ForkSpec, JoinStrategy
from relay.pipeline_rollback import RollbackHandler
from relay.pipeline_state import PipelineState
from relay.slicer import AgentManifest, SlicePacker
from relay.snapshot import LocalFileSnapshotStore
from relay.snapshot_protocol import SnapshotStore
from relay.types import ErrorCode, Failure, Result, RollbackSuccess, Success, __version__
from relay.validator import HandoffValidator

__all__: list[str] = [
    "AgentManifest",
    "ContextBroker",
    "ContextEnvelope",
    "CoreRelayPipeline",
    "create_context_broker",
    "ErrorCode",
    "Failure",
    "ForkResult",
    "ForkSpec",
    "HandoffValidator",
    "HardCapEnforcer",
    "JoinStrategy",
    "PipelineState",
    "Result",
    "RollbackHandler",
    "RollbackSuccess",
    "SlicePacker",
    "LocalFileSnapshotStore",
    "SnapshotStore",
    "Success",
    "TokenCounter",
    "__version__",
]