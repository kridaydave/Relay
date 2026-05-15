"""Unit tests for relay.pipeline."""

import asyncio
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

import pytest

from relay.envelope import RELAY_VERSION, ContextEnvelope
from relay.core_pipeline import CoreRelayPipeline
from relay.parallel import _agent_output_to_payload
from relay.runners.protocol import AgentOutput, ContextSlice
from relay.slicer import AgentManifest
from relay.types import ErrorCode, Failure, Success, RollbackSuccess


@pytest.fixture
def temp_storage():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def pipeline(temp_storage):
    return CoreRelayPipeline(
        signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
    )


def create_mock_envelope(
    step: int, pipeline_id: str, payload: dict, timestamp: datetime | None = None
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
    def test_pipeline_creates_envelope_on_first_step(self, pipeline):
        result = pipeline.execute_step({"data": "test-payload"})

        assert isinstance(result, Success)
        assert result.value.step == 1
        assert result.value.pipeline_id == pipeline._pipeline_id
        assert result.value.payload == {"data": "test-payload"}


class TestPipelineCreatesNextEnvelope:
    def test_pipeline_creates_next_envelope_on_subsequent_step(self, pipeline):
        pipeline.execute_step({"initial": "data"})
        result = pipeline.execute_step({"next": "data"})

        assert isinstance(result, Success)
        assert result.value.step == 2
        assert result.value.payload == {"next": "data"}


class TestPipelineValidationAndSnapshot:
    def test_pipeline_validates_and_saves_snapshot_on_clean_handoff(self, pipeline):
        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step(
            {"entities": ["entity1", "entity2"], "data": "next"}
        )

        assert isinstance(result, Success)
        assert result.value.step == 2


class TestPipelineRollback:
    def test_pipeline_triggers_rollback_on_contradiction(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        result = pipeline.execute_step({"data": "next"})

        assert isinstance(result, RollbackSuccess)
        assert result.value.step == 1


class TestPipelineRollback2:
    def test_pipeline_rollback_restores_previous_envelope(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"entities": ["entity1"], "data": "initial"})
        pipeline.execute_step({"data": "next"})
        result = pipeline.rollback()

        assert isinstance(result, (Success, RollbackSuccess))
        assert result.value.step == 1
        assert result.value.payload == {"entities": ["entity1"], "data": "initial"}


class TestPipelineGetCurrentEnvelope:
    def test_pipeline_get_current_envelope_returns_none_initially(self, pipeline):
        result = pipeline.get_current_envelope()
        assert result is None

    def test_pipeline_get_current_envelope_returns_current_after_step(self, pipeline):
        pipeline.execute_step({"data": "test"})
        result = pipeline.get_current_envelope()

        assert result is not None
        assert result.step == 1
        assert result.payload == {"data": "test"}


class TestConcurrentPipeline:
    """R18: Concurrent code must be tested concurrently."""

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    def test_concurrent_step_execution_produces_consistent_results(
        self, mock_initial, temp_storage
    ):
        """Test that concurrent step execution produces consistent results."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []
        lock = threading.Lock()

        def execute_step(step_num):
            try:
                result = pipeline.execute_step({"step": step_num, "data": f"data-{step_num}"})
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

        submitted_payloads = [{"step": i, "data": f"data-{i}"} for i in range(3)]
        assert final_envelope.payload in submitted_payloads, (
            f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
            "possible state corruption from concurrent writes"
        )

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_concurrent_step_execution_with_snapshot_tracking(
        self, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent access to _snapshot_ids is thread-safe."""
        def mock_create_next_envelope(previous_envelope, agent_output, manifest_hash):
            return Success(
                create_mock_envelope(
                    previous_envelope.step + 1,
                    previous_envelope.pipeline_id,
                    agent_output,
                )
            )
        mock_next.side_effect = mock_create_next_envelope

        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []
        lock = threading.Lock()

        def execute_and_advance(step_num):
            try:
                result = pipeline.execute_step({"step": step_num})
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

        submitted_payloads = [{"step": i} for i in range(3)] + [{"initial": "data"}]
        assert final_envelope.payload in submitted_payloads, (
            f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
            "possible state corruption from concurrent writes"
        )

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_concurrent_get_current_envelope(
        self, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent reads of _current_envelope are safe."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, "test-pipeline-id", {"next": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        pipeline.execute_step({"initial": "data"})
        pipeline.execute_step({"next": "data"})

        results = []
        errors = []
        lock = threading.Lock()

        def get_envelope():
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

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_concurrent_reads_and_writes(
        self, mock_next, mock_initial, temp_storage
    ):
        """Concurrent step writes interleaved with reads don't corrupt state."""
        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"initial": "data"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, "test-pipeline-id", {"next": "data"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        pipeline.execute_step({"initial": "data"})

        results = []
        errors = []
        lock = threading.Lock()

        def mixed_access(i: int):
            try:
                if i % 2 == 0:
                    pipeline.execute_step({"step": i})
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

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    @patch("relay.core_pipeline.SnapshotStore")
    def test_concurrent_rollback_access(
        self, mock_store_cls, mock_next, mock_initial, temp_storage
    ):
        """Test that concurrent rollback access is handled safely."""
        mock_store = MagicMock()
        mock_store.save_snapshot.return_value = Success("snapshot-id")
        mock_store.load_snapshot.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"data": "restored"})
        )
        mock_store_cls.return_value = mock_store

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        mock_initial.return_value = Success(
            create_mock_envelope(1, pipeline._pipeline_id, {"data": "initial"})
        )
        mock_next.return_value = Success(
            create_mock_envelope(2, pipeline._pipeline_id, {"data": "next"})
        )

        pipeline.execute_step({"data": "initial"})
        pipeline.execute_step({"data": "next"})

        results = []
        errors = []
        lock = threading.Lock()

        def attempt_rollback():
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
        assert all(isinstance(r, Failure) or isinstance(r, Success) or isinstance(r, RollbackSuccess) for r in results)

        final_envelope = pipeline._state._current_envelope
        previous_envelopes = pipeline._state._previous_envelopes
        snapshot_ids = pipeline._state._snapshot_ids

        if final_envelope is not None:
            current_step = final_envelope.step
            if current_step > 1:
                assert len(previous_envelopes) > 0 or snapshot_ids.get(current_step) is not None, (
                    f"R18 invariant violated: step {current_step} has no snapshot and no previous envelopes. "
                    f"Previous envelopes: {len(previous_envelopes)}, Snapshots: {snapshot_ids}"
                )

    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_thread_pool_executor_operations(
        self, mock_next, mock_initial, temp_storage
    ):
        """Test pipeline operations under thread pool execution."""
        def mock_create_next_envelope(previous_envelope, agent_output, manifest_hash):
            return Success(
                create_mock_envelope(
                    previous_envelope.step + 1,
                    previous_envelope.pipeline_id,
                    agent_output,
                )
            )
        mock_next.side_effect = mock_create_next_envelope

        mock_initial.return_value = Success(
            create_mock_envelope(1, "test-pipeline-id", {"data": "test"})
        )

        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )

        results = []
        errors = []

        def execute_step(step_num):
            try:
                result = pipeline.execute_step({"step": step_num})
                results.append(result)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(execute_step, i) for i in range(5)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        final_envelope = pipeline.get_current_envelope()
        assert final_envelope is not None

        submitted_payloads = [{"step": i} for i in range(5)] + [{"data": "test"}]
        assert final_envelope.payload in submitted_payloads, (
            f"Final payload {final_envelope.payload} is not one of the submitted payloads — "
            "possible state corruption from concurrent writes"
        )


class TestAgentOutputToPayload:
    def test_includes_tool_calls_when_present(self):
        output = AgentOutput(
            text="hello", structured={"key": "val"}, tool_calls=["call1"],
            token_count=10, latency_ms=5, adapter="test",
        )
        result = _agent_output_to_payload(output)
        assert result["text"] == "hello"
        assert result["key"] == "val"
        assert result["tool_calls"] == ["call1"]

    def test_no_tool_calls_when_empty(self):
        output = AgentOutput(
            text="hello", structured={}, tool_calls=[],
            token_count=10, latency_ms=5, adapter="test",
        )
        result = _agent_output_to_payload(output)
        assert result["text"] == "hello"
        assert "tool_calls" not in result


class TestPipelineConstruction:
    def test_fails_on_short_signing_secret(self):
        with pytest.raises(ValueError, match="signing_secret"):
            CoreRelayPipeline(signing_secret="short")


class TestPipelineContextManager:
    def test_context_manager_enter_returns_pipeline(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        with pipeline as p:
            assert p is pipeline

    def test_context_manager_exit_does_not_raise(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        pipeline.__enter__()
        pipeline.__exit__(None, None, None)


class TestPipelineClose:
    def test_close_with_token_counter(self, temp_storage):
        counter = MagicMock()
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000,
            storage_path=temp_storage, token_counter=counter,
        )
        pipeline.close()
        counter.close.assert_called_once()

    def test_close_without_token_counter_does_not_raise(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage
        )
        pipeline.close()


class TestPipelineInitialStepErrors:
    @patch("relay.core_pipeline.HardCapEnforcer")
    def test_budget_failure_in_initial_step(self, mock_enforcer_cls, temp_storage):
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
        result = pipeline.execute_step_with_manifest(
            {"y": "data"}, manifest=manifest,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.BUDGET_EXCEEDED

    def test_create_initial_envelope_failure(self, pipeline):
        with patch(
            "relay.context_broker.ContextBroker.create_initial_envelope",
            return_value=Failure(reason="fail", code=ErrorCode.INVALID_PAYLOAD),
        ):
            result = pipeline.execute_step({"data": "test"})
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PAYLOAD


class TestPipelineSubsequentStepErrors:
    @patch("relay.context_broker.ContextBroker.create_next_envelope")
    def test_create_next_envelope_failure(self, mock_next, pipeline):
        result = pipeline.execute_step({"data": "first"})
        assert isinstance(result, Success)

        mock_next.return_value = Failure(
            reason="fail", code=ErrorCode.INVALID_PAYLOAD,
        )
        result = pipeline.execute_step({"data": "second"})
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.INVALID_PAYLOAD


class TestPipelineBudgetEnforcement:
    def test_manifest_boundary_violation(self, pipeline):
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}),
            writes=frozenset({"permitted"}),
            max_tokens=100,
        )
        result = pipeline.execute_step_with_manifest(
            {"permitted": "ok", "forbidden": "bad"},
            manifest=manifest,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.MANIFEST_BOUNDARY_VIOLATION

    @patch("relay.core_pipeline.HardCapEnforcer")
    def test_budget_failure_in_subsequent_step(self, mock_enforcer_cls, temp_storage):
        counter = MagicMock()
        counter.count.return_value = 10
        enforcer = MagicMock()
        enforcer.check.side_effect = [
            Success(None),
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
        result = pipeline.execute_step_with_manifest(
            {"y": "data"}, manifest=manifest,
        )
        assert isinstance(result, Success)

        result = pipeline.execute_step_with_manifest(
            {"y": "more"}, manifest=manifest,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.BUDGET_EXCEEDED

    @patch("relay.core_pipeline.HardCapEnforcer")
    def test_per_agent_max_tokens_exceeded(self, mock_enforcer_cls, temp_storage):
        counter = MagicMock()
        counter.count.return_value = 9999
        enforcer = MagicMock()
        enforcer.check.return_value = Success(None)
        enforcer.counter = counter
        mock_enforcer_cls.return_value = enforcer

        manifest = AgentManifest(
            "a1", "task", frozenset({"x"}), frozenset({"y"}), max_tokens=10,
        )
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=100,
            storage_path=temp_storage, token_counter=counter,
        )
        result = pipeline.execute_step_with_manifest(
            {"y": "data"}, manifest=manifest,
        )
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.TOKEN_BUDGET_EXCEEDED
        assert "manifest.max_tokens" in result.reason


class TestPipelineApplyManifest:
    @patch("relay.context_broker.ContextBroker.create_initial_envelope")
    def test_apply_manifest_adds_hash_and_signature(self, mock_initial, temp_storage):
        mock_initial.return_value = Success(
            create_mock_envelope(1, "pipe-id", {"y": "data"}),
        )
        manifest = AgentManifest(
            "a1", "task",
            reads=frozenset({"x"}), writes=frozenset({"y"}), max_tokens=100,
        )
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        result = pipeline.execute_step_with_manifest(
            {"y": "data"}, manifest=manifest,
        )
        assert isinstance(result, Success)
        assert result.value.manifest_hash == manifest.compute_hash()
        assert result.value.signature != ""


class TestPipelineRollbackEdgeCases:
    def test_rollback_fails_when_no_history(self, pipeline):
        result = pipeline.rollback()
        assert isinstance(result, Failure)
        assert result.code == ErrorCode.NO_ROLLBACK_AVAILABLE


class TestPipelineBuildContextSlice:
    def test_build_context_slice_with_none_envelope(self, temp_storage):
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

    def test_build_context_slice_filters_by_manifest_reads(self, temp_storage):
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
    def test_slice_payload_returns_empty_when_no_packer(self, temp_storage):
        pipeline = CoreRelayPipeline(
            signing_secret="a" * 32, token_budget=8000, storage_path=temp_storage,
        )
        manifest = AgentManifest(
            "a1", "task", frozenset(), frozenset(), max_tokens=100,
        )
        result = pipeline._slice_payload(manifest, None)
        assert isinstance(result, Success)
        assert result.value == ""

    def test_slice_payload_returns_empty_when_no_envelope(self, temp_storage):
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
    async def test_fails_when_no_registry(self, temp_storage):
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
    async def test_fails_when_adapter_not_found(self, temp_storage):
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
    async def test_fails_on_adapter_exception(self, temp_storage):
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
    async def test_successful_execution_with_runner(self, temp_storage):
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
        assert "runner response" in result.value.payload.get("text", "")
