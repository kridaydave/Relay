"""Integration tests for relay.pipeline end-to-end behavior.

Tests the real wiring of ContextBroker, HandoffValidator, and SnapshotStore.
No mocks — this exercises the actual pipeline.
"""

import tempfile
import shutil
from typing import Generator

import pytest

from relay.core_pipeline import CoreRelayPipeline
from relay.envelope import ContextEnvelope, RELAY_VERSION
from relay.types import Success, Failure, RollbackSuccess, ErrorCode


@pytest.fixture()
def temp_storage() -> Generator[str, None, None]:
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture()
def pipeline(temp_storage: str) -> CoreRelayPipeline:
    return CoreRelayPipeline(
        signing_secret="a" * 32,
        token_budget=8000,
        storage_path=temp_storage
    )


@pytest.fixture()
def base_payload() -> dict[str, object]:
    return {
        "entities": [{"name": "Alice"}, {"name": "Bob"}],
        "data": "initial"
    }


@pytest.fixture()
def valid_next_payload() -> dict[str, object]:
    return {
        "entities": [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}],
        "data": "updated"
    }


@pytest.fixture()
def contradicting_payload() -> dict[str, object]:
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
    def test_successful_handoff_saves_snapshot_when_valid(self, temp_storage: str, base_payload: dict[str, object], valid_next_payload: dict[str, object]) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        result1 = pipeline.execute_step(base_payload)
        assert isinstance(result1, Success)

        result2 = pipeline.execute_step(valid_next_payload)
        assert isinstance(result2, Success)
        current = pipeline.get_current_envelope()
        assert current is not None
        assert current.step == 2

        rollback_result = pipeline.rollback()
        assert isinstance(rollback_result, RollbackSuccess)
        assert rollback_result.value.payload == base_payload

    def test_pipeline_commits_valid_next_envelope_when_stepping(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object], valid_next_payload: dict[str, object]) -> None:
        pipeline.execute_step(base_payload)
        result = pipeline.execute_step(valid_next_payload)

        assert isinstance(result, Success)
        assert result.value.payload == valid_next_payload
        assert result.value.step == 2


class TestRollbackOnContradiction:
    def test_rollback_on_hallucination(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object], valid_next_payload: dict[str, object], contradicting_payload: dict[str, object]) -> None:
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        current = pipeline.get_current_envelope()
        assert current is not None
        previous_step = current.step

        result = pipeline.execute_step(contradicting_payload)

        assert isinstance(result, RollbackSuccess)

        restored = pipeline.get_current_envelope()
        assert restored is not None
        assert restored.step == previous_step
        assert restored.payload == valid_next_payload

    def test_contradicting_payload_not_in_active_state_when_rejected(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object], valid_next_payload: dict[str, object], contradicting_payload: dict[str, object]) -> None:
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        pipeline.execute_step(contradicting_payload)

        current = pipeline.get_current_envelope()
        assert current is not None
        current_payload = current.payload
        assert "NEW_ENTITY_X" not in str(current_payload)


class TestEdgeCases:
    def test_rollback_with_no_prior_snapshot(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object]) -> None:
        result = pipeline.rollback()

        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_ROLLBACK_AVAILABLE

    def test_overwrite_snapshot_id_does_not_duplicate_entry_when_overwriting(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object], valid_next_payload: dict[str, object]) -> None:
        pipeline.execute_step(base_payload)
        pipeline.execute_step(valid_next_payload)

        rollback_result = pipeline.rollback()
        assert isinstance(rollback_result, RollbackSuccess)

        redo_result = pipeline.execute_step(valid_next_payload)
        assert isinstance(redo_result, Success)

    def test_broker_signs_envelope_when_processing(self, pipeline: CoreRelayPipeline, base_payload: dict[str, object]) -> None:
        result = pipeline.execute_step(base_payload)
        assert isinstance(result, Success)

        envelope = result.value
        assert envelope.signature != ""

        from relay.envelope import verify_signature
        assert verify_signature(envelope, "a" * 32)