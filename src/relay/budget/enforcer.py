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

    def check(
        self,
        budget_used: int,
        budget_total: int,
        projected_slice: str,
        estimated_output_cost: int = 0,
    ) -> Result[int]:
        """Check if projected slice would exceed budget.

        Validates that the sum of budget consumed so far, projected input
        cost, and estimated output cost would not exceed the total budget.
        Previously only checked input cost, which made the cap systematically
        under-enforce (PH-01 in ruthless audit).

        Args:
            budget_used: Tokens consumed so far in this pipeline.
            budget_total: Maximum token budget allowed.
            projected_slice: The context slice that would be passed to the agent.
            estimated_output_cost: Estimated agent output tokens to reserve.
                Defaults to 0 for backward compatibility, but callers should
                provide a realistic estimate to make the cap a true hard cap.

        Returns:
            Success(total_projected) if within budget, Failure if exceeded or counter error.
        """
        try:
            projected_cost = self.counter.count(projected_slice)
        except Exception as e:
            return Failure(
                reason=f"Token counter failed: {e}",
                code=ErrorCode.UNKNOWN_ERROR,
            )

        total_projected = projected_cost + estimated_output_cost
        if budget_used + total_projected > budget_total:
            return Failure(
                reason=(
                    f"Budget exceeded: used {budget_used}, "
                    f"projected input {projected_cost} + "
                    f"estimated output {estimated_output_cost} = "
                    f"{total_projected}, limit {budget_total}"
                ),
                code=ErrorCode.BUDGET_EXCEEDED,
            )

        return Success(total_projected)
