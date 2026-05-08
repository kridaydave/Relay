"""Budget enforcement for token cap validation."""

from dataclasses import dataclass

from relay.budget.token_counter import TokenCounter
from relay.envelope import ContextEnvelope
from relay.types import BudgetExceeded, ErrorCode, Failure, Result, Success


@dataclass(frozen=True)
class HardCapEnforcer:
    """Enforces hard token budget cap before agent calls.

    Validates that the projected token cost of an agent call
    would not exceed the remaining budget.
    """

    pipeline_id: str
    counter: TokenCounter

    def check(self, envelope: ContextEnvelope, projected_slice: str) -> Result[None]:
        """Check if projected slice would exceed budget.

        Args:
            envelope: Current context envelope.
            projected_slice: The context slice that would be passed to the agent.

        Returns:
            Success(None) if within budget, Failure if exceeded or invalid counter.
        """
        projected_cost = self.counter.count(projected_slice)
        if projected_cost < 0:
            return Failure(
                reason=f"TokenCounter returned negative value: {projected_cost}",
                code=ErrorCode.INVALID_TOKEN_COUNT,
            )

        if envelope.token_budget_used + projected_cost > envelope.token_budget_total:
            return Failure(
                reason=f"Budget exceeded: used {envelope.token_budget_used}, projected {projected_cost}, limit {envelope.token_budget_total}",
                code=ErrorCode.BUDGET_EXCEEDED,
            )

        return Success(None)