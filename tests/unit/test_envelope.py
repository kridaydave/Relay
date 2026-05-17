"""Unit tests for relay.envelope module."""

import json
import tempfile
from datetime import datetime, timezone

import pytest

from relay.envelope import (
    RELAY_VERSION,
    ContextEnvelope,
    compute_signature,
    create_initial_envelope,
    create_next_envelope,
    estimate_tokens,
    serialize_slice,
    verify_signature,
    validate_pipeline_id,
)
from relay.types import ErrorCode, Failure, JSONDict, Success


@pytest.fixture
def secret() -> str:
    return "a" * 32


@pytest.fixture
def initial_payload() -> "JSONDict":
    return {"data": "initial"}


@pytest.fixture
def next_payload() -> "JSONDict":
    return {"result": "output"}


class TestValidatePipelineId:
    def test_validate_pipeline_id_returns_success_when_id_is_valid(self) -> None:
        result = validate_pipeline_id("valid-id_123")
        assert isinstance(result, Success)
        assert result.value == "valid-id_123"

    def test_validate_pipeline_id_returns_failure_when_id_contains_unsafe_chars(self) -> None:
        # Test path traversal characters
        result = validate_pipeline_id("../etc/passwd")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

        # Test other invalid characters
        result = validate_pipeline_id("pipeline!@#")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_validate_pipeline_id_returns_failure_when_id_is_too_long(self) -> None:
        long_id = "a" * 129
        result = validate_pipeline_id(long_id)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_validate_pipeline_id_returns_failure_when_id_is_empty(self) -> None:
        result = validate_pipeline_id("")
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID


class TestCreateInitialEnvelope:
    def test_create_initial_envelope_with_valid_inputs(self, secret: str, initial_payload: JSONDict) -> None:
        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )

        assert isinstance(result, Success)
        assert isinstance(result.value, ContextEnvelope)
        envelope = result.value
        assert envelope.relay_version == RELAY_VERSION
        assert envelope.pipeline_id == "pipeline-123"
        assert envelope.step == 1
        assert envelope.token_budget_total == 8000
        assert envelope.payload == initial_payload
        assert envelope.manifest_hash == ""
        assert envelope.signature != ""

    def test_create_initial_envelope_with_manifest_hash(self, secret: str, initial_payload: JSONDict) -> None:
        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="abc123",
        )

        assert isinstance(result, Success)
        assert result.value.manifest_hash == "abc123"

    def test_create_initial_envelope_fails_on_empty_pipeline_id(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        result = create_initial_envelope(
            pipeline_id="",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )

        assert isinstance(result, Failure)
        assert "pipeline_id" in result.reason.lower()
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_create_initial_envelope_fails_on_empty_payload(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        result = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload={},
            secret=secret,
            manifest_hash="",
        )

        assert isinstance(result, Failure)
        assert "payload" in result.reason.lower()
        assert result.code == ErrorCode.INVALID_PAYLOAD


class TestCreateNextEnvelope:
    def test_step_increments_when_next_envelope_created(
        self, secret: str, initial_payload: JSONDict, next_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output=next_payload,
            manifest_hash="",
        )

        assert isinstance(second, Success)
        assert second.value.step == 2
        assert second.value.pipeline_id == "pipeline-123"

    def test_create_next_envelope_updates_token_budget(
        self, secret: str, initial_payload: JSONDict, next_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            token_budget_total=8000,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output=next_payload,
            manifest_hash="",
        )

        assert isinstance(second, Success)
        assert second.value.token_budget_used >= first.value.token_budget_used

    def test_fields_are_inherited_when_next_envelope_created(
        self, secret: str, initial_payload: JSONDict, next_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output=next_payload,
            manifest_hash="",
        )

        assert isinstance(second, Success)
        assert second.value.pipeline_id == first.value.pipeline_id
        assert second.value.token_budget_total == first.value.token_budget_total

    def test_create_next_envelope_fails_on_empty_agent_output(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)

        second = create_next_envelope(
            previous_envelope=first.value,
            secret=secret,
            agent_output={},
            manifest_hash="",
        )

        assert isinstance(second, Failure)
        assert second.code == ErrorCode.INVALID_PAYLOAD


class TestVerifySignature:
    def test_verify_signature_returns_true_for_valid_signature(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        envelope = first.value

        assert verify_signature(envelope, secret) is True

    def test_verify_signature_returns_false_for_invalid_signature(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        envelope = first.value

        assert verify_signature(envelope, "wrong-secret") is False

    def test_verify_signature_fails_on_tampered_budget(self, secret: str, initial_payload: JSONDict) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        envelope = first.value

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

    def test_verify_signature_passes_when_envelope_is_fresh_and_within_max_age(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        first = create_initial_envelope(
            pipeline_id="pipeline-123",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(first, Success)
        envelope = first.value

        assert verify_signature(envelope, secret, max_age_seconds=3600) is True

    def test_verify_signature_fails_when_envelope_is_stale_and_exceeds_max_age(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=old_ts,
            token_budget_used=0,
            token_budget_total=8000,
            payload=initial_payload,
            manifest_hash="",
            signature="",
        )
        signed = compute_signature(envelope, secret)
        stale = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=old_ts,
            token_budget_used=0,
            token_budget_total=8000,
            payload=initial_payload,
            manifest_hash="",
            signature=signed,
        )

        assert verify_signature(stale, secret, max_age_seconds=1) is False

    def test_verify_signature_passes_when_max_age_is_none_regardless_of_age(
        self, secret: str, initial_payload: JSONDict
    ) -> None:
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
        envelope = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=old_ts,
            token_budget_used=0,
            token_budget_total=8000,
            payload=initial_payload,
            manifest_hash="",
            signature="",
        )
        signed = compute_signature(envelope, secret)
        stale = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="pipeline-123",
            step=1,
            timestamp=old_ts,
            token_budget_used=0,
            token_budget_total=8000,
            payload=initial_payload,
            manifest_hash="",
            signature=signed,
        )

        assert verify_signature(stale, secret, max_age_seconds=None) is True


class TestTokenEstimation:
    """Ground-truth benchmark for estimate_tokens per R17.

    Ground truth: English prose and JSON tokenise at roughly 0.25–0.40
    tokens/char under BPE tokenisers (GPT-4 family, cl100k_base).
    Our formula: len(json) // 3 ≈ 0.33 tokens/char — within that range.

    The 3x tolerance is intentionally wide because the heuristic is coarse.
    For precise counting, use TiktokenCounter. These tests catch a completely
    broken implementation (returning 0, returning len, etc.).
    """

    PAYLOADS: list[JSONDict] = [
        {"summary": "Apple reported strong Q4 revenue growth.", "step": 1},
        {
            "entities": ["Alice", "Bob", "Charlie"],
            "facts": ["revenue up", "costs flat"],
        },
        {"data": "x" * 200},
        {"nested": {"a": {"b": {"c": "deep"}}}},
    ]

    def test_estimate_tokens_is_importable_when_using_packers(self) -> None:
        """packers re-exports estimate_tokens from envelope (consolidated, no duplicate)."""
        from relay.slicer.packers import estimate_tokens as packer_estimate

        assert packer_estimate is estimate_tokens
        for payload in self.PAYLOADS:
            assert packer_estimate(payload) == estimate_tokens(payload)

    def test_estimate_is_positive_for_all_representative_payloads(self) -> None:
        for payload in self.PAYLOADS:
            assert estimate_tokens(payload) > 0, f"Zero estimate for {payload}"

    def test_estimate_stays_within_tolerance_when_measured(self) -> None:
        for payload in self.PAYLOADS:
            estimate = estimate_tokens(payload)
            json_len = len(json.dumps(payload, sort_keys=True))
            baseline = max(1, json_len // 4)
            assert estimate >= baseline // 3, (
                f"Estimate {estimate} too low vs baseline {baseline} for {payload}"
            )
            assert estimate <= baseline * 3, (
                f"Estimate {estimate} too high vs baseline {baseline} for {payload}"
            )

    def test_estimate_increases_when_payload_is_larger(self) -> None:
        small: JSONDict = {"x": "a" * 10}
        large: JSONDict = {"x": "a" * 1000}
        assert estimate_tokens(large) > estimate_tokens(small)


class TestContextEnvelope:
    def test_envelope_is_immutable_when_frozen(self) -> None:
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
            envelope.step = 2  # type: ignore[misc]


class TestContextEnvelopeWithManifestHash:
    """Tests for ContextEnvelope.with_manifest_hash()."""

    def test_with_manifest_hash_returns_new_envelope(self) -> None:
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

    def test_with_manifest_hash_preserves_all_other_fields(self) -> None:
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

    def test_with_manifest_hash_is_idempotent(self) -> None:
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


class TestPipelineIdValidation:
    def test_rejects_pipeline_id_with_invalid_chars(self, secret: str, initial_payload: JSONDict) -> None:
        result = create_initial_envelope(
            pipeline_id="bad pipe!",
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID

    def test_initial_envelope_fails_when_pipeline_id_is_too_long(self, secret: str, initial_payload: JSONDict) -> None:
        result = create_initial_envelope(
            pipeline_id="x" * 129,
            initial_payload=initial_payload,
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PIPELINE_ID


class TestWithSignature:
    def test_with_signature_returns_new_envelope(self) -> None:
        original = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            token_budget_used=100,
            token_budget_total=8000,
            payload={"k": "v"},
            manifest_hash="",
            signature="old",
        )
        result = original.with_signature("new-sig")
        assert result is not original
        assert result.signature == "new-sig"
        assert result.manifest_hash == original.manifest_hash


class TestComputeSignature:
    def test_signature_is_deterministic_when_inputs_are_same(self, secret: str) -> None:
        res1 = create_initial_envelope(
            pipeline_id="pipe",
            initial_payload={"k": "v"},
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(res1, Success)
        env1 = res1.value

        res2 = create_initial_envelope(
            pipeline_id="pipe",
            initial_payload={"k": "v"},
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(res2, Success)
        env2 = res2.value

        sig1 = compute_signature(env1, secret)
        sig2 = compute_signature(env2, secret)
        assert sig1 == sig2

    def test_compute_signature_differs_for_different_secret(self, secret: str) -> None:
        res = create_initial_envelope(
            pipeline_id="pipe",
            initial_payload={"k": "v"},
            secret=secret,
            manifest_hash="",
        )
        assert isinstance(res, Success)
        env = res.value

        sig1 = compute_signature(env, secret)
        sig2 = compute_signature(env, "x" * 32)
        assert sig1 != sig2


class TestSerializeSlice:
    def test_serialize_slice_returns_compact_json(self) -> None:
        result = serialize_slice({"b": 2, "a": 1})
        assert result == '{"a":1,"b":2}'

    def test_serialize_slice_returns_empty_json_when_dict_is_empty(self) -> None:
        assert serialize_slice({}) == "{}"


class TestForkFields:
    def test_fork_fields_are_none_when_envelope_is_sequential(self) -> None:
        """Sequential envelopes have all fork fields as None."""
        from relay.envelope import create_initial_envelope

        result = create_initial_envelope(
            pipeline_id="test",
            initial_payload={"data": "x"},
            secret="a" * 32,
            manifest_hash="",
        )
        assert isinstance(result, Success)
        env = result.value
        assert env.fork_id is None
        assert env.join_strategy is None
        assert env.fork_count is None
        assert env.forks_succeeded is None

    def test_with_fork_metadata_sets_all_fields(self) -> None:
        """with_fork_metadata returns envelope with all four fork fields set."""
        from relay.envelope import create_initial_envelope

        res = create_initial_envelope(
            pipeline_id="test",
            initial_payload={"data": "x"},
            secret="a" * 32,
            manifest_hash="",
        )
        assert isinstance(res, Success)
        env = res.value
        meta = env.with_fork_metadata(
            fork_id="uuid-1",
            join_strategy="UNION",
            fork_count=3,
            forks_succeeded=2,
        )
        assert meta.fork_id == "uuid-1"
        assert meta.join_strategy == "UNION"
        assert meta.fork_count == 3
        assert meta.forks_succeeded == 2
        assert meta.signature == ""

    def test_with_fork_metadata_invalidates_signature(self) -> None:
        """with_fork_metadata sets signature to empty string."""
        from relay.envelope import create_initial_envelope

        res = create_initial_envelope(
            pipeline_id="test",
            initial_payload={"data": "x"},
            secret="a" * 32,
            manifest_hash="",
        )
        assert isinstance(res, Success)
        env = res.value
        meta = env.with_fork_metadata(
            fork_id="uuid-1",
            join_strategy="VOTE",
            fork_count=1,
            forks_succeeded=1,
        )
        assert meta.signature == ""

    def test_signature_is_unchanged_when_envelope_is_sequential(self) -> None:
        """Sequential envelope (fork fields None) produces same signature as v0.3 format."""
        from datetime import datetime, timezone

        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        env = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=ts,
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "x"},
            manifest_hash="",
            signature="",
        )
        secret = "a" * 32
        sig = compute_signature(env, secret)
        env_with_fork_none = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=ts,
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "x"},
            manifest_hash="",
            signature="",
            fork_id=None,
            join_strategy=None,
            fork_count=None,
            forks_succeeded=None,
        )
        sig_with_none = compute_signature(env_with_fork_none, secret)
        assert sig == sig_with_none

    def test_signature_includes_fork_suffix_when_envelope_is_parallel(self) -> None:
        """Parallel envelope signature differs from sequential when fork_id is set."""
        from datetime import datetime, timezone

        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        env_seq = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=ts,
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "x"},
            manifest_hash="",
            signature="",
        )
        env_par = ContextEnvelope(
            relay_version=RELAY_VERSION,
            pipeline_id="test",
            step=1,
            timestamp=ts,
            token_budget_used=100,
            token_budget_total=8000,
            payload={"data": "x"},
            manifest_hash="",
            signature="",
            fork_id="uuid-1",
            join_strategy="UNION",
            fork_count=2,
            forks_succeeded=2,
        )
        secret = "a" * 32
        assert compute_signature(env_seq, secret) != compute_signature(env_par, secret)

    def test_verify_signature_passes_after_re_signing_fork_metadata(self) -> None:
        """Envelope with fork metadata verifies after re-signing."""
        from relay.envelope import create_initial_envelope

        res = create_initial_envelope(
            pipeline_id="test",
            initial_payload={"data": "x"},
            secret="a" * 32,
            manifest_hash="",
        )
        assert isinstance(res, Success)
        env = res.value
        meta = env.with_fork_metadata(
            fork_id="uuid-1",
            join_strategy="UNION",
            fork_count=2,
            forks_succeeded=2,
        )
        signed = meta.with_signature(compute_signature(meta, "a" * 32))
        assert verify_signature(signed, "a" * 32)


class TestContextEnvelopeFieldConstraints:
    def test_constructor_fails_when_token_budget_used_is_negative(self) -> None:
        """Negative token_budget_used raises ValueError."""
        from datetime import datetime, timezone

        with pytest.raises(ValueError, match="token_budget_used"):
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test",
                step=1,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=-100,
                token_budget_total=8000,
                payload={"data": "x"},
                manifest_hash="",
                signature="",
            )

    def test_constructor_fails_when_token_budget_total_is_negative(self) -> None:
        """Negative token_budget_total raises ValueError."""
        from datetime import datetime, timezone

        with pytest.raises(ValueError, match="token_budget_total"):
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test",
                step=1,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=100,
                token_budget_total=-1,
                payload={"data": "x"},
                manifest_hash="",
                signature="",
            )

    def test_constructor_fails_when_step_is_negative(self) -> None:
        """Negative step raises ValueError."""
        from datetime import datetime, timezone

        with pytest.raises(ValueError, match="step"):
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test",
                step=-1,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=100,
                token_budget_total=8000,
                payload={"data": "x"},
                manifest_hash="",
                signature="",
            )

    def test_constructor_fails_when_step_exceeds_maximum(self) -> None:
        """Step number above _MAX_STEP raises ValueError (Issue #7)."""
        from datetime import datetime, timezone

        # We expect _MAX_STEP to be 10^6
        max_step = 10**6
        with pytest.raises(ValueError, match=f"step exceeds maximum {max_step}"):
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test",
                step=max_step + 1,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=100,
                token_budget_total=8000,
                payload={"data": "x"},
                manifest_hash="",
                signature="",
            )

    def test_constructor_fails_when_step_is_zero(self) -> None:
        """Step == 0 raises ValueError."""
        from datetime import datetime, timezone

        with pytest.raises(ValueError, match="step"):
            ContextEnvelope(
                relay_version=RELAY_VERSION,
                pipeline_id="test",
                step=0,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                token_budget_used=0,
                token_budget_total=8000,
                payload={"data": "x"},
                manifest_hash="",
                signature="",
            )

