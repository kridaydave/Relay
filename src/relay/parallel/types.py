"""Parallel execution types for Relay v0.4.

Owns: JoinStrategy enum, ForkSpec, ForkResult.
Does NOT: implement join logic, execute adapters, or manage pipeline state.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from relay.runners.protocol import AgentOutput
from relay.types import Failure, Result

if TYPE_CHECKING:
    from relay.validator import ValidationResult
    from relay.slicer.manifest import AgentManifest


class JoinStrategy(str, Enum):
    """Strategy for merging parallel fork outputs."""
    UNION      = "UNION"
    VOTE       = "VOTE"
    FIRST_WINS = "FIRST_WINS"


@dataclass(frozen=True)
class ForkSpec:
    """Specification for one fork in a parallel step.

    Owns: the adapter name and manifest that define one fork's execution.
    Does NOT: execute the adapter, hold results, or reference pipeline state.
    """
    adapter_name: str
    manifest: "AgentManifest"


@dataclass(frozen=True)
class ForkResult:
    """Result from one fork's execution and validation.

    Owns: the fork's identity, output, and validation result.
    Does NOT: write to pipeline state or reference the registry.

    A ForkResult is always created — even for failed forks — so join
    strategies have a complete picture of what happened.
    """
    fork_index: int
    adapter_name: str
    success: bool
    agent_output: "AgentOutput | None"
    validation: "ValidationResult | None"
    failure: "Failure | None"


def _agent_output_to_payload(output: AgentOutput) -> dict[str, Any]:
    """Shape AgentOutput into a payload dict for validation and merging.

    ``output.text`` always takes precedence when ``output.structured``
    also contains a ``"text"`` key, preventing silent data loss.
    """
    raw = dict(output.structured)
    raw["text"] = output.text
    if output.tool_calls:
        raw["tool_calls"] = output.tool_calls
    return raw
