"""Unit tests for relay.envelope module."""

import json
import tempfile
from datetime import datetime, timezone

import pytest

from relay.envelope import (
    RELAY_VERSION,
    ContextEnvelope,
    create_initial_envelope,
    create_next_envelope,
    verify_signature,
    _compute_signature,
    _estimate_tokens,
)


@pytest.fixture
def secret():
    return "test-secret"


@pytest.fixture
def initial_payload():
    return {"data": "test", "count": 42}


@pytest.fixture
def next_payload():
    return {"data": "updated", "count": 43}


class TestCreateInitialEnvelope:
    def test_create_initial_envelope_with_valid_inputs(self, secret, initial_payload):
        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )

        assert isinstance(result.value, ContextEnvelope)
        envelope = result.value
        assert envelope.relay_version == RELAY_VERSION
        assert envelope.pipeline_id == "pipeline-123"
        assert envelope.step == 1
        assert envelope.token_budget_total == 8000
        assert envelope.payload == initial_payload
        assert envelope.manifest_hash == ""
        assert envelope.signature != ""

    def test_create_initial_envelope_with_manifest_hash(self, secret, initial_payload):
        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="abc123",
        )

        assert result.value.manifest_hash == "abc123"

    def test_create_initial_envelope_fails_on_empty_pipeline_id(
        self, secret, initial_payload
    ):
        result = create_initial_envelope(
            pipeline_id="", initial_payload=initial_payload, secret=secret, manifest_hash=""
        )

        assert isinstance(result.reason, str)
        assert "pipeline_id" in result.reason.lower()
        assert result.code == "INVALID_PIPELINE_ID"

    def test_create_initial_envelope_fails_on_empty_payload(self, secret, initial_payload):
        result = create_initial_envelope(
            pipeline_id="pipeline-123", initial_payload={}, secret=secret, manifest_hash=""
        )

        assert isinstance(result.reason, str)
        assert "payload" in result.reason.lower()
        assert result.code == "INVALID_PAYLOAD"


class TestCreateNextEnvelope:
    def test_create_next_envelope_increments_step(self, secret, initial_payload, next_payload):
        first = create_initial_envelope(
            pipeline_id="pipeline-123", initial_payload=initial_payload, secret=secret, manifest_hash=""
        )
        second = create_next_envelope(
            previous_envelope=first.value, secret=secret, agent_output=next_payload, manifest_hash=""
        )

        assert second.value.step == 2
        assert second.value.pipeline_id == "pipeline-123"

    def test_create_next_envelope_updates_token_budget(
        self, secret, initial_payload, next_payload
    ):
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            token_budget_total=8000,
            manifest_hash="",
        )
        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output=next_payload,
            manifest_hash="",
        )

        assert second.value.token_budget_used >= first.value.token_budget_used

    def test_create_next_envelope_inherits_previous_fields(
        self, secret, initial_payload, next_payload
    ):
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output=next_payload,
            manifest_hash="",
        )

        assert second.value.pipeline_id == first.value.pipeline_id
        assert second.value.token_budget_total == first.value.token_budget_total

    def test_create_next_envelope_fails_on_token_budget_exceeded(
        self, secret, initial_payload
    ):
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            token_budget_total=100,
            manifest_hash="",
        )
        large_payload = {"data": "x" * 1000}

        second = create_next_envelope(
            previous_envelope=first.value, secret=secret, agent_output=large_payload, manifest_hash=""
        )

        assert isinstance(second.reason, str)
        assert "budget" in second.reason.lower()
        assert second.code == "TOKEN_BUDGET_EXCEEDED"

    def test_create_next_envelope_fails_on_empty_agent_output(self, secret, initial_payload):
        first = create_initial_envelope(
            pipeline_id="pipeline-123", initial_payload=initial_payload, secret=secret, manifest_hash=""
        )

        second = create_next_envelope(
            previous_envelope=first.value, secret=secret, agent_output={}, manifest_hash=""
        )

        assert isinstance(second.reason, str)
        assert second.code == "INVALID_PAYLOAD"
        assert second.code == "INVALID_PAYLOAD"


class TestVerifySignature:
    def test_verify_signature_returns_true_for_valid_signature(
        self, secret, initial_payload
    ):
        envelope = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        ).value

        assert verify_signature(envelope, secret) is True

    def test_verify_signature_returns_false_for_invalid_signature(
        self, secret, initial_payload
    ):
        envelope = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        ).value

        assert verify_signature(envelope, "wrong-secret") is False

    def test_verify_signature_fails_on_tampered_budget(
        self, secret, initial_payload
    ):
        envelope = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        ).value

        tampered = ContextEnvelope(
            relay_version=envelope.relay_version,
            pipeline_id=envelope.pipeline_id,
            step=envelope.step,
            timestamp=envelope.timestamp,
            token_budget_used=envelope.token_budget_used + 1,
            token_budget_total=envelope.token_budget_total,
            payload=envelope.payload,
            manifest_hash=envelope.manifest_hash,
            signature=envelope.signature,
        )

        assert verify_signature(tampered, secret) is False


class TestTokenEstimation:
    def test_token_estimate_within_realistic_tolerance(self):
        payload = {"key": "value" * 50}
        estimate = _estimate_tokens(payload)
        json_str = json.dumps(payload, sort_keys=True)

        assert estimate > 0
        assert estimate == len(json_str) // 3, "Must use formula: len(json_str) // 3"


class TestContextEnvelope:
    def test_context_envelope_is_frozen_dataclass(self):
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=datetime.now(timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "test"},
            manifest_hash="",
            signature="sig",
        )

        with pytest.raises(Exception):
            envelope.step = 2


class TestContextEnvelopeWithManifestHash:
    """Tests for ContextEnvelope.with_manifest_hash()."""

    def test_with_manifest_hash_returns_new_envelope(self):
        original = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test-pipeline",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "test"},
            manifest_hash="original-hash",
            signature="original-sig",
        )

        result = original.with_manifest_hash("new-hash")

        assert result is not original
        assert result.manifest_hash == "new-hash"
        assert result.pipeline_id == "test-pipeline"
        assert result.step == 1
        assert result.payload == {"data": "test"}
        assert result.signature == "original-sig"

    def test_with_manifest_hash_preserves_all_other_fields(self):
        original = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-abc",
            step=5,
            timestamp=datetime(2024, 6, 15, tzinfo=timezone.utc),
            token_budget_used=500,
            token_budget_total=12000,
            payload={"entities": ["a", "b"], "actions": ["x"]},
            manifest_hash="old-hash",
            signature="sig-xyz",
        )

        result = original.with_manifest_hash("new-hash-xyz")

        assert result.relay_version == RELAY_VERSION
        assert result.pipeline_id == "pipeline-abc"
        assert result.step == 5
        assert result.timestamp == datetime(2024, 6, 15, tzinfo=timezone.utc)
        assert result.token_budget_used == 500
        assert result.token_budget_total == 12000
        assert result.payload == {"entities": ["a", "b"], "actions": ["x"]}
        assert result.manifest_hash == "new-hash-xyz"
        assert result.signature == "sig-xyz"

    def test_with_manifest_hash_is_idempotent(self):
        original = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=datetime.now(timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "test"},
            manifest_hash="hash1",
            signature="sig",
        )

        intermediate = original.with_manifest_hash("hash2")
        final = intermediate.with_manifest_hash("hash3")

        assert final.manifest_hash == "hash3"
        assert final.step == original.step
        assert final.pipeline_id == original.pipeline_id
