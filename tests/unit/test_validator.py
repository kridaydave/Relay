"""Unit tests for relay.validator."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope, create_initial_envelope
from relay.validator import HandoffValidator, ValidationResult
from relay.types import Success, Failure


def _make_envelope(
    pipeline_id: str,
    step: int,
    payload: dict,
    token_budget_used: int = 100,
    token_budget_total: int = 8000,
    timestamp: datetime = None,
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
    @patch("relay.envelope.datetime")
    def test_validate_handoff_pipeline_id_mismatch(self, mock_datetime):
        """Mismatched pipeline IDs must return Failure."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"]},
            secret="a" * 32,
            manifest_hash=""
        )
        previous_envelope = previous_result.value

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
        assert result.code == "PIPELINE_MISMATCH"

    @patch("relay.envelope.datetime")
    def test_validate_handoff_step_not_increasing(self, mock_datetime):
        """Step must increase between envelopes."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)
        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"]},
            secret="a" * 32,
            manifest_hash=""
        )
        previous_envelope = previous_result.value

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
        assert result.code == "INVALID_STEP"

    @patch("relay.envelope.datetime")
    def test_validator_passes_clean_handoff(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"]},
            secret="a" * 32,
            manifest_hash=""
        )
        previous_envelope = previous_result.value

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

    @patch("relay.envelope.datetime")
    def test_validator_detects_contradiction_when_critical_key_missing(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

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
        assert "Critical keys removed" in validation_result.contradiction_details
        assert "facts" in validation_result.contradiction_details
        assert "constraints" in validation_result.contradiction_details


class TestShouldRollback:
    def test_validator_should_rollback_returns_true_on_contradiction(self):
        validation_result = ValidationResult(
            has_contradiction=True,
            diff={"added": [], "removed": [], "modified": []},
            contradiction_details="Some contradiction"
        )

        validator = HandoffValidator()
        should_rollback = validator.should_rollback(validation_result)

        assert should_rollback is True

    def test_validator_should_rollback_returns_false_on_clean_validation(self):
        validation_result = ValidationResult(
            has_contradiction=False,
            diff={"added": [], "removed": [], "modified": []},
            contradiction_details=None
        )

        validator = HandoffValidator()
        should_rollback = validator.should_rollback(validation_result)

        assert should_rollback is False


class TestComputeDiff:
    @patch("relay.envelope.datetime")
    def test_validator_computes_diff_between_payloads(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"]},
            secret="a" * 32,
            manifest_hash=""
        )
        previous_envelope = previous_result.value

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
        assert "new_field" in diff["added"]
        assert "actions" in diff["removed"]
        assert "entities" in diff["modified"]
        assert "facts" in diff["modified"]


class TestHallucinationDetection:
    def test_hallucination_detection_at_threshold(self):
        """Test that exactly 2.0x ratio is not flagged (boundary case).

        Uses 3+ char entity names that _extract_entities actually parses.
        Previous: 2 entities (alice, bob), Current: 4 entities (alice, bob, charlie, david)
        Ratio: new=2, removed=0 -> replaced with 1 -> ratio=2.0 exactly (not > threshold).
        """
        validator = HandoffValidator()
        previous_payload = {"entities": ["alice", "bob"]}
        current_payload = {"entities": ["alice", "bob", "charlie", "david"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None

    def test_hallucination_detection_above_threshold(self):
        """Test that ratio above 2.0x triggers detection.

        Uses 3+ char entity names in keys that _extract_entities recognizes.
        Previous: 2 entities (alice, bob), Current: 5 entities (alice, bob, charlie, david, eve)
        Ratio: new=3, removed=0 -> replaced with 1 -> ratio=3.0 > 2.0 threshold.
        """
        validator = HandoffValidator()
        previous_payload = {"entity": "alice", "id": "bob"}
        current_payload = {"entity": "alice", "id": "bob", "name": "charlie", "identifier": "david", "subject": "eve"}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is not None
        assert "Entity fabrication detected" in result

    def test_hallucination_detection_below_threshold(self):
        """Test that ratio below 2.0x does not trigger detection.

        Uses 3+ char entity names that _extract_entities extracts from list values.
        Previous: 3 entities (alice, bob, charlie), Current: 4 entities (alice, bob, charlie, david)
        Ratio: new=1, removed=0 -> replaced with 1 -> ratio=1.0 < 2.0 threshold.
        """
        validator = HandoffValidator()
        previous_payload = {"entities": ["alice", "bob", "charlie"]}
        current_payload = {"entities": ["alice", "bob", "charlie", "david"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None


class TestEntityExtraction:
    def test_extract_entities_from_entities_list(self):
        """Test extraction from payload with entities key."""
        validator = HandoffValidator()
        payload = {"entities": ["Alice", "Bob", "Charlie"]}

        entities = validator._extract_entities(payload)

        assert entities == frozenset({"alice", "bob", "charlie"})

    def test_extract_entities_from_nested_structure(self):
        """Test extraction from nested payload structure."""
        validator = HandoffValidator()
        payload = {
            "data": {
                "subject": "Order123",
                "object": "Customer456"
            }
        }

        entities = validator._extract_entities(payload)

        assert "order123" in entities
        assert "customer456" in entities

    def test_extract_entities_from_string_values(self):
        """Test extraction from string values in payload."""
        validator = HandoffValidator()
        payload = {"action": "process order_abc def"}

        entities = validator._extract_entities(payload)

        assert "process order_abc def" in entities

    def test_extract_entities_empty_payload(self):
        """Test extraction from empty payload."""
        validator = HandoffValidator()
        payload = {}

        entities = validator._extract_entities(payload)

        assert entities == frozenset()

    def test_extract_entities_no_new_entities(self):
        """Test that entity removal does not trigger hallucination."""
        validator = HandoffValidator()
        previous_payload = {"entities": ["a", "b", "c"]}
        current_payload = {"entities": ["a", "b"]}

        result = validator._detect_hallucination(previous_payload, current_payload)

        assert result is None