"""Unit tests for relay.runner."""

from typing import Any

from relay.runner import Agent, AgentRunner
from relay.slicer import ContextSlice
from relay.types import Failure, Success


class MockAgent:
    """Mock Agent that can be configured to succeed or fail."""

    def __init__(
        self,
        fail_always: bool = False,
        fail_with_exception: bool = False,
        exception_on_attempt: int | None = None,
        succeed_from_attempt: int = 1,
    ) -> None:
        self.fail_always = fail_always
        self.fail_with_exception = fail_with_exception
        self.exception_on_attempt = exception_on_attempt
        self.succeed_from_attempt = succeed_from_attempt
        self.attempt_count = 0

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.attempt_count += 1
        if self.exception_on_attempt is not None and self.attempt_count >= self.exception_on_attempt:
            raise RuntimeError("Simulated failure")
        if self.fail_always or self.attempt_count < self.succeed_from_attempt:
            if self.fail_with_exception:
                raise RuntimeError("Agent execution failed")
            return {"error": "Agent execution failed"}
        return {"result": "success", "data": input_data}


def create_slice(payload: dict[str, Any] | None = None) -> ContextSlice:
    """Helper to create a ContextSlice for testing."""
    return ContextSlice(
        slice_id="test_slice",
        step=1,
        relevant_keys=["test_key"],
        truncated_at=1000,
        payload=payload or {"test_key": "test_value"},
    )


class TestAgentRunnerExecute:
    """Tests for AgentRunner.execute method."""

    def test_runner_executes_agent_and_returns_output(self) -> None:
        agent = MockAgent()
        runner = AgentRunner()
        slice = create_slice()

        result = runner.execute(agent, slice)

        assert isinstance(result, Success)
        assert result.value == {"result": "success", "data": slice.payload}

    def test_runner_returns_failure_on_agent_exception(self) -> None:
        agent = MockAgent(exception_on_attempt=1)
        runner = AgentRunner()
        slice = create_slice()

        result = runner.execute(agent, slice)

        assert isinstance(result, Failure)
        assert result.code == "AGENT_ERROR"
        assert "Simulated failure" in result.reason


class TestAgentRunnerExecuteWithRetry:
    """Tests for AgentRunner.execute_with_retry method."""

    def test_runner_respects_max_retries_on_failure(self) -> None:
        agent = MockAgent(fail_with_exception=True, succeed_from_attempt=100)
        runner = AgentRunner(max_retries=3)
        slice = create_slice()

        result = runner.execute_with_retry(agent, slice, max_retries=3)

        assert isinstance(result, Failure)
        assert result.code == "AGENT_ERROR"
        assert agent.attempt_count == 3

    def test_runner_succeeds_on_eventual_success_after_retries(self) -> None:
        agent = MockAgent(fail_with_exception=True, succeed_from_attempt=3)
        runner = AgentRunner(max_retries=3)
        slice = create_slice()

        result = runner.execute_with_retry(agent, slice, max_retries=3)

        assert isinstance(result, Success)
        assert result.value == {"result": "success", "data": slice.payload}
        assert agent.attempt_count == 3

    def test_runner_returns_failure_on_timeout(self) -> None:
        def slowRun(input_data: dict[str, Any]) -> dict[str, Any]:
            import time
            time.sleep(10)
            return {"result": "too slow"}

        class SlowAgent:
            def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
                return slowRun(input_data)

        runner = AgentRunner(timeout_seconds=0.1)
        slice = create_slice()

        result = runner.execute_with_retry(
            SlowAgent(),
            slice,
            max_retries=1
        )

        assert isinstance(result, Failure)
        assert result.code == "TIMEOUT"

    def test_runner_execute_with_retry_overrides_default(self) -> None:
        agent = MockAgent()
        runner = AgentRunner(max_retries=1)
        slice = create_slice()

        result = runner.execute_with_retry(agent, slice, max_retries=5)

        assert isinstance(result, Success)
        assert agent.attempt_count == 1