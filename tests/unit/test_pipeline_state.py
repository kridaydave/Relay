"""Unit tests for relay.pipeline_state."""

import threading
from datetime import datetime, timezone

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.pipeline_state import PipelineState
from relay.types import JSONDict


def create_mock_envelope(
    step: int, pipeline_id: str = "test-pipeline"
) -> ContextEnvelope:
    payload: JSONDict = {"step": step}
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload=payload,
        manifest_hash="",
        signature=f"sig{step}",
    )


@pytest.fixture
def state() -> PipelineState:
    return PipelineState(pipeline_id="test-pipeline-id")


class TestInitialization:
    def test_pipeline_id_is_correctly_set_on_init(self, state: PipelineState) -> None:
        assert state.pipeline_id == "test-pipeline-id"

    def test_initial_current_envelope_returns_none(self, state: PipelineState) -> None:
        with state.transaction() as _:
            assert state.current() is None

    def test_initial_state_has_no_history(self, state: PipelineState) -> None:
        with state.transaction() as _:
            assert state.has_history() is False


class TestSetCurrent:
    def test_sets_current_envelope(self, state: PipelineState) -> None:
        env = create_mock_envelope(1)
        with state.transaction() as _:
            state.set_current(env)
            assert state.current() == env


class TestArchiveAndSet:
    def test_archives_current_and_sets_new(self, state: PipelineState) -> None:
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        with state.transaction() as _:
            state.set_current(env1)

        with state.transaction() as _:
            state.archive_and_set(env2)
            assert state.current() == env2
            history = state.get_previous_envelopes()
            assert len(history) == 1
            assert history[0] == env1

    def test_first_envelope_has_no_archive_after_set(self, state: PipelineState) -> None:
        env1 = create_mock_envelope(1)
        with state.transaction() as _:
            state.archive_and_set(env1)
            assert state.current() == env1
            assert state.has_history() is False


class TestSnapshotIds:
    def test_snapshot_ids_dict_is_empty_initially(self, state: PipelineState) -> None:
        with state.transaction():
            assert state.snapshot_ids == {}


class TestGetPreviousEnvelopes:
    def test_returns_copy_of_previous_envelopes(self, state: PipelineState) -> None:
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        with state.transaction() as _:
            state.archive_and_set(env1)
        with state.transaction() as _:
            state.archive_and_set(env2)
        with state.transaction() as _:
            history = state.get_previous_envelopes()
            assert len(history) == 1
            assert history[0] == env1
            history.clear()
            assert len(state.get_previous_envelopes()) == 1

    def test_returns_empty_list_when_no_history(self, state: PipelineState) -> None:
        with state.transaction() as _:
            assert state.get_previous_envelopes() == []


class TestConsumeLast:
    def test_removes_and_returns_last_envelope(self, state: PipelineState) -> None:
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        with state.transaction() as _:
            state.archive_and_set(env1)
        with state.transaction() as _:
            state.archive_and_set(env2)
        with state.transaction() as _:
            consumed = state.consume_last()
        assert consumed == env1
        with state.transaction() as _:
            history = state.get_previous_envelopes()
            assert len(history) == 0

    def test_raises_index_error_when_history_empty(self, state: PipelineState) -> None:
        with state.transaction() as _:
            with pytest.raises(IndexError):
                state.consume_last()


class TestThreadSafety:
    def test_transaction_lock_is_acquirable_when_called(self, state: PipelineState) -> None:
        with state.transaction() as _:
            pass

    def test_lock_prevents_concurrent_modification_when_held(self, state: PipelineState) -> None:
        env1 = create_mock_envelope(1)
        env2 = create_mock_envelope(2)
        errors: list[Exception] = []

        def set_current() -> None:
            try:
                with state.transaction():
                    state.set_current(env1)
            except Exception as e:
                errors.append(e)

        def archive_and_set() -> None:
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
        with state.transaction() as _:
            final = state.current()
        assert final is not None
        assert final.step in (1, 2)


class TestLockAssertions:
    def test_set_current_outside_transaction_raises_runtime_error(self, state: PipelineState) -> None:
        env = create_mock_envelope(1)
        with pytest.raises(RuntimeError, match="Lock must be held via transaction"):
            state.set_current(env)

    def test_transaction_raises_on_reentrant_call(self, state: PipelineState) -> None:
        """Re-entrant call to transaction() should raise RuntimeError (Issue #4)."""
        with state.transaction():
            with pytest.raises(RuntimeError, match="Re-entrant lock access detected"):
                with state.transaction():
                    pass
