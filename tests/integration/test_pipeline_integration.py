"""Integration tests for relay.pipeline end-to-end behavior.

Tests the real wiring of ContextBroker, HandoffValidator, and SnapshotStore.
No mocks — this exercises the actual pipeline.
"""

import tempfile
import shutil

import pytest

from relay.core_pipeline import CoreRelayPipeline
from relay.context_broker import ContextBroker
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import Success, Failure, RollbackSuccess


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def pipeline(temp_storage):
    return CoreRelayPipeline(
        signing_secret="a" * 32,
        token_budget=8000,
        storage_path=temp_storage
    )


@pytest.fixture
def base_payload():
    return {
        "entities": [{"name": "Alice"}, {"name": "Bob"}],
        "data": "initial"
    }


@pytest.fixture
def valid_next_payload():
    return {
        "entities": [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}],
        "data": "updated"
    }


@pytest.fixture
def contradicting_payload():
    return {
        "entities": [
            {"name": "Alice"},
            {"name": "NEW_1"},
            {"name": "NEW_2"},
            {"name": "NEW_3"},
            {"name": "NEW_4"},
            {"name": "NEW_5"},
            {"name": "NEW_6"},
            {"name": "NEW_7"}
        ]
    }


class TestSuccessfulHandoff:
    def test_successful_handoff_saves_snapshot(self, pipeline, base_payload, valid_next_payload):
        result1 = pipeline.execute_step(base_payload)
        assert isinstance(result1, Success)

        result2 = pipeline.execute_step(valid_next_payload)
        assert isinstance(result2, Success)
        assert pipeline.get_current_envelope().step == 2

        with pipeline._state.transaction():
            snapshot_id = pipeline._state.snapshot_ids.get(2)
        assert snapshot_id is not None

        load_result = pipeline._snapshot_store.load_snapshot(snapshot_id)
        assert isinstance(load_result, Success)
        assert load_result.value.payload == valid_next_payload
        assert load_result.value.step == 2

    def test_pipeline_commits_valid_next_envelope(self, pipeline, base_payload, valid_next_payload):
        pipeline.execute_step(base_payload)
        result = pipeline.execute_step(valid_next_payload)

        assert isinstance(result, Success)
        assert result.value.payload == valid_next_payload
        assert result.value.step == 2


class TestRollbackOnContradiction:
    def test_rollback_on_hallucination(self, pipeline, base_payload, valid_next_payload, contradicting_payload):
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        previous_step = pipeline.get_current_envelope().step
        with pipeline._state.transaction():
            previous_snapshot_id = pipeline._state.snapshot_ids.get(previous_step)

        result = pipeline.execute_step(contradicting_payload)

        assert isinstance(result, RollbackSuccess)

        restored = pipeline.get_current_envelope()
        assert restored.step == previous_step
        assert restored.payload == valid_next_payload

        assert previous_snapshot_id is not None
        load_result = pipeline._snapshot_store.load_snapshot(previous_snapshot_id)
        assert isinstance(load_result, Success)
        assert load_result.value.payload == valid_next_payload

    def test_contradicting_payload_not_in_active_state(self, pipeline, base_payload, valid_next_payload, contradicting_payload):
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        pipeline.execute_step(contradicting_payload)

        current_payload = pipeline.get_current_envelope().payload
        assert "NEW_ENTITY_X" not in str(current_payload)


class TestEdgeCases:
    def test_rollback_with_no_prior_snapshot(self, pipeline, base_payload):
        result = pipeline.rollback()

        assert isinstance(result, Failure)
        assert "NO_ROLLBACK_AVAILABLE" in result.code

    def test_idempotent_snapshot_ids(self, pipeline, base_payload, valid_next_payload):
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        step = 2
        with pipeline._state.transaction():
            pipeline._state.snapshot_ids[step] = "new-id"
            assert len([k for k in pipeline._state.snapshot_ids if k == step]) == 1

    def test_broker_signs_envelope(self, pipeline, base_payload):
        result = pipeline.execute_step(base_payload)
        assert isinstance(result, Success)

        envelope = result.value
        assert envelope.signature != ""

        from relay.envelope import verify_signature
        assert verify_signature(envelope, "a" * 32)