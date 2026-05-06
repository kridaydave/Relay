from dataclasses import dataclass

from relay.budget.token_counter import TokenCounter
from relay.envelope import ContextEnvelope
from relay.types import BudgetExceededError


@dataclass(frozen=True)
class HardCapEnforcer:
    """Enforces hard token budget cap before agent calls.

    Checks if the projected token cost would exceed the remaining budget.
    Raises BudgetExceededError if the cap would be breached.
    """

    pipeline_id: str
    counter: TokenCounter

    def check(self, envelope: ContextEnvelope, projected_slice: str) -> None:
        """Check if the projected slice would exceed the token budget.

        Args:
            envelope: Current context envelope.
            projected_slice: The slice of context being projected to the agent.

        Raises:
            BudgetExceededError: If projected cost exceeds remaining budget.
            ValueError: If counter returns a negative value.
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