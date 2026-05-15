"""Fork runner for Relay v0.4 parallel execution.

Owns: executing one adapter against a pre-fork envelope snapshot.
Does NOT: write to pipeline state, acquire locks, or know about join strategies.

Each call is a pure coroutine — the same pre_fork_envelope can be passed to
N concurrent _run_single_fork calls with no contention.
"""

from typing import TYPE_CHECKING, Any

from relay.envelope import ContextEnvelope
from relay.parallel.types import ForkResult, ForkSpec, _agent_output_to_payload
from relay.runners.protocol import AgentOutput, ContextSlice
from relay.types import ErrorCode, Failure, Success
from relay.validator import HandoffValidator, validate_manifest_boundaries

if TYPE_CHECKING:
    from relay.runners.registry import AdapterRegistry
    from relay.slicer.manifest import AgentManifest


async def _run_single_fork(
    fork_index: int,
    spec: ForkSpec,
    slice_: ContextSlice,
    pre_fork_envelope: ContextEnvelope,
    registry: "AdapterRegistry",
    validator: HandoffValidator,
) -> ForkResult:
    """Execute one fork: run adapter, validate output, return ForkResult.

    Never raises. All errors are captured in ForkResult.success=False.
    Never writes to pipeline state — caller owns commit.

    Args:
        fork_index:        0-based index in the original fork_specs list.
        spec:              ForkSpec describing which adapter + manifest to use.
        slice_:            Pre-built ContextSlice for this fork (immutable).
        pre_fork_envelope: The snapshot envelope before the parallel step.
        registry:          Adapter registry to look up the adapter.
        validator:         Stateless HandoffValidator instance (shared across forks).

    Returns:
        ForkResult — always. success=True iff adapter ran and validation passed.
    """
    adapter_result = registry.get(spec.adapter_name)
    if isinstance(adapter_result, Failure):
        return ForkResult(
            fork_index=fork_index,
            adapter_name=spec.adapter_name,
            success=False,
            agent_output=None,
            validation=None,
            failure=adapter_result,
        )

    adapter = adapter_result.value

    try:
        agent_output = await adapter.run(slice_, spec.manifest)
    except Exception as e:
        return ForkResult(
            fork_index=fork_index,
            adapter_name=spec.adapter_name,
            success=False,
            agent_output=None,
            validation=None,
            failure=Failure(
                reason=f"Adapter '{spec.adapter_name}' raised: {type(e).__name__}: {e}",
                code=ErrorCode.FORK_EXECUTION_FAILED,
            ),
        )

    fork_payload = _agent_output_to_payload(agent_output)
    validation_result = validator.validate_handoff_payload(
        previous_envelope=pre_fork_envelope,
        new_payload=fork_payload,
    )
    if isinstance(validation_result, Failure):
        return ForkResult(
            fork_index=fork_index,
            adapter_name=spec.adapter_name,
            success=False,
            agent_output=agent_output,
            validation=None,
            failure=validation_result,
        )

    validation = validation_result.value
    passed = not validator.should_rollback(validation)

    if passed:
        written_sections = set(fork_payload.keys())
        boundary_result = validate_manifest_boundaries(spec.manifest, written_sections)
        if isinstance(boundary_result, Failure):
            return ForkResult(
                fork_index=fork_index,
                adapter_name=spec.adapter_name,
                success=False,
                agent_output=agent_output,
                validation=validation,
                failure=boundary_result,
            )

    return ForkResult(
        fork_index=fork_index,
        adapter_name=spec.adapter_name,
        success=passed,
        agent_output=agent_output,
        validation=validation,
        failure=None if passed else Failure(
            reason=validation.contradiction_details or "Fork validation failed",
            code=ErrorCode.FORK_EXECUTION_FAILED,
        ),
    )
