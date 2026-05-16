"""Parallel execution support for Relay v0.4.

Owns: JoinStrategy, ForkSpec, ForkResult types; fork runner; join strategies.
Does NOT: manage pipeline state, acquire locks, or execute steps.
"""

from relay.parallel.fork_runner import run_single_fork
from relay.parallel.join import apply_join_strategy
from relay.parallel.types import ForkResult, ForkSpec, JoinStrategy, agent_output_to_payload

__all__ = [
    "JoinStrategy",
    "ForkSpec",
    "ForkResult",
    "agent_output_to_payload",
    "apply_join_strategy",
    "run_single_fork",
]
