"""Handoff Validator for Relay v0.1.

Owns: contradiction detection, diff computation, rollback triggering.
Does NOT: sign envelopes, persist data, execute agents.
"""

from dataclasses import dataclass
from typing import Any

from relay.envelope import ContextEnvelope
from relay.types import Failure, Result, Success


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a handoff between envelopes."""
    has_contradiction: bool
    diff: dict[str, Any]
    contradiction_details: str | None


class HandoffValidator:
    """Validates agent output and detects corruption.

    Owns: contradiction detection, diff computation, rollback triggering.
    Does NOT: sign envelopes, persist data, execute agents.
    """

    CRITICAL_KEYS: frozenset[str] = frozenset({"entities", "actions", "facts", "constraints", "requirements"})

    def __init__(self, hallucination_ratio_threshold: float | None = 2.0) -> None:
        """Initialize the validator.

        Args:
            hallucination_ratio_threshold: Flag hallucination when new_entities / removed_entities
                exceeds this ratio. None disables hallucination detection.
        """
        self._hallucination_ratio_threshold = hallucination_ratio_threshold

    def validate_handoff(
        self,
        previous_envelope: ContextEnvelope,
        current_envelope: ContextEnvelope
    ) -> Result[ValidationResult]:
        """Validate a handoff between two envelopes."""
        if previous_envelope.pipeline_id != current_envelope.pipeline_id:
            return Failure(reason="Pipeline ID mismatch", code="PIPELINE_MISMATCH")

        if previous_envelope.step >= current_envelope.step:
            return Failure(reason="Step must increase", code="INVALID_STEP")

        contradiction_details: str | None = None
        has_contradiction = False

        hallucination_result = self._detect_hallucination(previous_envelope.payload, current_envelope.payload)
        if hallucination_result:
            has_contradiction = True
            contradiction_details = hallucination_result

        diff = self._compute_diff(previous_envelope.payload, current_envelope.payload)
        critical_missing = self._check_critical_keys_missing(diff)
        if critical_missing:
            has_contradiction = True
            contradiction_details = (
                f"{contradiction_details}; " if contradiction_details else ""
            ) + critical_missing

        has_contradiction_str: str | None = contradiction_details if has_contradiction else None

        return Success(ValidationResult(
            has_contradiction=has_contradiction,
            diff=diff,
            contradiction_details=has_contradiction_str
        ))

    def should_rollback(self, validation_result: ValidationResult) -> bool:
        """Determine if validation result requires rollback."""
        return validation_result.has_contradiction

    def _detect_hallucination(
        self,
        previous_payload: dict[str, Any],
        current_payload: dict[str, Any]
    ) -> str | None:
        """Detect hallucination by checking for fabricated entities not in prior context.

        Flags when new entities appear that were NOT supported by prior context.
        Entity removal is valid agent behavior and not flagged.
        """
        if self._hallucination_ratio_threshold is None:
            return None

        prev_entities = self._extract_entities(previous_payload)
        curr_entities = self._extract_entities(current_payload)

        fabricated = curr_entities - prev_entities

        if fabricated:
            fabricated_list = sorted(fabricated)
            return f"Entity fabrication detected: {fabricated_list}"

        return None

    def _extract_entities(self, payload: dict[str, Any]) -> frozenset[str]:
        """Extract entity mentions from payload."""
        entities: set[str] = set()

        def extract_recursive(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in {"entity", "entities", "subject", "object", "name", "id", "identifier"}:
                        if isinstance(value, str):
                            entities.add(value.lower())
                    extract_recursive(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_recursive(item)
            elif isinstance(obj, str):
                if len(obj) > 2 and len(obj) < 100:
                    entities.add(obj.lower())

        extract_recursive(payload)
        return frozenset(entities)

    def _compute_diff(
        self,
        previous_payload: dict[str, Any],
        current_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute structural diff of payload keys."""
        diff: dict[str, Any] = {
            "added": [],
            "removed": [],
            "modified": []
        }

        prev_keys = set(previous_payload.keys())
        curr_keys = set(current_payload.keys())

        diff["added"] = sorted(curr_keys - prev_keys)
        diff["removed"] = sorted(prev_keys - curr_keys)

        common_keys = prev_keys & curr_keys
        for key in common_keys:
            if previous_payload[key] != current_payload[key]:
                diff["modified"].append(key)

        diff["modified"] = sorted(diff["modified"])

        return diff

    def _check_critical_keys_missing(self, diff: dict[str, Any]) -> str | None:
        """Flag if critical keys disappear."""
        removed = diff.get("removed", [])
        missing_critical = [k for k in removed if k in self.CRITICAL_KEYS]

        if missing_critical:
            return f"Critical keys removed: {sorted(missing_critical)}"

        return None