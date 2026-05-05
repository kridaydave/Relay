"""Agent execution layer for Relay.

Owns: agent execution, result parsing, error handling.
Does NOT: manage prompts, validate context, persist state.
"""

from dataclasses import dataclass
from threading import Thread
from typing import Any, Protocol, runtime_checkable

from relay.slicer import ContextSlice
from relay.types import Failure, Result, Success

TRANSIENT_ERROR_CODES = frozenset({
    "TIMEOUT",
    "RATE_LIMIT",
    "SERVICE_UNAVAILABLE",
    "NETWORK_ERROR",
    "AGENT_ERROR",
    "NO_RESULT",
})


@runtime_checkable
class Agent(Protocol):
    """Protocol for any agent implementation."""

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run the agent with input data."""
        ...


@dataclass(frozen=True)
class AgentRunner:
    """Executes agent calls, framework-agnostic.

    Owns: agent execution, result parsing, error handling.
    Does NOT: manage prompts, validate context, persist state.
    """

    max_retries: int = 3
    timeout_seconds: float = 30.0

    def execute(self, agent: Agent, input_slice: ContextSlice) -> Result[dict[str, Any]]:
        """Execute agent with input slice once."""
        return self.execute_with_retry(agent, input_slice, self.max_retries)

    def execute_with_retry(
        self,
        agent: Agent,
        input_slice: ContextSlice,
        max_retries: int | None = None
    ) -> Result[dict[str, Any]]:
        """Execute agent with retry logic."""
        if max_retries is None:
            max_retries = self.max_retries

        last_error: Failure | None = None

        for attempt in range(max_retries):
            result = self._execute_with_timeout(agent, input_slice)

            if isinstance(result, Success):
                return result

            last_error = result
            if isinstance(last_error, Failure) and last_error.code not in TRANSIENT_ERROR_CODES:
                return last_error
            if attempt < max_retries - 1:
                continue

        return last_error or Failure(
            reason="Agent execution failed with unknown error",
            code="UNKNOWN_ERROR"
        )

    def _execute_with_timeout(
        self,
        agent: Agent,
        input_slice: ContextSlice
    ) -> Result[dict[str, Any]]:
        """Execute agent with timeout handling."""
        output_container: list[Result[dict[str, Any]]] = []

        def run_agent() -> None:
            try:
                result = agent.run(input_slice.payload)
                output_container.append(Success(result))
            except Exception as e:
                output_container.append(Failure(reason=str(e), code="AGENT_ERROR"))

        thread = Thread(target=run_agent, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout_seconds)

        if thread.is_alive():
            return Failure(
                reason=f"Agent execution timed out after {self.timeout_seconds}s",
                code="TIMEOUT"
            )

        if not output_container:
            return Failure(
                reason="Agent execution produced no result",
                code="NO_RESULT"
            )

        return output_container[0]