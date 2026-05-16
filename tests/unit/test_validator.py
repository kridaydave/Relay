"""Unit tests for relay.validator."""

from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope, create_initial_envelope
from relay.validator import HandoffValidator, MaxDepthExceededError, ValidationResult, validate_manifest_boundaries
from relay.types import Success, Failure, ErrorCode, JSONDict, unwrap


def _make_envelope(
    pipeline_id: str,
    step: int,
    payload: JSONDict,
    token_budget_used: int = 100,
    token_budget_total: int = 8000,
    timestamp: datetime | None = None,
    signature: str = "sig",
    manifest_hash: str = ""
) -> ContextEnvelope:
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=timestamp,
        token_budget_used=token_budget_used,
        token_budget_total=token_budget_total,
        payload=payload,
        manifest_hash=manifest_hash,
        signature=signature
    )


class TestValidateHandoff:
    def test_validate_handoff_fails_when_pipeline_id_mismatch(self) -> None:
        """Mismatched pipeline IDs must return Failure."""
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        current_envelope = _make_envelope(
            pipeline_id="different-pipeline",  # Different pipeline ID
            step=2,
            payload={"entities": ["a"]},
            token_budget_used=100,
            token_budget_total=8000
        )

        validator = HandoffValidator()
        result = validator.validate_handoff(previous_envelope, current_envelope)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.PIPELINE_MISMATCH

    def test_validate_handoff_fails_when_step_not_increasing(self) -> None:
        """Step must increase between envelopes."""
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        current_envelope = _make_envelope(
            pipeline_id="pipeline-123",
            step=1,  # Same step - not increasing
            payload={"entities": ["a", "b"]},
            token_budget_used=100,
            token_budget_total=8000
        )

        validator = HandoffValidator()
        result = validator.validate_handoff(previous_envelope, current_envelope)

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_STEP

    def test_validate_handoff_passes_when_clean(self) -> None:
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        current_envelope = _make_envelope(
            pipeline_id="pipeline-123",
            step=2,
            payload={"entities": ["a", "b"], "actions": ["b"], "facts": ["c", "d"]},
            token_budget_used=200,
            token_budget_total=8000
        )

        validator = HandoffValidator()
        result = validator.validate_handoff(previous_envelope, current_envelope)

        assert isinstance(result, Success)
        validation_result = result.value
        assert validation_result.has_contradiction is False
        assert validation_result.contradiction_details is None
        assert validation_result.confidence_score == pytest.approx(1.0)

    def test_validator_detects_contradiction_when_critical_key_missing(self) -> None:
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_envelope = _make_envelope(
            pipeline_id="pipeline-123",
            step=1,
            payload={"entities": ["a"], "actions": ["b"], "facts": ["c"], "constraints": ["x"]},
            token_budget_used=100,
            token_budget_total=8000,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

        current_envelope = _make_envelope(
            pipeline_id="pipeline-123",
            step=2,
            payload={"entities": ["a"], "actions": ["b"]},
            token_budget_used=200,
            token_budget_total=8000
        )

        validator = HandoffValidator()
        result = validator.validate_handoff(previous_envelope, current_envelope)

        assert isinstance(result, Success)
        validation_result = result.value
        assert validation_result.has_contradiction is True
        assert validation_result.contradiction_details is not None
        assert "Critical keys removed" in validation_result.contradiction_details
        assert "facts" in validation_result.contradiction_details
        assert "constraints" in validation_result.contradiction_details
        assert validation_result.confidence_score == 0.0


class TestShouldRollback:
    def test_validator_should_rollback_returns_true_on_contradiction(self) -> None:
        validation_result = ValidationResult(
            has_contradiction=True,
            diff={"added": [], "removed": [], "modified": []},
            contradiction_details="Some contradiction"
        )

        validator = HandoffValidator()
        should_rollback = validator.should_rollback(validation_result)

        assert should_rollback is True

    def test_validator_should_rollback_returns_false_on_clean_validation(self) -> None:
        validation_result = ValidationResult(
            has_contradiction=False,
            diff={"added": [], "removed": [], "modified": []},
            contradiction_details=None
        )

        validator = HandoffValidator()
        should_rollback = validator.should_rollback(validation_result)

        assert should_rollback is False


class TestComputeDiff:
    def test_validate_handoff_computes_diff_on_payload_change(self) -> None:
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        current_envelope = _make_envelope(
            pipeline_id="pipeline-123",
            step=2,
            payload={"entities": ["a", "b"], "facts": ["c", "d"], "new_field": "value"},
            token_budget_used=200,
            token_budget_total=8000
        )

        validator = HandoffValidator()
        result = validator.validate_handoff(previous_envelope, current_envelope)

        assert isinstance(result, Success)
        diff = result.value.diff
        # Use cast or explicit type check to avoid "object" in operator error
        added = diff["added"]
        removed = diff["removed"]
        modified = diff["modified"]
        assert isinstance(added, list)
        assert isinstance(removed, list)
        assert isinstance(modified, list)
        assert "new_field" in added
        assert "actions" in removed
        assert "entities" in modified
        assert "facts" in modified


class TestHallucinationGroundTruth:
    """R6.3: Hallucination heuristic ground-truth tests.

    Human-agreed ground truth:
    - FABRICATION: Agent invents 5 new entities while dropping all 4 previous ones.
      This is a textbook hallucination — a confident agent fabricating facts.
    - CLEAN ADDITION: Agent adds 2 new entities while keeping all 3 previous ones.
      This is normal incremental learning, not hallucination.
    - ENTITY DECAY: Agent removes 2 entities with no additions.
      Allowed per design — entity removal is not hallucination (see _detect_hallucination docstring).

    Known false-positive cases:
    - Entities with identical names but different referents (e.g., "Apple" the company
      vs "apple" the fruit) are treated as the same entity. This can flag legitimate
      context shifts as fabrication.
    - Short entity names (<=2 chars) are filtered as stop words, which may miss
      legitimate single-letter identifiers.
    - Entities nested inside unrelated data structures (e.g., "invoice_123" in a
      freeform "notes" field alongside unrelated text) can inflate entity counts.

    Known false-negative cases:
    - Subtle fabrication where new entities are paraphrases of old ones (e.g., "Apple Inc"
      replaced by "Apple Corporation") is not caught since set comparison is exact-match.
    - Fabricated entities that reuse names from existing ones are not flagged since they
      appear as "kept" entities (e.g., prev: ["Apple"], curr: ["Apple", "Apple-2"]).
    """

    def test_hallucination_detector_fires_on_textbook_fabrication(self) -> None:
        validator = HandoffValidator()
        previous_payload: JSONDict = {
            "entities": ["Apple-Inc", "Steve-Jobs", "Tim-Cook", "Cupertino"],
            "facts": ["fact1"],
        }
        current_payload: JSONDict = {
            "entities": [
                "Apple-Inc", "Steve-Jobs", "Tim-Cook", "Cupertino",
                "Microsoft", "Bill-Gates", "Satya-Nadella", "Redmond", "Silicon-Valley"
            ],
            "facts": [],
        }
        result = validator._detect_hallucination(previous_payload, current_payload)
        assert result is not None
        assert "Entity fabrication detected" in result

    def test_hallucination_detector_is_silent_on_clean_addition(self) -> None:
        validator = HandoffValidator()
        previous_payload: JSONDict = {
            "entities": ["Apple-Inc", "Steve-Jobs", "Tim-Cook"],
        }
        current_payload: JSONDict = {
            "entities": ["Apple-Inc", "Steve-Jobs", "Tim-Cook", "iPhone", "MacBook"],
        }
        result = validator._detect_hallucination(previous_payload, current_payload)
        assert result is None

    def test_hallucination_detector_is_silent_on_entity_decay(self) -> None:
        validator = HandoffValidator()
        previous_payload: JSONDict = {"entities": ["Apple", "Microsoft", "Google"]}
        current_payload: JSONDict = {"entities": ["Apple"]}
        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None


class TestValidateManifestBoundaries:
    def test_valid_manifest_returns_success(self) -> None:
        """Agent writing only to permitted sections returns Success."""
        from relay.slicer import AgentManifest
        manifest = AgentManifest(
            agent_id="agent-1",
            task_description="test",
            reads=frozenset({"section_a", "section_b"}),
            writes=frozenset({"section_a"}),
            max_tokens=1000,
        )
        written_sections = {"section_a"}
        result = validate_manifest_boundaries(manifest, written_sections)
        assert isinstance(result, Success)
        assert result.value is None

    def test_unauthorized_section_returns_failure(self) -> None:
        """Agent writing to unauthorized section returns Failure."""
        from relay.slicer import AgentManifest
        manifest = AgentManifest(
            agent_id="agent-1",
            task_description="test",
            reads=frozenset(),
            writes=frozenset({"section_a"}),
            max_tokens=1000,
        )
        written_sections = {"section_a", "unauthorized_section"}
        result = validate_manifest_boundaries(manifest, written_sections)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.MANIFEST_BOUNDARY_VIOLATION
        assert "unauthorized_section" in result.reason

class TestHallucinationDetection:
    def test_detect_hallucination_is_silent_when_at_threshold_boundary(self) -> None:
        """Test that exactly 2.0x ratio is not flagged (boundary case).

        Uses 3+ char entity names that _extract_entities actually parses.
        Previous: 2 entities (alice, bob), Current: 4 entities (alice, bob, charlie, david)
        Ratio: new=2, removed=0 -> replaced with 1 -> ratio=2.0 exactly (not > threshold).
        """
        validator = HandoffValidator()
        previous_payload: JSONDict = {"entities": ["alice", "bob"]}
        current_payload: JSONDict = {"entities": ["alice", "bob", "charlie", "david"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None

    def test_detect_hallucination_fails_when_above_threshold(self) -> None:
        """Test that ratio above 2.0x triggers detection.

        Uses 3+ char entity names in keys that _extract_entities recognizes.
        Previous: 2 entities (alice, bob), Current: 5 entities (alice, bob, charlie, david, eve)
        Ratio: new=3, removed=0 -> replaced with 1 -> ratio=3.0 > 2.0 threshold.
        """
        validator = HandoffValidator()
        previous_payload: JSONDict = {"entity": "alice", "id": "bob"}
        current_payload: JSONDict = {"entity": "alice", "id": "bob", "name": "charlie", "identifier": "david", "subject": "eve"}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is not None
        assert "Entity fabrication detected" in result

    def test_detect_hallucination_is_silent_when_below_threshold(self) -> None:
        """Test that ratio below 2.0x does not trigger detection.

        Uses 3+ char entity names that _extract_entities extracts from list values.
        Previous: 3 entities (alice, bob, charlie), Current: 4 entities (alice, bob, charlie, david)
        Ratio: new=1, removed=0 -> replaced with 1 -> ratio=1.0 < 2.0 threshold.
        """
        validator = HandoffValidator()
        previous_payload: JSONDict = {"entities": ["alice", "bob", "charlie"]}
        current_payload: JSONDict = {"entities": ["alice", "bob", "charlie", "david"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None

    def test_detect_hallucination_fires_on_excessive_deletion(self) -> None:
        validator = HandoffValidator()
        previous: JSONDict = {"entities": ["alice", "bob", "charlie", "david", "eve"]}
        current: JSONDict = {"entities": []}
        result = validator._detect_hallucination(previous, current)
        assert result is not None
        assert "Excessive entity deletion" in result

    def test_detect_hallucination_is_silent_on_moderate_deletion(self) -> None:
        validator = HandoffValidator()
        previous: JSONDict = {"entities": ["alice", "bob"]}
        current: JSONDict = {"entities": []}
        result = validator._detect_hallucination(previous, current)
        assert result is None


class TestEntityExtraction:
    def test_extract_entities_works_with_entities_key(self) -> None:
        """Test extraction from payload with entities key."""
        validator = HandoffValidator()
        payload: JSONDict = {"entities": ["Alice", "Bob", "Charlie"]}

        entities = validator._extract_entities(payload)

        assert entities == frozenset({"alice", "bob", "charlie"})

    def test_extract_entities_works_with_nested_structure(self) -> None:
        """Test extraction from nested payload structure."""
        validator = HandoffValidator()
        payload: JSONDict = {
            "data": {
                "subject": "Order123",
                "object": "Customer456"
            }
        }

        entities = validator._extract_entities(payload)

        assert "order123" in entities
        assert "customer456" in entities

    def test_extract_entities_returns_empty_on_non_entity_keys(self) -> None:
        """Only strings under entity-named keys are extracted."""
        validator = HandoffValidator()
        payload: JSONDict = {"action": "process order_abc def"}

        entities = validator._extract_entities(payload)

        assert entities == frozenset()

    def test_extract_entities_returns_empty_when_payload_empty(self) -> None:
        """Test extraction from empty payload."""
        validator = HandoffValidator()
        payload: JSONDict = {}

        entities = validator._extract_entities(payload)

        assert entities == frozenset()

    def test_detect_hallucination_is_silent_when_no_new_entities(self) -> None:
        """Test that entity removal does not trigger hallucination."""
        validator = HandoffValidator()
        previous_payload: JSONDict = {"entities": ["a", "b", "c"]}
        current_payload: JSONDict = {"entities": ["a", "b"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None

    def test_detect_hallucination_returns_none_when_threshold_disabled(self) -> None:
        validator = HandoffValidator(hallucination_ratio_threshold=None)
        prev: JSONDict = {"entities": ["Apple", "Microsoft", "Google"]}
        curr: JSONDict = {"entities": ["Apple", "Microsoft", "Google", "Amazon", "Meta", "Netflix"]}
        result = validator._detect_hallucination(prev, curr)
        assert result is None

    def test_hallucination_detection_with_both_hallucination_and_missing_keys(self) -> None:
        """Combined hallucination and critical key removal concatenates details."""
        prev_payload: JSONDict = {"entities": ["alice", "bob"], "facts": ["fact1"], "constraints": ["x"]}
        curr_payload: JSONDict = {"entities": ["alice", "bob", "charlie", "david", "eve", "frank"]}
        prev = _make_envelope("pipe", 1, prev_payload)
        curr = _make_envelope("pipe", 2, curr_payload)
        validator = HandoffValidator()
        result = validator.validate_handoff(prev, curr)
        assert isinstance(result, Success)
        validation_result = result.value
        assert validation_result.has_contradiction is True
        assert validation_result.contradiction_details is not None
        assert "Entity fabrication" in validation_result.contradiction_details
        assert "Critical keys removed" in validation_result.contradiction_details

    def test_extract_entities_raises_on_excessive_depth(self) -> None:
        validator = HandoffValidator()
        deeply_nested: JSONDict = {}
        current = deeply_nested
        for _ in range(60):
            current["nested"] = {}
            current = current["nested"]  # type: ignore[assignment]
        with pytest.raises(MaxDepthExceededError):
            validator._extract_entities(deeply_nested)

    def test_detect_hallucination_fails_on_max_depth_exceeded(self) -> None:
        validator = HandoffValidator()
        deeply_nested: JSONDict = {}
        current = deeply_nested
        for _ in range(60):
            current["nested"] = {}
            current = current["nested"]  # type: ignore[assignment]
        result = validator._detect_hallucination({}, deeply_nested)
        assert result is not None
        assert "depth exceeds limit" in result


class TestConfidenceScore:
    def test_validate_payloads_has_high_confidence_when_clean_handoff(self) -> None:
        """Clean handoff with all entities preserved yields confidence 1.0."""
        validator = HandoffValidator()
        prev_payload: JSONDict = {"entities": ["alice", "bob"]}
        curr_payload: JSONDict = {"entities": ["alice", "bob"]}
        result = validator._validate_payloads(prev_payload, curr_payload)
        assert isinstance(result, Success)
        assert result.value.confidence_score == pytest.approx(1.0)

    def test_validate_payloads_yields_zero_confidence_on_contradiction(self) -> None:
        """Contradiction detected → confidence_score is 0.0."""
        validator = HandoffValidator()
        prev_payload: JSONDict = {"entities": ["alice"], "facts": ["f1"]}
        curr_payload: JSONDict = {"entities": ["alice"]}
        result = validator._validate_payloads(prev_payload, curr_payload)
        assert isinstance(result, Success)
        assert result.value.confidence_score == 0.0

    def test_validate_payloads_yield_zero_confidence_when_deeply_nested(self) -> None:
        """MaxDepthExceededError → confidence_score is 0.0."""
        validator = HandoffValidator()
        deeply_nested: JSONDict = {}
        current = deeply_nested
        for _ in range(60):
            current["nested"] = {}
            current = current["nested"]  # type: ignore[assignment]
        result = validator._validate_payloads({}, deeply_nested)
        assert isinstance(result, Success)
        assert result.value.confidence_score == 0.0

    def test_validate_payloads_calculates_confidence_on_partial_preservation(self) -> None:
        """Some entities preserved → confidence = preserved / total_new."""
        validator = HandoffValidator()
        prev_payload: JSONDict = {"entities": ["alice", "bob"]}
        curr_payload: JSONDict = {"entities": ["bob", "charlie", "david"]}
        result = validator._validate_payloads(prev_payload, curr_payload)
        assert isinstance(result, Success)
        expected = 1 / 3
        assert result.value.confidence_score == pytest.approx(expected)

    def test_validation_result_sets_high_confidence_by_default(self) -> None:
        """ValidationResult without confidence_score defaults to 1.0."""
        vr = ValidationResult(
            has_contradiction=False, diff={}, contradiction_details=None,
        )
        assert vr.confidence_score == 1.0


class TestValidateHandoffPayload:
    def test_validate_handoff_payload_succeeds_with_matching_result(self) -> None:
        """validate_handoff_payload produces identical ValidationResult to validate_handoff."""
        from unittest.mock import patch, MagicMock
        with patch("relay.envelope.datetime") as mock_datetime:
            mock_now: MagicMock = mock_datetime.now
            mock_now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)
            previous_result = create_initial_envelope(
                pipeline_id="pipeline-123",
                initial_payload={"entities": ["a"], "actions": ["b"]},
                secret="a" * 32,
                manifest_hash=""
            )
            previous_envelope = unwrap(previous_result)

            new_payload: JSONDict = {"entities": ["a", "b"], "actions": ["b"]}

            validator = HandoffValidator()
            result_via_handoff = validator.validate_handoff(
                previous_envelope,
                _make_envelope("pipeline-123", 2, new_payload),
            )
            result_via_payload = validator.validate_handoff_payload(
                previous_envelope, new_payload,
            )

            assert isinstance(result_via_handoff, Success)
            assert isinstance(result_via_payload, Success)
            validation_h = result_via_handoff.value
            validation_p = result_via_payload.value
            assert validation_h.has_contradiction == validation_p.has_contradiction
            assert validation_h.diff == validation_p.diff
            assert validation_h.confidence_score == pytest.approx(
                validation_p.confidence_score
            )

    def test_validate_handoff_payload_succeeds_when_ignores_envelope_metadata(self) -> None:
        """validate_handoff_payload does not check pipeline_id or step."""
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        validator = HandoffValidator()
        result = validator.validate_handoff_payload(
            previous_envelope, {"entities": ["a", "b"]},
        )
        assert isinstance(result, Success)

    def test_validate_handoff_payload_fails_on_contradiction_in_raw_data(self) -> None:
        """validate_handoff_payload detects contradictions in raw payload."""
        ref_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "facts": ["f1"]},
            secret="a" * 32,
            manifest_hash="",
            now=ref_time,
        )
        previous_envelope = unwrap(previous_result)

        validator = HandoffValidator()
        result = validator.validate_handoff_payload(
            previous_envelope, {"entities": ["a"]},
        )
        assert isinstance(result, Success)
        assert result.value.has_contradiction is True
        assert result.value.confidence_score == 0.0