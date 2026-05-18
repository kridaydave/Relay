"""Handoff Validator for Relay v0.1.

Owns: contradiction detection, diff computation, rollback triggering.
Does NOT: sign envelopes, persist data, execute agents.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from relay.envelope import ContextEnvelope
from relay.types import ErrorCode, Failure, JSONDict, Result, Success

if TYPE_CHECKING:
    from relay.slicer.manifest import AgentManifest


MAX_EXTRACTION_DEPTH = 50
MAX_EXTRACTED_ENTITIES = 10000

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
    diff: JSONDict
    contradiction_details: str | None
    confidence_score: float = 1.0


@dataclass(frozen=True)
class HandoffValidator:
    """Validates agent output and detects corruption.

    Owns: contradiction detection, diff computation, rollback triggering.
    Does NOT: sign envelopes, persist data, execute agents.

    Stateless (frozen per Rule 2.4).
    """

    hallucination_ratio_threshold: float | None = 2.0
    hallucination_deletion_threshold: int | None = 3

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
        self, previous_envelope: ContextEnvelope, new_payload: JSONDict
    ) -> Result[ValidationResult]:
        """Validate a raw payload dict against the previous envelope.

        Skips envelope-level checks (pipeline_id, step) — a raw payload has no
        envelope metadata yet. Used by _run_single_fork to validate fork output
        pre-commit.

        REQUIRES: no lock — reads only immutable inputs.
        """
        return self._validate_payloads(previous_envelope.payload, new_payload)

    def _validate_payloads(
        self,
        previous_payload: JSONDict,
        new_payload: JSONDict,
    ) -> Result[ValidationResult]:
        """Core validation logic operating on raw payloads.

        Extracted from validate_handoff so fork_runner can validate without a
        full envelope. Logic is identical to validate_handoff() minus the
        pipeline_id/step envelope checks.

        REQUIRES: no lock — reads only immutable inputs. Stateless.
        """
        contradiction_details: str | None = None
        has_contradiction = False

        hallucination_result = self._detect_hallucination(previous_payload, new_payload)
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
        self, previous_payload: JSONDict, current_payload: JSONDict
    ) -> str | None:
        """Detect hallucination by checking entity fabrication ratio.

        This heuristic approximates detection by flagging when new entities vastly
        outnumber removed ones, suggesting fabrication. Entity removal is valid and
        not flagged.
        """
        if self.hallucination_ratio_threshold is None:
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
            if ratio > self.hallucination_ratio_threshold:
                return f"Entity fabrication detected: {new_count} new, {removed_count} removed (ratio: {ratio:.1f}x)"

        if removed_count > 0 and new_count == 0:
            if (
                self.hallucination_deletion_threshold is not None
                and removed_count > self.hallucination_deletion_threshold
            ):
                return f"Excessive entity deletion detected: {removed_count} removed, 0 new"

        return None

    ENTITY_KEYS: frozenset[str] = frozenset(
        {"entity", "entities", "subject", "object", "name", "id", "identifier"}
    )

    def _extract_entities(self, payload: JSONDict) -> frozenset[str]:
        """Approximates entity mentions from payload using iterative traversal.

        This heuristic extracts strings from values whose parent key is an
        entity-keyed field (entity, entities, subject, object, name, id, identifier).
        It has known false positives (narrative text using entity-like keys) and
        false negatives (entities in non-entity-keyed fields). Treat output as
        approximate, not exact.

        Only extracts strings from values whose parent key is an entity-keyed field.
        This prevents arbitrary narrative text from polluting the entity set.

        Tracks nesting depth from root (not stack size). A flat list of 60 strings
        has items at depth 1 and passes. A dict nested 50 levels deep fails with
        MaxDepthExceededError.
        """
        entities: set[str] = set()

        stack: list[tuple[object, int, bool]] = [(payload, 0, False)]
        while stack:
            if len(entities) >= MAX_EXTRACTED_ENTITIES:
                break
            obj, depth, is_entity_context = stack.pop()
            if depth > MAX_EXTRACTION_DEPTH:
                raise MaxDepthExceededError(
                    f"JSON depth {depth} exceeds maximum allowed depth of {MAX_EXTRACTION_DEPTH}"
                )

            if isinstance(obj, dict):
                obj_dict = cast(JSONDict, obj)
                for key, value in obj_dict.items():
                    in_entity_context = key in self.ENTITY_KEYS
                    if in_entity_context and isinstance(value, str):
                        if (
                            len(value) > 2
                            and len(value) < 80
                            and value.lower() not in self.STOP_WORDS
                        ):
                            entities.add(value.lower())
                            continue
                    stack.append((value, depth + 1, in_entity_context))
            elif isinstance(obj, list):
                obj_list = cast(list[object], obj)
                for item in obj_list:
                    if is_entity_context and isinstance(item, str):
                        if (
                            len(item) > 2
                            and len(item) < 80
                            and item.lower() not in self.STOP_WORDS
                        ):
                            entities.add(item.lower())
                            continue
                    stack.append((item, depth + 1, is_entity_context))

        return frozenset(entities)

    def _compute_diff(
        self, previous_payload: JSONDict, current_payload: JSONDict
    ) -> JSONDict:
        """Compute structural diff of payload keys."""
        added: list[str] = []
        removed: list[str] = []
        modified: list[str] = []

        prev_keys = set(previous_payload.keys())
        curr_keys = set(current_payload.keys())

        added = sorted(curr_keys - prev_keys)
        removed = sorted(prev_keys - curr_keys)

        common_keys = prev_keys & curr_keys
        for key in common_keys:
            if previous_payload[key] != current_payload[key]:
                modified.append(key)

        modified = sorted(modified)

        return dict[str, object](
            {"added": added, "removed": removed, "modified": modified}
        )

    def _check_critical_keys_missing(self, diff: JSONDict) -> str | None:
        """Flag if critical keys disappear."""
        removed_raw = diff.get("removed", [])
        if isinstance(removed_raw, list):
            removed: list[object] = removed_raw
        else:
            removed = []
        missing_critical = [
            k for k in removed if isinstance(k, str) and k in self.CRITICAL_KEYS
        ]

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
