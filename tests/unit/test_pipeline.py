"""Unit tests for relay.pipeline."""

import asyncio
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Generator, cast, List, Union, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.core_pipeline import CoreRelayPipeline
from relay.parallel import agent_output_to_payload
from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer import AgentManifest
from relay.types import ErrorCode, Failure, Success, RollbackSuccess, JSONDict, Result


@pytest.fixture
def temp_storage() -> Generator[str, None, None]:
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def pipeline(temp_storage: str) -> CoreRelayPipeline:
    return CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
    )


def create_mock_envelope(
    step: int, pipeline_id: str, payload: JSONDict, timestamp: datetime | None = None
) -> ContextEnvelope:
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return ContextEnvelope(
        relay_version=RELAY_VERSION,
        pipeline_id=pipeline_id,
        step=step,
        timestamp=timestamp,
        token_budget_used=100 * step,
        token_budget_total=8000,
        payload=payload,
        manifest_hash="",
        signature=f"sig{step}",
    )


class TestPipelineCreatesEnvelope:
    def test_pipeline_creates_envelope_on_first_step(self, pipeline: CoreRelayPipeline) -> None:
        result = pipeline.execute_step({"data": "test-payload"})

        assert isinstance(result, Success)
        assert result.value.step == 1
        assert result.value.pipeline_id == pipeline._pipeline_id
        assert result.value.payload == {"data": "test-payload"}


class TestPipelineCreatesNextEnvelope:
    def test_pipeline_creates_next_envelope_on_subsequent_step(self, pipeline: CoreRelayPipeline) -> None:
        pipeline.execute_step({"initial": "data"})
        result = pipeline.execute_step({"next": "data"})

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.payload == {"next": "data"}


class TestPipelineValidationAndSnapshot:
    def test_pipeline_validates_and_saves_snapshot_on_clean_handoff(self, pipeline: CoreRelayPipeline) -> None:
        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step(
            {"entities": ["entity1", "entity2"], "data": "next"}
        )

        assert isinstance(result, Success)
        assert result.value.step == 2


class TestPipelineRollback:
    def test_pipeline_triggers_rollback_on_contradiction(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step({"data": "next"})

        assert isinstance(result, RollbackSuccess)
        assert result.value.step == 1


class TestPipelineRollback2:
    def test_pipeline_rollback_restores_previous_envelope_when_called(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        pipeline.execute_step({"data": "next"})
        result = pipeline.rollback()

        assert isinstance(result, RollbackSuccess)
        assert result.value.step == 1
        assert result.value.payload == {"entities": ["entity1"], "data": "initial"}


class TestPipelineGetCurrentEnvelope:
    def test_pipeline_get_current_envelope_returns_none_initially(self, pipeline: CoreRelayPipeline) -> None:
        result = pipeline.get_current_envelope()
        assert result is None

    def test_pipeline_get_current_envelope_returns_current_after_step(self, pipeline: CoreRelayPipeline) -> None:
        pipeline.execute_step({"data": "test"})
        result = pipeline.get_current_envelope()

        assert result is not None
        assert result.step == 1
        assert result.payload == {"data": "test"}


class TestConcurrentPipeline:
    """R18: Concurrent code must be tested concurrently."""

    def test_concurrent_step_execution_produces_consistent_results_when_run_in_parallel(
        self, temp_storage: str
    ) -> None:
        """Test that concurrent step execution produces consistent results."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:
            
            initial_payload: JSONDict = {"initial": "data"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", initial_payload)
            )
            def mock_create_next_envelope_side_effect(
                previous_envelope: ContextEnvelope, agent_output: JSONDict, manifest_hash: str
            ) -> Success[ContextEnvelope]:
                return Success[ContextEnvelope](
                    create_mock_envelope(
                        previous_envelope.step + 1,
                        previous_envelope.pipeline_id,
                        agent_output,
                    )
                )
            mock_next.side_effect = mock_create_next_envelope_side_effect

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )

            results: List[Result[ContextEnvelope]] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def execute_step(step_num: int) -> None:
                try:
                    payload: JSONDict = {"step": step_num, "data": f"data-{step_num}"}
                    result = pipeline.execute_step(payload)
                    with lock:
                        results.append(result)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [threading.Thread(target=execute_step, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert len(results) > 0
            final_envelope = pipeline.get_current_envelope()
            assert final_envelope is not None
            assert final_envelope.step >= 1

            submitted_payloads: List[JSONDict] = [{"step": i, "data": f"data-{i}"} for i in range(3)]
            assert final_envelope.payload in submitted_payloads, (
                f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
                "possible state corruption from concurrent writes"
            )

    def test_concurrent_step_execution_with_snapshot_tracking(
        self, temp_storage: str
    ) -> None:
        """Test that concurrent access to _snapshot_ids is thread-safe."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:

            def mock_create_next_envelope(
                previous_envelope: ContextEnvelope, agent_output: JSONDict, manifest_hash: str
            ) -> Success[ContextEnvelope]:
                return Success[ContextEnvelope](
                    create_mock_envelope(
                        previous_envelope.step + 1,
                        previous_envelope.pipeline_id,
                        agent_output,
                    )
                )
            mock_next.side_effect = mock_create_next_envelope

            initial_payload: JSONDict = {"initial": "data"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", initial_payload)
            )

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )

            results: List[Result[ContextEnvelope]] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def execute_and_advance(step_num: int) -> None:
                try:
                    payload: JSONDict = {"step": step_num}
                    result = pipeline.execute_step(payload)
                    with lock:
                        results.append(result)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [
                threading.Thread(target=execute_and_advance, args=(i,))
                for i in range(3)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert len(results) > 0

            final_envelope = pipeline.get_current_envelope()
            assert final_envelope is not None
            assert final_envelope.step >= 1

            submitted_payloads: List[JSONDict] = [{"step": i} for i in range(3)]
            submitted_payloads.append(initial_payload)
            assert final_envelope.payload in submitted_payloads, (
                f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
                "possible state corruption from concurrent writes"
            )

    def test_concurrent_get_current_envelope_when_called_by_multiple_threads(
        self, temp_storage: str
    ) -> None:
        """Test that concurrent reads of _current_envelope are safe."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:

            payload1: JSONDict = {"initial": "data"}
            payload2: JSONDict = {"next": "data"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", payload1)
            )
            mock_next.return_value = Success[ContextEnvelope](
                create_mock_envelope(2, "test-pipeline-id", payload2)
            )

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )

            pipeline.execute_step(payload1)
            pipeline.execute_step(payload2)

            results: List[ContextEnvelope | None] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def get_envelope() -> None:
                try:
                    envelope = pipeline.get_current_envelope()
                    with lock:
                        results.append(envelope)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [threading.Thread(target=get_envelope) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert all(r is not None for r in results), "All results should be non-None"

    def test_concurrent_reads_and_writes_are_safe_when_interleaved(
        self, temp_storage: str
    ) -> None:
        """Concurrent step writes interleaved with reads don't corrupt state."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:

            payload1: JSONDict = {"initial": "data"}
            payload2: JSONDict = {"next": "data"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", payload1)
            )
            mock_next.return_value = Success[ContextEnvelope](
                create_mock_envelope(2, "test-pipeline-id", payload2)
            )

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )
            pipeline.execute_step(payload1)

            results: List[ContextEnvelope | None] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def mixed_access(i: int) -> None:
                try:
                    if i % 2 == 0:
                        payload: JSONDict = {"step": i}
                        pipeline.execute_step(payload)
                    envelope = pipeline.get_current_envelope()
                    with lock:
                        results.append(envelope)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [threading.Thread(target=mixed_access, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert all(r is not None for r in results), "All results should be non-None"

    def test_concurrent_rollback_access_when_requested_simultaneously(
        self, temp_storage: str
    ) -> None:
        """Test that concurrent rollback access is handled safely."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next, \
             patch("relay.core_pipeline.SnapshotStore") as mock_store_cls:

            mock_store = MagicMock()
            mock_store.save_snapshot.return_value = Success[str]("snapshot-id")
            mock_store.load_snapshot.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", {"data": "restored"})
            )
            mock_store_cls.return_value = mock_store

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )

            payload1: JSONDict = {"data": "initial"}
            payload2: JSONDict = {"data": "next"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, pipeline._pipeline_id, payload1)
            )
            mock_next.return_value = Success[ContextEnvelope](
                create_mock_envelope(2, pipeline._pipeline_id, payload2)
            )

            pipeline.execute_step(payload1)
            pipeline.execute_step(payload2)

            results: List[Result[ContextEnvelope]] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def attempt_rollback() -> None:
                try:
                    result = pipeline.rollback()
                    with lock:
                        results.append(result)
                except Exception as e:
                    with lock:
                        errors.append(e)

            threads = [threading.Thread(target=attempt_rollback) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(results) > 0, "At least one rollback attempt should have completed"
            assert all(isinstance(r, (Failure, Success, RollbackSuccess)) for r in results)

            final_envelope = pipeline.current_envelope
            previous_envelopes = pipeline.history
            snapshot_ids = pipeline.snapshot_index

            if final_envelope is not None:
                current_step = final_envelope.step
                if current_step > 1:
                    assert len(previous_envelopes) > 0 or snapshot_ids.get(current_step) is not None, (
                        f"R18 invariant violated: step {current_step} has no snapshot and no previous envelopes. "
                        f"Previous envelopes: {len(previous_envelopes)}, Snapshots: {snapshot_ids}"
                    )

    def test_thread_pool_executor_operations_succeed_when_run_concurrently(
        self, temp_storage: str
    ) -> None:
        """Test pipeline operations under thread pool execution."""
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial, \
             patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:

            def mock_create_next_envelope(
                previous_envelope: ContextEnvelope, agent_output: JSONDict, manifest_hash: str
            ) -> Success[ContextEnvelope]:
                return Success[ContextEnvelope](
                    create_mock_envelope(
                        previous_envelope.step + 1,
                        previous_envelope.pipeline_id,
                        agent_output,
                    )
                )
            mock_next.side_effect = mock_create_next_envelope

            payload1: JSONDict = {"data": "test"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "test-pipeline-id", payload1)
            )

            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
            )

            results: List[Result[ContextEnvelope]] = []
            errors: List[Exception] = []
            lock = threading.Lock()

            def execute_step_task(step_num: int) -> None:
                try:
                    payload: JSONDict = {"step": step_num}
                    result = pipeline.execute_step(payload)
                    with lock:
                        results.append(result)
                except Exception as e:
                    with lock:
                        errors.append(e)

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(execute_step_task, i) for i in range(5)]
                for f in futures:
                    f.result()

            assert len(errors) == 0, f"Errors occurred: {errors}"
            final_envelope = pipeline.get_current_envelope()
            assert final_envelope is not None

            # Fix incompatible types in assignment
            submitted_payloads: List[JSONDict] = [{"step": i} for i in range(5)]
            submitted_payloads.append(payload1)
            assert final_envelope.payload in submitted_payloads, (
                f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
                "possible state corruption from concurrent writes"
            )



class TestAgentOutputToPayload:
    def test_includes_tool_calls_when_present(self) -> None:
        output = AgentOutput(
            text="hello", structured={"key": "val"}, tool_calls=[{"name": "call1"}],
            token_count=10, latency_ms=5, adapter="test",
        )
        result = agent_output_to_payload(output)
        assert result["text"] == "hello"
        assert result["key"] == "val"
        assert result["tool_calls"] == [{"name": "call1"}]

    def test_no_tool_calls_when_empty(self) -> None:
        output = AgentOutput(
            text="hello", structured={}, tool_calls=[],
            token_count=10, latency_ms=5, adapter="test",
        )
        result = agent_output_to_payload(output)
        assert result["text"] == "hello"
        assert "tool_calls" not in result


class TestPipelineConstruction:
    def test_fails_on_short_signing_secret(self) -> None:
        with pytest.raises(ValueError, match="signing_secret"):
            CoreRelayPipeline(signing_secret="short")


class TestPipelineContextManager:
    def test_context_manager_enter_returns_pipeline(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        with pipeline as p:
            assert p is pipeline

    def test_context_manager_exit_succeeds_and_does_not_raise(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        pipeline.__enter__()
        pipeline.__exit__(None, None, None)


class TestPipelineClose:
    def test_close_with_token_counter(self, temp_storage: str) -> None:
        counter = MagicMock()
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, token_counter=counter,
        )
        pipeline.close()
        counter.close.assert_called_once()

    def test_close_without_token_counter_succeeds_and_does_not_raise(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        pipeline.close()


class TestPipelineInitialStepErrors:
    def test_budget_failure_in_initial_step_returns_error(self, temp_storage: str) -> None:
        with patch("relay.core_pipeline.HardCapEnforcer") as mock_enforcer_cls:
            counter = MagicMock()
            enforcer = MagicMock()
            enforcer.check.return_value = Failure(
                reason="Budget exceeded", code=ErrorCode.BUDGET_EXCEEDED,
            )
            mock_enforcer_cls.return_value = enforcer

            manifest = AgentManifest(
                "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=100,
            )
            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=100,
                storage_path=temp_storage, token_counter=counter,
            )
            payload: JSONDict = {"y": "data"}
            result = pipeline.execute_step_with_manifest(
                payload, manifest=manifest,
            )
            assert isinstance(result, Failure)
            assert result.code == ErrorCode.BUDGET_EXCEEDED

    def test_create_initial_envelope_fails_on_failure(self, pipeline: CoreRelayPipeline) -> None:
        payload: JSONDict = {"data": "test"}
        with patch(
            "relay.context_broker.ContextBroker.create_initial_envelope",
            return_value=Failure(reason="fail", code=ErrorCode.INVALID_PAYLOAD),
        ):
            result = pipeline.execute_step(payload)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PAYLOAD


class TestPipelineSubsequentStepErrors:
    def test_create_next_envelope_fails_on_failure(self, pipeline: CoreRelayPipeline) -> None:
        with patch("relay.context_broker.ContextBroker.create_next_envelope") as mock_next:
            payload1: JSONDict = {"data": "first"}
            result = pipeline.execute_step(payload1)
            assert isinstance(result, Success)

            mock_next.return_value = Failure(
                reason="fail", code=ErrorCode.INVALID_PAYLOAD,
            )
            payload2: JSONDict = {"data": "second"}
            result = pipeline.execute_step(payload2)
            assert isinstance(result, Failure)
            assert result.code == ErrorCode.INVALID_PAYLOAD


class TestPipelineBudgetEnforcement:
    def test_check_budget_passes_with_valid_projection(self, temp_storage: str) -> None:
        """_check_budget must succeed with a reasonable budget."""
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=100,
        )
        payload: JSONDict = {"y": "data"}
        result = pipeline.execute_step_with_manifest(
            payload, manifest=manifest,
        )
        assert isinstance(result, Success)

    def test_manifest_boundary_violation_returns_failure(self, pipeline: CoreRelayPipeline) -> None:
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}),
            writes=frozenset({"permitted"}),
            max_tokens=100,
        )
        payload: JSONDict = {"permitted": "ok", "forbidden": "bad"}
        result = pipeline.execute_step_with_manifest(
            payload,
            manifest=manifest,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.MANIFEST_BOUNDARY_VIOLATION

    def test_budget_failure_in_subsequent_step_returns_error(self, temp_storage: str) -> None:
        with patch("relay.core_pipeline.HardCapEnforcer") as mock_enforcer_cls:
            counter = MagicMock()
            counter.count.return_value = 10
            enforcer = MagicMock()
            enforcer.check.side_effect = [
                Success[None](None),
                Failure(reason="Budget exceeded", code=ErrorCode.BUDGET_EXCEEDED),
            ]
            enforcer.counter = counter
            mock_enforcer_cls.return_value = enforcer

            manifest = AgentManifest(
                "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=100,
            )
            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=100,
                storage_path=temp_storage, token_counter=counter,
            )
            payload1: JSONDict = {"y": "data"}
            result = pipeline.execute_step_with_manifest(
                payload1, manifest=manifest,
            )
            assert isinstance(result, Success)

            payload2: JSONDict = {"y": "more"}
            result = pipeline.execute_step_with_manifest(
                payload2, manifest=manifest,
            )
            assert isinstance(result, Failure)
            assert result.code == ErrorCode.BUDGET_EXCEEDED

    def test_per_agent_max_tokens_exceeded_fails_validation(self, temp_storage: str) -> None:
        with patch("relay.core_pipeline.HardCapEnforcer") as mock_enforcer_cls:
            counter = MagicMock()
            counter.count.return_value = 9999
            enforcer = MagicMock()
            enforcer.check.return_value = Success[None](None)
            enforcer.counter = counter
            mock_enforcer_cls.return_value = enforcer

            manifest = AgentManifest(
                "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=10,
            )
            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=100,
                storage_path=temp_storage, token_counter=counter,
            )
            payload: JSONDict = {"y": "data"}
            result = pipeline.execute_step_with_manifest(
                payload, manifest=manifest,
            )
            assert isinstance(result, Failure)
            assert result.code == ErrorCode.TOKEN_BUDGET_EXCEEDED
            assert "manifest.max_tokens" in result.reason


class TestPipelineApplyManifest:
    def test_apply_manifest_adds_hash_and_signature_when_successful(self, temp_storage: str) -> None:
        with patch("relay.context_broker.ContextBroker.create_initial_envelope") as mock_initial:
            payload: JSONDict = {"y": "data"}
            mock_initial.return_value = Success[ContextEnvelope](
                create_mock_envelope(1, "pipe-id", payload),
            )
            manifest = AgentManifest(
                "a1", "task",
                reads=frozenset({"x"}), writes=frozenset({"y"}), max_tokens=100,
            )
            pipeline = CoreRelayPipeline(
                signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
            )
            result = pipeline.execute_step_with_manifest(
                payload, manifest=manifest,
            )
            assert isinstance(result, Success)
            assert result.value.manifest_hash == manifest.compute_hash()
            assert result.value.signature != ""


class TestPipelineRollbackEdgeCases:
    def test_rollback_fails_when_no_history(self, pipeline: CoreRelayPipeline) -> None:
        """Rolling back an initial pipeline fails with NO_ROLLBACK_AVAILABLE."""
        result = pipeline.rollback()
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_ROLLBACK_AVAILABLE

    def test_do_rollback_fails_on_invariant_violation_when_state_is_corrupt(self, pipeline: CoreRelayPipeline) -> None:
        """If has_history() is True but peek_last() is None, _do_rollback fails with INVALID_STATE."""
        # Manually corrupt the state by having history but no last envelope
        # We need to mock peek_last to return None while has_history returns True
        with patch.object(pipeline._state, "has_history", return_value=True), \
             patch.object(pipeline._state, "peek_last", return_value=None):
            # We must also mock transaction to not actually do anything
            from contextlib import contextmanager
            @contextmanager
            def mock_transaction() -> Generator[ContextEnvelope | None, None, None]:
                yield None
            
            with patch.object(pipeline._state, "transaction", side_effect=mock_transaction):
                result = pipeline.rollback()
                assert isinstance(result, Failure)
                assert result.code == ErrorCode.INVALID_STATE


class TestPipelineFinalizeStepErrors:
    def test_finalize_step_fails_when_snapshot_save_fails(self, pipeline: CoreRelayPipeline) -> None:
        """If SnapshotStore fails to save, _finalize_step returns the failure."""
        env1 = create_mock_envelope(1, pipeline._pipeline_id, {"x": 1})
        env2 = create_mock_envelope(2, pipeline._pipeline_id, {"x": 2})
        
        with patch.object(pipeline._snapshot_store, "save_snapshot", return_value=Failure(reason="disk full", code=ErrorCode.SNAPSHOT_SAVE_FAILED)):
            # Use transaction to hold the lock
            with pipeline._state.transaction():
                result = pipeline._finalize_step(env1, env2)
                assert isinstance(result, Failure)
                assert result.code == ErrorCode.SNAPSHOT_SAVE_FAILED



class TestPipelineBuildContextSlice:
    def test_build_context_slice_with_none_envelope(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}), writes=frozenset({"y"}), max_tokens=100,
        )
        slice_ = pipeline._build_context_slice(None, manifest)
        assert isinstance(slice_, ContextSlice)
        assert slice_.step == 0
        assert slice_.sections == {}

    def test_build_context_slice_filters_by_manifest_reads_when_envelope_provided(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}), writes=frozenset({"y"}), max_tokens=100,
        )
        envelope = create_mock_envelope(
            1, pipeline._pipeline_id, {"x": "keep", "z": "exclude"},
        )
        slice_ = pipeline._build_context_slice(envelope, manifest)
        assert "x" in slice_.sections
        assert "z" not in slice_.sections


class TestPipelineSlicePayload:
    def test_slice_payload_returns_empty_when_no_packer(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset(), frozenset(), max_tokens=100,
        )
        result = pipeline._slice_payload(manifest, None)
        assert isinstance(result, Success)
        assert result.value == ""

    def test_slice_payload_returns_empty_when_no_envelope(self, temp_storage: str) -> None:
        packer = MagicMock()
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, slice_packer=packer,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset(), frozenset(), max_tokens=100,
        )
        result = pipeline._slice_payload(manifest, None)
        assert isinstance(result, Success)
        assert result.value == ""


class TestPipelineExecuteStepWithRunner:
    @pytest.mark.asyncio
    async def test_fails_when_no_registry(self, temp_storage: str) -> None:
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset(), frozenset(), max_tokens=100,
        )
        result = await pipeline.execute_step_with_runner("nonexistent", manifest)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_REGISTRY

    @pytest.mark.asyncio
    async def test_fails_when_adapter_not_found(self, temp_storage: str) -> None:
        from relay.runners import AdapterRegistry
        registry = AdapterRegistry()
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, registry=registry,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset(), frozenset(), max_tokens=100,
        )
        result = await pipeline.execute_step_with_runner("unknown", manifest)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ADAPTER_NOT_FOUND

    @pytest.mark.asyncio
    async def test_fails_on_adapter_exception(self, temp_storage: str) -> None:
        from relay.runners import AdapterRegistry
        from tests.unit.test_runners.conftest import FixedAgentRunner

        registry = AdapterRegistry()
        runner = FixedAgentRunner(fail=True, fail_with=RuntimeError)
        registry.register("failing-runner", runner)

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, registry=registry,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=100,
        )
        result = await pipeline.execute_step_with_runner("failing-runner", manifest)
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.ADAPTER_EXECUTION_FAILED
        assert "FixedAgentRunner" in result.reason

    @pytest.mark.asyncio
    async def test_successful_execution_with_runner(self, temp_storage: str) -> None:
        from relay.runners import AdapterRegistry
        from tests.unit.test_runners.conftest import FixedAgentRunner

        registry = AdapterRegistry()
        runner = FixedAgentRunner(output_text="runner response")
        registry.register("good-runner", runner)

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, registry=registry,
        )
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}), writes=frozenset({"text", "y"}), max_tokens=10000,
        )
        result = await pipeline.execute_step_with_runner("good-runner", manifest)
        assert isinstance(result, Success)
        assert result.value.step == 1
        assert "runner response" in str(result.value.payload.get("text", ""))
