"""Handoff Validator for Relay v0.1.

Owns: contradiction detection, diff computation, rollback triggering.
Does NOT: sign envelopes, persist data, execute agents.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from relay.envelope import ContextEnvelope
from relay.types import ErrorCode, Failure, Result, Success

if TYPE_CHECKING:
    from relay.slicer.manifest import AgentManifest


MAX_EXTRACTION_DEPTH = 50

__all__ = [
    "MAX_EXTRACTION_DEPTH",
    "MaxDepthExceededError",
    "ValidationResult",
    "HandoffValidator",
    "validate_manifest_boundaries",
]


class MaxDepthExceededError(Exception):
    """Raised when JSON depth exceeds maximum allowed."""

    pass


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a handoff between envelopes."""

    has_contradiction: bool
    diff: dict[str, Any]
    contradiction_details: str | None
    confidence_score: float = 1.0


class HandoffValidator:
    """Validates agent output and detects corruption.

    Owns: contradiction detection, diff computation, rollback triggering.
    Does NOT: sign envelopes, persist data, execute agents.
    """

    CRITICAL_KEYS: frozenset[str] = frozenset(
        {"entities", "actions", "facts", "constraints", "requirements"}
    )
    STOP_WORDS: frozenset[str] = frozenset(
        {
            "the",
            "and",
            "but",
            "for",
            "nor",
            "yet",
            "so",
            "a",
            "an",
            "of",
            "to",
            "in",
            "on",
            "at",
            "by",
            "with",
            "from",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
        }
    )

    def __init__(
        self,
        hallucination_ratio_threshold: float | None = 2.0,
        hallucination_deletion_threshold: int | None = 3,
    ) -> None:
        """Initialize the validator.

        Args:
            hallucination_ratio_threshold: Flag hallucination when new_entities / removed_entities
                exceeds this ratio. None disables hallucination detection.
            hallucination_deletion_threshold: Flag excessive deletion when more than this many
                entities are removed with no additions. None disables this check.
        """
        self._hallucination_ratio_threshold = hallucination_ratio_threshold
        self._hallucination_deletion_threshold = hallucination_deletion_threshold

    def validate_handoff(
        self, previous_envelope: ContextEnvelope, current_envelope: ContextEnvelope
    ) -> Result[ValidationResult]:
        """Validate a handoff between two envelopes.

        Delegates payload-level checks to _validate_payloads. Envelope-level
        checks (pipeline_id, step) remain here because fork validation operates
        on raw payloads, not envelopes.
        """
        if previous_envelope.pipeline_id != current_envelope.pipeline_id:
            return Failure(
                reason="Pipeline ID mismatch", code=ErrorCode.PIPELINE_MISMATCH
            )

        if previous_envelope.step >= current_envelope.step:
            return Failure(reason="Step must increase", code=ErrorCode.INVALID_STEP)

        return self._validate_payloads(
            previous_envelope.payload, current_envelope.payload
        )

    def validate_handoff_payload(
        self, previous_envelope: ContextEnvelope, new_payload: dict[str, Any]
    ) -> Result[ValidationResult]:
        """Validate a raw payload dict against the previous envelope.

        Skips envelope-level checks (pipeline_id, step) — a raw payload has no
        envelope metadata yet. Used by _run_single_fork to validate fork output
        pre-commit.

        REQUIRES: no lock — reads only immutable inputs.
        """
        return self._validate_payloads(
            previous_envelope.payload, new_payload
        )

    def _validate_payloads(
        self,
        previous_payload: dict[str, Any],
        new_payload: dict[str, Any],
    ) -> Result[ValidationResult]:
        """Core validation logic operating on raw payloads.

        Extracted from validate_handoff so fork_runner can validate without a
        full envelope. Logic is identical to validate_handoff() minus the
        pipeline_id/step envelope checks.

        REQUIRES: no lock — reads only immutable inputs. Stateless.
        """
        contradiction_details: str | None = None
        has_contradiction = False

        hallucination_result = self._detect_hallucination(
            previous_payload, new_payload
        )
        if hallucination_result:
            has_contradiction = True
            contradiction_details = hallucination_result

        diff = self._compute_diff(previous_payload, new_payload)
        critical_missing = self._check_critical_keys_missing(diff)
        if critical_missing:
            has_contradiction = True
            contradiction_details = (
                f"{contradiction_details}; " if contradiction_details else ""
            ) + critical_missing

        if has_contradiction:
            confidence_score = 0.0
        else:
            try:
                new_entities = self._extract_entities(new_payload)
                known_entities = self._extract_entities(previous_payload)
            except MaxDepthExceededError:
                confidence_score = 0.0
            else:
                if not new_entities:
                    confidence_score = 1.0
                else:
                    preserved = len(new_entities & known_entities)
                    confidence_score = preserved / len(new_entities)

        has_contradiction_str: str | None = (
            contradiction_details if has_contradiction else None
        )

        return Success(
            ValidationResult(
                has_contradiction=has_contradiction,
                diff=diff,
                contradiction_details=has_contradiction_str,
                confidence_score=confidence_score,
            )
        )

    def should_rollback(self, validation_result: ValidationResult) -> bool:
        """Determine if validation result requires rollback."""
        return validation_result.has_contradiction

    def _detect_hallucination(
        self, previous_payload: dict[str, Any], current_payload: dict[str, Any]
    ) -> str | None:
        """Detect hallucination by checking entity fabrication ratio.

        This heuristic approximates detection by flagging when new entities vastly
        outnumber removed ones, suggesting fabrication. Entity removal is valid and
        not flagged.
        """
        if self._hallucination_ratio_threshold is None:
            return None

        try:
            prev_entities = self._extract_entities(previous_payload)
            curr_entities = self._extract_entities(current_payload)
        except MaxDepthExceededError as e:
            return f"Payload depth exceeds limit: {e}"

        new_entities = curr_entities - prev_entities
        removed_entities = prev_entities - curr_entities

        new_count = len(new_entities)
        removed_count = len(removed_entities)

        if new_count > 0:
            effective_removed = max(removed_count, 1)
            ratio = new_count / effective_removed
            if ratio > self._hallucination_ratio_threshold:
                return f"Entity fabrication detected: {new_count} new, {removed_count} removed (ratio: {ratio:.1f}x)"

        if removed_count > 0 and new_count == 0:
            if (
                self._hallucination_deletion_threshold is not None
                and removed_count > self._hallucination_deletion_threshold
            ):
                return f"Excessive entity deletion detected: {removed_count} removed, 0 new"

        return None

    def _extract_entities(self, payload: dict[str, Any]) -> frozenset[str]:
        """Extract entity mentions from payload using iterative traversal.

        Tracks nesting depth from root (not stack size). A flat list of 60 strings
        has items at depth 1 and passes. A dict nested 50 levels deep fails with
        MaxDepthExceededError.
        """
        entities: set[str] = set()

        stack: list[tuple[Any, int]] = [(payload, 0)]
        while stack:
            obj, depth = stack.pop()
            if depth > MAX_EXTRACTION_DEPTH:
                raise MaxDepthExceededError(
                    f"JSON depth {depth} exceeds maximum allowed depth of {MAX_EXTRACTION_DEPTH}"
                )

            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in {
                        "entity",
                        "entities",
                        "subject",
                        "object",
                        "name",
                        "id",
                        "identifier",
                    }:
                        if isinstance(value, str):
                            entities.add(value.lower())
                    stack.append((value, depth + 1))
            elif isinstance(obj, list):
                for item in obj:
                    stack.append((item, depth + 1))
            elif isinstance(obj, str):
                if (
                    len(obj) > 2
                    and len(obj) < 100
                    and obj.lower() not in self.STOP_WORDS
                ):
                    entities.add(obj.lower())

        return frozenset(entities)

    def _compute_diff(
        self, previous_payload: dict[str, Any], current_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute structural diff of payload keys."""
        diff: dict[str, Any] = {"added": [], "removed": [], "modified": []}

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
    manifest: "AgentManifest",
    written_sections: set[str],
) -> Result[None]:
    """Validate that agent only wrote to sections in its manifest.

    Args:
        manifest: Agent manifest defining write permissions.
        written_sections: Set of section keys the agent wrote to.

    Returns:
        Success(None) if validation passes, Failure if agent wrote outside manifest.
    """
    violations = []
    for section in written_sections:
        if section not in manifest.writes:
            violations.append(section)

    if violations:
        return Failure(
            reason=f"Agent {manifest.agent_id} wrote to sections not in manifest: {violations}",
            code=ErrorCode.MANIFEST_BOUNDARY_VIOLATION,
        )

    return Success(None)
