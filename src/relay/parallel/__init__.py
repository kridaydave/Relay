"""Parallel execution support for Relay v0.4.

Owns: JoinStrategy, ForkSpec, ForkResult types; fork runner; join strategies.
Does NOT: manage pipeline state, acquire locks, or execute steps.
"""

from relay.parallel.fork_runner import _run_single_fork
from relay.parallel.join import apply_join_strategy
from relay.parallel.types import ForkResult, ForkSpec, JoinStrategy

__all__ = [
    "JoinStrategy",
    "ForkSpec",
    "ForkResult",
    "_run_single_fork",
    "apply_join_strategy",
]
