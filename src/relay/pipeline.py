"""Pipeline orchestration for Relay v0.1.

Owns: pipeline lifecycle, component coordination.
Does NOT: define agent behavior, manage prompts.
"""

from dataclasses import dataclass

from relay.core_pipeline import CoreRelayPipeline
from relay.snapshot import SnapshotStore


@dataclass(frozen=True)
class RelayPipeline(CoreRelayPipeline):
    """Orchestrates the three core components.

    Owns: pipeline lifecycle, component coordination.
    Does NOT: define agent behavior, manage prompts.
    """
    pass