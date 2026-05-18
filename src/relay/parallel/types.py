"""Parallel execution types for Relay v0.4.

Owns: JoinStrategy enum, ForkSpec, ForkResult.
Does NOT: implement join logic, execute adapters, or manage pipeline state.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from relay.runners.protocol import AgentOutput
from relay.types import Failure, JSONDict

if TYPE_CHECKING:
    from relay.slicer.manifest import AgentManifest
    from relay.validator import ValidationResult


class JoinStrategy(str, Enum):
    """Strategy for merging parallel fork outputs."""

    UNION = "UNION"
    VOTE = "VOTE"
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

    Note: For FIRST_WINS strategy, the forks_succeeded field in the final
    envelope may not reflect the actual count of passing forks due to
    cancellation. The value 1 indicates at least one fork succeeded.
    """

    fork_index: int
    adapter_name: str
    success: bool
    agent_output: "AgentOutput | None"
    validation: "ValidationResult | None"
    failure: "Failure | None"


logger = logging.getLogger(__name__)


def agent_output_to_payload(output: AgentOutput) -> JSONDict:
    """Shape AgentOutput into a payload dict for validation and merging.

    ``output.text`` always takes precedence over ``output.structured["text"]``.
    A warning is logged when this overwrite occurs.
    """
    raw: JSONDict = dict(output.structured)
    if "text" in raw:
        logger.warning(
            "agent_output_to_payload: output.structured already contains a 'text' key; "
            "overwriting with output.text (structured value lost)"
        )
    raw["text"] = output.text
    if output.tool_calls:
        raw["tool_calls"] = output.tool_calls
    return raw
