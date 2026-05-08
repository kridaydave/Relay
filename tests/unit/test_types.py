"""Unit tests for relay.types."""

from dataclasses import dataclass

import pytest

from relay.types import (
    Success,
    Failure,
    RollbackSuccess,
    Result,
    is_success,
    is_failure,
    unwrap,
    unwrap_or,
    map_result,
    map_error,
)


@dataclass(frozen=True)
class SuccessFixture:
    value: str


@dataclass(frozen=True)
class FailureFixture:
    reason: str
    code: str


class TestSuccess:
    def test_success_contains_value(self):
        success = Success(value=42)
        assert success.value == 42


class TestFailure:
    def test_failure_contains_reason_and_code(self):
        failure = Failure(reason="Something went wrong", code="ERR_001")
        assert failure.reason == "Something went wrong"
        assert failure.code == "ERR_001"


class TestIsSuccess:
    def test_is_success_returns_true_for_success(self):
        result: Result[str] = Success(value="hello")
        assert is_success(result) is True

    def test_is_success_returns_false_for_failure(self):
        result: Result[str] = Failure(reason="error", code="ERR")
        assert is_success(result) is False


class TestIsFailure:
    def test_is_failure_returns_true_for_failure(self):
        result: Result[str] = Failure(reason="error", code="ERR")
        assert is_failure(result) is True

    def test_is_failure_returns_false_for_success(self):
        result: Result[str] = Success(value="hello")
        assert is_failure(result) is False


class TestUnwrap:
    def test_unwrap_returns_value_from_success(self):
        result: Result[str] = Success(value="test value")
        assert unwrap(result) == "test value"

    def test_unwrap_raises_on_failure(self):
        result: Result[str] = Failure(reason="error", code="ERR")
        with pytest.raises(ValueError, match="Unwrap called on Failure"):
            unwrap(result)


class TestUnwrapOr:
    def test_unwrap_or_returns_value_or_default(self):
        result: Result[str] = Success(value="actual")
        assert unwrap_or(result, "default") == "actual"

    def test_unwrap_or_returns_default_on_failure(self):
        result: Result[str] = Failure(reason="error", code="ERR")
        assert unwrap_or(result, "default") == "default"

    def test_unwrap_or_returns_default_for_rollback_success(self):
        result: Result[str] = RollbackSuccess(value="restored", reason="contradiction")
        assert unwrap_or(result, "default") == "default"


class TestMapResult:
    def test_map_result_applies_function_to_success(self):
        result: Result[int] = Success(value=5)
        mapped = map_result(result, lambda x: x * 2)
        assert isinstance(mapped, Success)
        assert mapped.value == 10

    def test_map_result_leaves_failure_unchanged(self):
        result: Result[int] = Failure(reason="error", code="ERR")
        mapped = map_result(result, lambda x: x * 2)
        assert mapped is result

    def test_map_result_leaves_rollback_success_unchanged(self):
        result: Result[int] = RollbackSuccess(value=5, reason="rollback")
        mapped = map_result(result, lambda x: x * 2)
        assert mapped is result


class TestMapError:
    def test_map_error_applies_function_to_failure(self):
        result: Result[int] = Failure(reason="original", code="ERR_001")
        mapped = map_error(
            result, lambda f: Failure(reason=f"New: {f.reason}", code=f"NEW_{f.code}")
        )
        assert isinstance(mapped, Failure)
        assert mapped.reason == "New: original"
        assert mapped.code == "NEW_ERR_001"

    def test_map_error_leaves_success_unchanged(self):
        result: Result[int] = Success(value=42)
        mapped = map_error(result, lambda f: Failure(reason="new", code="NEW"))
        assert mapped is result