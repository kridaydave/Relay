"""Join strategy implementations for Relay v0.4 parallel execution.

Owns: merging ForkResults into a single payload per join strategy.
Does NOT: execute adapters, commit to pipeline state, or manage locks.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Coroutine

logger = logging.getLogger(__name__)

from relay.envelope import ContextEnvelope
from relay.parallel.types import ForkResult, ForkSpec, JoinStrategy, agent_output_to_payload
from relay.types import ErrorCode, Failure, Result, Success

if TYPE_CHECKING:
    from relay.runners.protocol import AgentOutput


def _apply_union(fork_results: list[ForkResult]) -> Result[dict[str, Any]]:
    """Merge all passing forks. Conflict on any shared key with differing values.

    Under UNION, a single failed fork fails the entire parallel step.

    Returns: Success(merged_payload) or Failure(MERGE_CONFLICT | ALL_FORKS_FAILED)
    """
    failed = [r for r in fork_results if not r.success]
    if failed:
        reasons = "; ".join(
            f"fork[{r.fork_index}] ({r.adapter_name}): {r.failure.reason}"
            for r in failed if r.failure
        )
        return Failure(
            reason=f"UNION: {len(failed)} fork(s) failed — {reasons}",
            code=ErrorCode.ALL_FORKS_FAILED,
        )

    merged: dict[str, Any] = {}
    conflicts: list[str] = []

    for result in fork_results:
        if result.agent_output is None:
            return Failure(
                reason=(
                    f"ForkResult.success=True but agent_output is None "
                    f"for fork[{result.fork_index}] — invariant violated"
                ),
                code=ErrorCode.UNKNOWN_ERROR,
            )
        fork_payload = agent_output_to_payload(result.agent_output)
        for key, value in fork_payload.items():
            if key in merged and merged[key] != value:
                conflicts.append(key)
            elif key not in merged:
                merged[key] = value

    if conflicts:
        return Failure(
            reason=f"UNION merge conflict on keys: {sorted(set(conflicts))}",
            code=ErrorCode.MERGE_CONFLICT,
        )

    return Success(merged)


def _apply_vote(fork_results: list[ForkResult]) -> Result[dict[str, Any]]:
    """Accept the passing fork with the highest confidence_score.

    Failed forks are discarded; only passing forks compete.

    Returns: Success(winner_payload) or Failure(ALL_FORKS_FAILED)
    """
    passing = [r for r in fork_results if r.success and r.validation is not None]
    if not passing:
        return Failure(
            reason=f"VOTE: all {len(fork_results)} forks failed",
            code=ErrorCode.ALL_FORKS_FAILED,
        )

    def _confidence(r: ForkResult) -> float:
        if r.validation is None:
            return 0.0
        return r.validation.confidence_score

    winner = max(passing, key=_confidence)
    if winner.agent_output is None:
        return Failure(
            reason=(
                "ForkResult.success=True but agent_output is None "
                f"for fork[{winner.fork_index}] — invariant violated"
            ),
            code=ErrorCode.UNKNOWN_ERROR,
        )
    return Success(agent_output_to_payload(winner.agent_output))


async def _apply_first_wins(
    fork_index_coros: list[tuple[int, ForkSpec, "Coroutine[Any, Any, ForkResult]"]],
) -> Result[dict[str, Any]]:
    """Accept the first passing fork; cancel the rest.

    Cancellation is best-effort — tasks already in flight may complete naturally.

    Returns: Success(winner_payload) or Failure(ALL_FORKS_FAILED)
    """
    tasks: list[asyncio.Task[ForkResult]] = [
        asyncio.create_task(coro, name=f"fork-{idx}")
        for idx, _, coro in fork_index_coros
    ]
    winner_payload: dict[str, Any] | None = None
    pending = set(tasks)

    while pending and winner_payload is None:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                result: ForkResult = task.result()
            except Exception as exc:
                logger.warning("Fork task %s raised unexpected exception: %s: %s", task.get_name(), type(exc).__name__, exc)
                continue
            if result.success and result.agent_output is not None:
                winner_payload = agent_output_to_payload(result.agent_output)
                break
        if winner_payload is not None:
            break

    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if winner_payload is None:
        return Failure(
            reason=f"FIRST_WINS: all {len(tasks)} forks failed or were cancelled",
            code=ErrorCode.ALL_FORKS_FAILED,
        )
    return Success(winner_payload)


async def apply_join_strategy(
    strategy: JoinStrategy,
    fork_results: list[ForkResult],
    first_wins_coros: list[tuple[int, ForkSpec, "Coroutine[Any, Any, ForkResult]"]] | None = None,
) -> Result[dict[str, Any]]:
    """Route to the correct strategy implementation.

    Returns: Success(merged_payload) or Failure with MERGE_CONFLICT / ALL_FORKS_FAILED.
    """
    if strategy == JoinStrategy.UNION:
        return _apply_union(fork_results)
    elif strategy == JoinStrategy.VOTE:
        return _apply_vote(fork_results)
    elif strategy == JoinStrategy.FIRST_WINS:
        if first_wins_coros is None:
            raise ValueError("first_wins_coros must be provided for FIRST_WINS strategy")
        return await _apply_first_wins(first_wins_coros)
    else:
        return Failure(
            reason=f"Unknown join strategy: {strategy!r}",
            code=ErrorCode.INVALID_JOIN_STRATEGY,
        )
