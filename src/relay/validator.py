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
        """Detect hallucination by checking entity fabrication ratio.

        Flags when new entities vastly outnumber removed ones, suggesting fabrication.
        Entity removal is valid and not flagged.
        """
        if self._hallucination_ratio_threshold is None:
            return None

        prev_entities = self._extract_entities(previous_payload)
        curr_entities = self._extract_entities(current_payload)

        new_entities = curr_entities - prev_entities
        removed_entities = prev_entities - curr_entities

        new_count = len(new_entities)
        removed_count = len(removed_entities)

        if new_count > 0:
            removed_count = max(removed_count, 1)
            ratio = new_count / removed_count
            if ratio > self._hallucination_ratio_threshold:
                return f"Entity fabrication detected: {new_count} new, {removed_count} removed (ratio: {ratio:.1f}x)"

        if removed_count > 0 and new_count == 0:
            if removed_count > self._hallucination_ratio_threshold:
                return f"Excessive entity deletion detected: {removed_count} removed, 0 new"

        return None

    def _extract_entities(self, payload: dict[str, Any]) -> frozenset[str]:
        """Extract entity mentions from payload."""
        entities: set[str] = set()
        stop_words = {"the", "and", "but", "for", "nor", "yet", "so", "a", "an", "of", "to", "in", "on", "at", "by", "with", "from", "is", "are", "was", "were", "be", "been", "being"}

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
                if len(obj) > 2 and len(obj) < 100 and obj.lower() not in stop_words:
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


def validate_manifest_boundaries(
    envelope: ContextEnvelope,
    manifest: "AgentManifest",
    written_sections: set[str],
) -> Result[None]:
    """Validate that agent only wrote to sections in its manifest.

    Args:
        envelope: Current context envelope.
        manifest: Agent manifest defining write permissions.
        written_sections: Set of section keys the agent wrote to.

    Returns:
        Success(None) if validation passes, Failure if agent wrote outside manifest.
    """
    from relay.slicer.manifest import AgentManifest
    from relay.types import HandoffValidationFailure

    violations = []
    for section in written_sections:
        if section not in manifest.writes:
            violations.append(section)

    if violations:
        return Failure(
            reason=f"Agent {manifest.agent_id} wrote to sections not in manifest: {violations}",
            code="MANIFEST_BOUNDARY_VIOLATION",
        )

    return Success(None)