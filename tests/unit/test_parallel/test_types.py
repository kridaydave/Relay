"""Shape and invariant tests for parallel types."""

import pytest

from relay.parallel.types import JoinStrategy
from tests.unit.test_parallel.conftest import (
    make_fork_spec,
    make_passing_fork_result,
    make_failing_fork_result,
)


class TestJoinStrategy:
    def test_join_strategy_values_match_design_doc_when_checked(self) -> None:
        """Strategy string values match Design Doc section 4 join strategy names."""
        assert JoinStrategy.UNION.value == "UNION"
        assert JoinStrategy.VOTE.value == "VOTE"
        assert JoinStrategy.FIRST_WINS.value == "FIRST_WINS"

    def test_join_strategy_is_string_enum_when_serialized(self) -> None:
        """JoinStrategy values usable as strings for serialization."""
        assert JoinStrategy.UNION == "UNION"


class TestForkSpec:
    def test_fork_spec_is_frozen_when_modified(self) -> None:
        spec = make_fork_spec()
        with pytest.raises(Exception):
            spec.adapter_name = "changed"  # type: ignore[misc]


class TestForkResult:
    def test_passing_fork_result_has_no_failure_when_successful(self) -> None:
        result = make_passing_fork_result()
        assert result.success is True
        assert result.failure is None
        assert result.agent_output is not None
        assert result.validation is not None

    def test_failing_fork_result_has_no_output_when_failed(self) -> None:
        result = make_failing_fork_result()
        assert result.success is False
        assert result.agent_output is None
        assert result.failure is not None
