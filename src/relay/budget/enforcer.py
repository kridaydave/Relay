"""Budget enforcement for token cap validation."""

from dataclasses import dataclass

from relay.envelope import ContextEnvelope
from relay.types import BudgetExceededError


@dataclass(frozen=True)
class HardCapEnforcer:
    """Enforces hard token budget cap before agent calls.

    Validates that the projected token cost of an agent call
    would not exceed the remaining budget.
    """

    pipeline_id: str
    counter: "TokenCounter"

    def check(self, envelope: ContextEnvelope, projected_slice: str) -> None:
        """Check if projected slice would exceed budget.

        Args:
            envelope: Current context envelope.
            projected_slice: The context slice that would be passed to the agent.

        Raises:
            BudgetExceededError: If projected cost would exceed remaining budget.
            ValueError: If counter returns negative value.
        """
        projected_cost = self.counter.count(projected_slice)
        if projected_cost < 0:
            raise ValueError(f"TokenCounter returned negative value: {projected_cost}")

        if envelope.token_budget_used + projected_cost > envelope.token_budget_total:
            raise BudgetExceededError(
                used=envelope.token_budget_used,
                projected=projected_cost,
                limit=envelope.token_budget_total,
                step=envelope.step,
            )