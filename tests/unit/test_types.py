"""Unit tests for relay.types."""

from dataclasses import dataclass

import pytest

from relay.types import (
    ErrorCode,
    Failure,
    Result,
    RollbackSuccess,
    Success,
    is_failure,
    is_success,
    map_error,
    map_result,
    unwrap,
    unwrap_or,
)


@dataclass(frozen=True)
class SuccessFixture:
    """Fixture for successful result values."""

    value: str


@dataclass(frozen=True)
class FailureFixture:
    """Fixture for failure result details."""

    reason: str
    code: str


class TestSuccess:
    """Tests for the Success result type."""

    def test_success_contains_value(self) -> None:
        """Verify Success stores and returns its value."""
        success = Success(value=42)
        assert success.value == 42


class TestFailure:
    """Tests for the Failure result type."""

    def test_failure_contains_reason_and_code(self) -> None:
        """Verify Failure stores and returns reason and code."""
        failure = Failure(reason="Something went wrong", code=ErrorCode.UNKNOWN_ERROR)
        assert failure.reason == "Something went wrong"
        assert failure.code == ErrorCode.UNKNOWN_ERROR


class TestIsSuccess:
    """Tests for the is_success predicate."""

    def test_is_success_returns_true_for_success(self) -> None:
        """Verify is_success returns True for Success instances."""
        result: Result[str] = Success(value="hello")
        assert is_success(result) is True

    def test_is_success_returns_false_for_failure(self) -> None:
        """Verify is_success returns False for Failure instances."""
        result: Result[str] = Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR)
        assert is_success(result) is False

    def test_is_success_returns_false_for_rollback_success(self) -> None:
        """Verify is_success returns False for RollbackSuccess instances."""
        result: Result[str] = RollbackSuccess(value="restored", reason="rollback")
        assert is_success(result) is False


class TestIsFailure:
    """Tests for the is_failure predicate."""

    def test_is_failure_returns_true_for_failure(self) -> None:
        """Verify is_failure returns True for Failure instances."""
        result: Result[str] = Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR)
        assert is_failure(result) is True

    def test_is_failure_returns_false_for_success(self) -> None:
        """Verify is_failure returns False for Success instances."""
        result: Result[str] = Success(value="hello")
        assert is_failure(result) is False

    def test_is_failure_returns_false_for_rollback_success(self) -> None:
        """Verify is_failure returns False for RollbackSuccess instances."""
        result: Result[str] = RollbackSuccess(value="restored", reason="rollback")
        assert is_failure(result) is False


class TestUnwrap:
    """Tests for the unwrap function."""

    def test_unwrap_returns_value_from_success(self) -> None:
        """Verify unwrap extracts value from Success."""
        result: Result[str] = Success(value="test value")
        assert unwrap(result) == "test value"

    def test_unwrap_raises_on_failure(self) -> None:
        """Verify unwrap raises ValueError when called on Failure."""
        result: Result[str] = Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR)
        with pytest.raises(ValueError, match="Unwrap called on non-Success"):
            unwrap(result)

    def test_unwrap_raises_on_rollback_success(self) -> None:
        """unwrap should raise ValueError on RollbackSuccess."""
        result: Result[int] = RollbackSuccess(value=42, reason="test")
        with pytest.raises(ValueError, match="non-Success"):
            unwrap(result)


class TestUnwrapOr:
    """Tests for the unwrap_or function."""

    def test_unwrap_or_returns_value_or_default(self) -> None:
        """Verify unwrap_or returns Success value if present."""
        result: Result[str] = Success(value="actual")
        assert unwrap_or(result, "default") == "actual"

    def test_unwrap_or_returns_default_on_failure(self) -> None:
        """Verify unwrap_or returns default value on Failure."""
        result: Result[str] = Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR)
        assert unwrap_or(result, "default") == "default"

    def test_unwrap_or_returns_default_on_rollback_success(self) -> None:
        """Verify unwrap_or returns default on RollbackSuccess per documented contract."""
        result: Result[str] = RollbackSuccess(value="restored", reason="rollback")
        assert unwrap_or(result, "default") == "default"


class TestMapResult:
    """Tests for the map_result function."""

    def test_map_result_applies_function_to_success_when_present(self) -> None:
        """Verify map_result transforms Success value."""
        result: Result[int] = Success(value=5)
        mapped = map_result(result, lambda x: x * 2)
        assert isinstance(mapped, Success)
        assert mapped.value == 10

    def test_map_result_leaves_failure_unchanged_when_mapping(self) -> None:
        """Verify map_result ignores Failure instances."""
        result: Result[int] = Failure(reason="error", code=ErrorCode.UNKNOWN_ERROR)
        mapped = map_result(result, lambda x: x * 2)
        assert mapped is result

    def test_map_result_transforms_rollback_success_when_present(self) -> None:
        """map_result should transform RollbackSuccess value."""
        result: Result[int] = RollbackSuccess(value=5, reason="rolled back")
        mapped = map_result(result, lambda x: x * 2)
        assert isinstance(mapped, RollbackSuccess)
        assert mapped.value == 10
        assert mapped.reason == "rolled back"


class TestMapError:
    """Tests for the map_error function."""

    def test_map_error_applies_function_to_failure_when_present(self) -> None:
        """Verify map_error transforms Failure details."""
        result: Result[int] = Failure(reason="original", code=ErrorCode.INVALID_PIPELINE_ID)
        mapped = map_error(
            result, lambda f: Failure(reason=f"New: {f.reason}", code=f.code)
        )
        assert isinstance(mapped, Failure)
        assert mapped.reason == "New: original"
        assert mapped.code == ErrorCode.INVALID_PIPELINE_ID

    def test_map_error_leaves_success_unchanged_when_mapping(self) -> None:
        """Verify map_error ignores Success instances."""
        result: Result[int] = Success(value=42)
        mapped = map_error(result, lambda f: Failure(reason="new", code=ErrorCode.UNKNOWN_ERROR))
        assert mapped is result

    def test_map_error_leaves_rollback_success_unchanged_when_mapping(self) -> None:
        """Verify map_error ignores RollbackSuccess instances."""
        result: Result[int] = RollbackSuccess(value=42, reason="rollback")
        mapped = map_error(result, lambda f: Failure(reason="new", code=ErrorCode.UNKNOWN_ERROR))
        assert mapped is result


class TestRollbackSuccessContract:
    """Tests specifically for the RollbackSuccess contract."""

    def test_rollback_success_is_neither_success_nor_failure_when_checked(self) -> None:
        """Verify RollbackSuccess is not identified as Success or Failure."""
        result: Result[int] = RollbackSuccess(value=100, reason="manual rollback")
        assert is_success(result) is False
        assert is_failure(result) is False

    def test_map_error_ignores_rollback_success_when_invoked(self) -> None:
        """Verify map_error returns original RollbackSuccess unchanged."""
        result: Result[int] = RollbackSuccess(value=100, reason="manual rollback")
        assert map_error(result, lambda f: Failure(reason="fail", code=ErrorCode.UNKNOWN_ERROR)) is result
