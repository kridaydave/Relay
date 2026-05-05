"""Async pipeline orchestration for Relay.

Owns: async lifecycle, concurrent agent execution.
Does NOT: define agent behavior, manage prompts.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from relay.core_pipeline import CoreRelayPipeline


@dataclass(frozen=True)
class AsyncRelayPipeline(CoreRelayPipeline):
    """Async version of RelayPipeline.

    Owns: async lifecycle, concurrent agent execution.
    Does NOT: define agent behavior.
    """
    _executor: ThreadPoolExecutor = field(init=False, repr=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, '_executor', ThreadPoolExecutor(max_workers=1))
        object.__setattr__(self, '_lock', Lock())

    async def execute_step_async(self, agent_output: dict[str, Any]) -> Any:
        """Execute a pipeline step with agent output asynchronously."""
        with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._executor,
                self._execute_step_sync,
                agent_output
            )

    def _execute_step_sync(self, agent_output: dict[str, Any]) -> Any:
        """Synchronous implementation that delegates to inherited execute_step."""
        return self.execute_step(agent_output)

    def _rollback_sync(self, reason: str = "Manual rollback") -> Any:
        """Synchronous implementation that delegates to inherited rollback."""
        return self.rollback()

    async def execute_with_timeout(
        self,
        agent_output: dict[str, Any],
        timeout_seconds: float
    ) -> Any:
        """Execute a pipeline step with timeout."""
        try:
            return await asyncio.wait_for(
                self.execute_step_async(agent_output),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            from relay.types import Failure
            return Failure(
                reason=f"Execution timed out after {timeout_seconds} seconds",
                code="EXECUTION_TIMEOUT"
            )

    async def get_current_envelope_async(self) -> Any:
        """Get the current envelope asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._get_current_envelope_sync
        )

    def _get_current_envelope_sync(self) -> Any:
        """Synchronous implementation that delegates to inherited get_current_envelope."""
        return self.get_current_envelope()

    def __enter__(self) -> "AsyncRelayPipeline":
        """Enter async context."""
        return self

    def __exit__(self, exc_type: type, exc_val: BaseException, exc_tb: Any) -> None:
        """Exit async context and clean up executor."""
        self._executor.shutdown(wait=True, cancel_futures=True)

    def close(self) -> None:
        """Explicitly shut down the executor."""
        self._executor.shutdown(wait=True, cancel_futures=True)