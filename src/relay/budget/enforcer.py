"""Budget enforcement for token cap validation.

Owns: hard-cap check before agent calls.
Does NOT: count tokens, manage budgets, or execute agents.
"""

from dataclasses import dataclass

from relay.budget.token_counter import TokenCounter
from relay.types import ErrorCode, Failure, Result, Success


@dataclass(frozen=True)
class HardCapEnforcer:
    """Enforces hard token budget cap before agent calls.

    Validates that the projected token cost of an agent call
    would not exceed the remaining budget.
    """

    counter: TokenCounter

    def check(self, budget_used: int, budget_total: int, projected_slice: str) -> Result[None]:
        """Check if projected slice would exceed budget.

        Args:
            budget_used: Tokens consumed so far in this pipeline.
            budget_total: Maximum token budget allowed.
            projected_slice: The context slice that would be passed to the agent.

        Returns:
            Success(None) if within budget, Failure if exceeded or invalid counter.
        """
        projected_cost = self.counter.count(projected_slice)
        if budget_used + projected_cost > budget_total:
            return Failure(
                reason=f"Budget exceeded: used {budget_used}, projected {projected_cost}, limit {budget_total}",
                code=ErrorCode.BUDGET_EXCEEDED,
            )

        return Success(None)