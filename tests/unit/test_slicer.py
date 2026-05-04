import pytest
from relay.slicer import SlicePackager, ContextSlice, create_slice_from_envelope
from relay.envelope import ContextEnvelope, create_initial_envelope
from relay.types import Success, Failure


@pytest.fixture
def sample_payload():
    return {
        "task": "analyze data",
        "results": {"accuracy": 0.95, "metrics": [1, 2, 3, 4, 5]},
        "logs": "Starting analysis...\nProcessing...\nComplete.",
    }


@pytest.fixture
def envelope(sample_payload):
    result = create_initial_envelope("test-pipeline-123", sample_payload)
    assert isinstance(result, Success)
    return result.value


class TestSlicePackager:
    def test_slicer_creates_slice_with_valid_envelope(self, envelope):
        packager = SlicePackager(default_max_tokens=4000)
        result = packager.create_slice(envelope, "agent-1")

        assert isinstance(result, Success)
        slice_obj = result.value
        assert isinstance(slice_obj, ContextSlice)
        assert "test-pipeline-123" in slice_obj.slice_id
        assert slice_obj.step == envelope.step

    def test_slicer_respects_max_tokens_limit(self, envelope):
        packager = SlicePackager(default_max_tokens=4000)
        result = packager.create_slice(envelope, "agent-1", max_tokens=100)

        assert isinstance(result, Success)
        assert result.value.truncated_at == 100

    def test_slicer_uses_registered_agent_keys_when_available(self, sample_payload):
        envelope_result = create_initial_envelope("test-pipeline-456", sample_payload)
        assert isinstance(envelope_result, Success)
        envelope = envelope_result.value

        packager = SlicePackager(default_max_tokens=4000)
        packager.register_agent_keys("agent-2", ["task", "results"])

        result = packager.create_slice(envelope, "agent-2")

        assert isinstance(result, Success)
        assert set(result.value.relevant_keys) == {"task", "results"}

    def test_slicer_falls_back_to_all_keys_when_not_registered(self, sample_payload):
        envelope_result = create_initial_envelope("test-pipeline-789", sample_payload)
        assert isinstance(envelope_result, Success)
        envelope = envelope_result.value

        packager = SlicePackager(default_max_tokens=4000)

        result = packager.create_slice(envelope, "unknown-agent")

        assert isinstance(result, Success)
        assert set(result.value.relevant_keys) == set(sample_payload.keys())

    def test_slicer_truncates_values_to_fit_budget(self):
        large_payload = {
            "large_data": "x" * 10000,
            "small_data": "y",
        }
        envelope_result = create_initial_envelope("test-pipeline-trunc", large_payload)
        assert isinstance(envelope_result, Success)
        envelope = envelope_result.value

        packager = SlicePackager(default_max_tokens=50)
        result = packager.create_slice(envelope, "agent-1")

        assert isinstance(result, Success)
        result_payload = result.value.payload
        if "large_data" in result_payload:
            assert len(result_payload["large_data"]) <= 200

    def test_context_slice_has_all_required_fields(self, envelope):
        packager = SlicePackager(default_max_tokens=4000)
        result = packager.create_slice(envelope, "agent-1")

        assert isinstance(result, Success)
        slice_obj = result.value
        assert hasattr(slice_obj, "slice_id")
        assert hasattr(slice_obj, "step")
        assert hasattr(slice_obj, "relevant_keys")
        assert hasattr(slice_obj, "truncated_at")
        assert hasattr(slice_obj, "payload")
        assert isinstance(slice_obj.slice_id, str)
        assert isinstance(slice_obj.step, int)
        assert isinstance(slice_obj.relevant_keys, list)
        assert isinstance(slice_obj.truncated_at, int)
        assert isinstance(slice_obj.payload, dict)


class TestCreateSliceFromEnvelope:
    def test_create_slice_from_envelope_convenience_function(self, sample_payload):
        envelope_result = create_initial_envelope("test-pipeline-conv", sample_payload)
        assert isinstance(envelope_result, Success)
        envelope = envelope_result.value

        result = create_slice_from_envelope(envelope, "agent-1", max_tokens=2000)

        assert isinstance(result, Success)
        assert isinstance(result.value, ContextSlice)
        assert result.value.truncated_at == 2000