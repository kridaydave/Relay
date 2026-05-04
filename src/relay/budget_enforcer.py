"""Token budget enforcement for Relay.

Owns: budget pre-checking, priority queuing.
Does NOT: execute agents, sign envelopes.
"""

from dataclasses import dataclass

from relay.envelope import ContextEnvelope
from relay.types import Result, Success


@dataclass(frozen=True)
class TokenBudgetEnforcer:
    """Enforces token budget before agent execution.

    Owns: budget pre-checking, priority queuing.
    Does NOT: execute agents, sign envelopes.
    """

    default_model: str

    def __init__(self, default_model: str = "gpt-4") -> None:
        """Initialize the enforcer with a default model."""
        object.__setattr__(self, "default_model", default_model)

    def can_proceed(
        self,
        current_envelope: ContextEnvelope,
        estimated_agent_tokens: int
    ) -> Result[bool]:
        """Check if agent can proceed within token budget."""
        total_used = current_envelope.token_budget_used + estimated_agent_tokens
        if total_used <= current_envelope.token_budget_total:
            return Success(value=True)
        return Success(value=False)

    def estimate_agent_tokens(
        self,
        agent_prompt: str,
        model: str | None = None
    ) -> int:
        """Estimate tokens for an agent prompt."""
        return len(agent_prompt) // 4