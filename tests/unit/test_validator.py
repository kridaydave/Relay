"""Unit tests for relay.validator."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from relay.envelope import ContextEnvelope, create_initial_envelope
from relay.validator import HandoffValidator, ValidationResult
from relay.types import Success, Failure


RELAY_VERSION = "0.1.0"


def _make_envelope(
    pipeline_id: str,
    step: int,
    payload: dict,
    token_budget_used: int = 100,
    token_budget_total: int = 8000,
    timestamp: datetime = None,
    signature: str = "sig"
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
        signature=signature
    )


class TestValidateHandoff:
    @patch("relay.envelope.datetime")
    def test_validator_passes_clean_handoff(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"]},
            secret="secret"
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

        previous_result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={"entities": ["a"], "actions": ["b"], "facts": ["c"], "constraints": ["x"]},
            secret="secret"
        )
        previous_envelope = previous_result.value

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
            secret="secret"
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