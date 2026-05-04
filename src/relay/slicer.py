"""Context slice extraction for Relay.

Owns: ContextSlice, slice extraction, key relevance determination.
Does NOT: execute agents, validate content, sign envelopes.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope
from relay.types import Result, Success, Failure


@dataclass(frozen=True)
class ContextSlice:
    """Minimal context slice for a specific agent.

    Attributes:
        slice_id: Unique identifier for this slice.
        step: Step number this slice was created from.
        relevant_keys: Keys this agent should see.
        truncated_at: Token limit for this slice.
        payload: The subset of data being provided.
    """
    slice_id: str
    step: int
    relevant_keys: list[str]
    truncated_at: int
    payload: dict[str, Any]


class SlicePackager:
    """Cuts minimal context slices per agent.

    Owns: slice extraction, key relevance, truncation.
    Does NOT: execute agents, validate content, sign envelopes.
    """

    def __init__(self, default_max_tokens: int = 4000) -> None:
        """Initialize with default token limit."""
        self._default_max_tokens = default_max_tokens
        self._agent_key_map: dict[str, list[str]] = {}

    def register_agent_keys(self, agent_id: str, relevant_keys: list[str]) -> None:
        """Register which keys an agent should have access to."""
        self._agent_key_map[agent_id] = relevant_keys

    def create_slice(
        self,
        envelope: ContextEnvelope,
        agent_id: str,
        max_tokens: int | None = None
    ) -> Result[ContextSlice]:
        """Create a minimal slice for the given agent."""
        if max_tokens is None:
            max_tokens = self._default_max_tokens

        relevant_keys = self._determine_relevant_keys(agent_id, envelope.payload)
        if not relevant_keys:
            relevant_keys = list(envelope.payload.keys())

        truncated_payload = self._truncate_payload(
            envelope.payload,
            relevant_keys,
            max_tokens
        )

        slice_obj = ContextSlice(
            slice_id=f"{envelope.pipeline_id}_step{envelope.step}_agent{agent_id}",
            step=envelope.step,
            relevant_keys=relevant_keys,
            truncated_at=max_tokens,
            payload=truncated_payload
        )
        return Success(slice_obj)

    def _determine_relevant_keys(
        self,
        agent_id: str,
        full_payload: dict[str, Any]
    ) -> list[str]:
        """Determine which keys are relevant for this agent."""
        if agent_id in self._agent_key_map:
            registered = self._agent_key_map[agent_id]
            return [k for k in registered if k in full_payload]
        return list(full_payload.keys())

    def _truncate_payload(
        self,
        payload: dict[str, Any],
        relevant_keys: list[str],
        max_tokens: int
    ) -> dict[str, Any]:
        """Truncate payload to fit within token budget."""
        import json
        result: dict[str, Any] = {}
        current_tokens = 0

        for key in relevant_keys:
            if key not in payload:
                continue
            value = payload[key]
            value_str = json.dumps(value)
            value_tokens = len(value_str) // 4

            if current_tokens + value_tokens > max_tokens:
                remaining = max_tokens - current_tokens
                if remaining <= 0:
                    break
                truncated_value = value_str[:remaining * 4]
                try:
                    result[key] = json.loads(truncated_value)
                except json.JSONDecodeError:
                    result[key] = str(value)[:remaining]
                break

            result[key] = value
            current_tokens += value_tokens

        return result


def create_slice_from_envelope(
    envelope: ContextEnvelope,
    agent_id: str,
    max_tokens: int = 4000
) -> Result[ContextSlice]:
    """Convenience function to create a slice from an envelope."""
    packager = SlicePackager(default_max_tokens=max_tokens)
    return packager.create_slice(envelope, agent_id, max_tokens)