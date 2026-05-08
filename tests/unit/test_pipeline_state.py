"""Unit tests for relay.pipeline_state."""

import threading
from datetime import datetime, timezone

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.pipeline_state import PipelineState


def create_mock_envelope(step: int, pipeline_id: str = "test-pipeline") -> ContextEnvelope:
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload={"step": step},
        manifest_hash="",
        signature=f"sig{step}",
    )


@pytest.fixture
def state():
    return PipelineState(pipeline_id="test-pipeline-id")


class TestInitialization:
    def test_pipeline_id_is_set(self, state):
        assert state.pipeline_id == "test-pipeline-id"

    def test_initial_current_is_none(self, state):
        assert state.current() is None

    def test_initial_has_no_history(self, state):
        assert state.has_history() is False


class TestSetCurrent:
    def test_sets_current_envelope(self, state):
        env = create_mock_envelope(1)
        state.set_current(env)
        assert state.current() == env


class TestArchiveAndSet:
    def test_archives_current_and_sets_new(self, state):
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        state.set_current(env1)

        state.archive_and_set(env2)

        assert state.current() == env2
        history = state.get_previous_envelopes()
        assert len(history) == 1
        assert history[0] == env1

    def test_first_envelope_has_no_archive(self, state):
        env1 = create_mock_envelope(1)
        state.archive_and_set(env1)
        assert state.current() == env1
        assert state.has_history() is False


class TestRollbackToLast:
    def test_pops_last_envelope_from_history(self, state):
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        state.set_current(env1)
        state.archive_and_set(env2)

        previous, history = state.rollback_to_last()

        assert previous == env1
        assert len(history) == 0

    def test_has_history_reflects_state(self, state):
        assert state.has_history() is False
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        state.set_current(env1)
        state.archive_and_set(env2)
        assert state.has_history() is True
        state.rollback_to_last()
        assert state.has_history() is False


class TestLastEnvelope:
    def test_returns_none_when_no_history(self, state):
        assert state.last_envelope() is None

    def test_returns_last_envelope_in_history(self, state):
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        env3 = create_mock_envelope(3)
        state.set_current(env1)
        state.archive_and_set(env2)
        state.archive_and_set(env3)

        assert state.last_envelope() == env2


class TestSnapshotIds:
    def test_snapshot_ids_is_empty_initially(self, state):
        assert state.snapshot_ids == {}


class TestThreadSafety:
    def test_lock_is_acquirable(self, state):
        with state.transaction() as _:
            pass

    def test_lock_prevents_concurrent_modification(self, state):
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        errors = []

        def set_current():
            try:
                with state.transaction():
                    state.set_current(env1)
            except Exception as e:
                errors.append(e)

        def archive_and_set():
            try:
                with state.transaction():
                    state.archive_and_set(env2)
            except Exception as e:
                errors.append(e)

        def archive_and_set():
            try:
                with state.transaction():
                    state.archive_and_set(env2)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=set_current)
        t2 = threading.Thread(target=archive_and_set)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0
