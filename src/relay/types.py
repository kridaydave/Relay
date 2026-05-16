"""Result types and error handling for Relay.

Owns: Success, Failure, and Result union types, __version__.
Does NOT: handle specific domain errors, validate data, or make decisions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar

JSONDict = dict[str, object]
"""A JSON-serializable dictionary with string keys and object values."""

__version__ = "0.4.1"

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Error codes for Relay failures. Used exhaustively for type safety."""

    INVALID_PIPELINE_ID = "INVALID_PIPELINE_ID"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    INVALID_TOKEN_COUNT = "INVALID_TOKEN_COUNT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MANIFEST_BOUNDARY_VIOLATION = "MANIFEST_BOUNDARY_VIOLATION"
    PIPELINE_MISMATCH = "PIPELINE_MISMATCH"
    INVALID_STEP = "INVALID_STEP"
    INVALID_SNAPSHOT_ID = "INVALID_SNAPSHOT_ID"
    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    SNAPSHOT_SAVE_FAILED = "SNAPSHOT_SAVE_FAILED"
    SNAPSHOT_LOAD_FAILED = "SNAPSHOT_LOAD_FAILED"
    INDEX_UPDATE_FAILED = "INDEX_UPDATE_FAILED"
    INDEX_NOT_FOUND = "INDEX_NOT_FOUND"
    INVALID_INDEX = "INVALID_INDEX"
    CORRUPTED_INDEX = "CORRUPTED_INDEX"
    INDEX_READ_FAILED = "INDEX_READ_FAILED"
    NO_SNAPSHOT_REGISTERED = "NO_SNAPSHOT_REGISTERED"
    NO_ROLLBACK_AVAILABLE = "NO_ROLLBACK_AVAILABLE"
    PIPELINE_NOT_FOUND = "PIPELINE_NOT_FOUND"
    NO_SNAPSHOTS = "NO_SNAPSHOTS"
    INVALID_STATE = "INVALID_STATE"
    INVALID_SNAPSHOT = "INVALID_SNAPSHOT"
    MISSING_SECTIONS = "MISSING_SECTIONS"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    ADAPTER_NOT_FOUND = "ADAPTER_NOT_FOUND"
    NO_REGISTRY = "NO_REGISTRY"
    ADAPTER_EXECUTION_FAILED = "ADAPTER_EXECUTION_FAILED"
    INVALID_SECRET = "INVALID_SECRET"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    ALL_FORKS_FAILED = "ALL_FORKS_FAILED"
    FORK_EXECUTION_FAILED = "FORK_EXECUTION_FAILED"
    INVALID_JOIN_STRATEGY = "INVALID_JOIN_STRATEGY"


@dataclass(frozen=True)
class Success(Generic[T]):
    """Represents a successful result with a value."""

    value: T


@dataclass(frozen=True)
class Failure:
    """Represents a failed result with a reason and error code."""

    reason: str
    code: ErrorCode = ErrorCode.UNKNOWN_ERROR


@dataclass(frozen=True)
class RollbackSuccess(Generic[T]):
    """Represents a successful rollback result with restored value and reason."""

    value: T
    reason: str


type Result[T] = Success[T] | RollbackSuccess[T] | Failure


def is_success(result: Result[T]) -> bool:
    """Check if a Result is a Success."""
    return isinstance(result, Success)


def is_failure(result: Result[T]) -> bool:
    """Check if a Result is a Failure."""
    return isinstance(result, Failure)


def unwrap(result: Result[T]) -> T:
    """Extract value from Success, raise on Failure or RollbackSuccess."""
    if isinstance(result, Success):
        return result.value
    raise ValueError(f"Unwrap called on non-Success: {result}")


def unwrap_or(result: Result[T], default: T) -> T:
    """Extract value from Success, return default on Failure or RollbackSuccess.

    RollbackSuccess carries a restored value but callers of unwrap_or typically
    want the default on any non-Success path — this is a deliberate design choice
    that differs from map_result (which transforms RollbackSuccess). Use map_result
    if you need to transform the rollback value.
    """
    if isinstance(result, Success):
        return result.value
    return default


U = TypeVar("U")


def map_result(result: "Result[T]", fn: Callable[[T], U]) -> "Result[U]":
    """Apply function to Success value, leave Failure unchanged."""
    if isinstance(result, Success):
        return Success(fn(result.value))
    if isinstance(result, RollbackSuccess):
        return RollbackSuccess(fn(result.value), result.reason)
    return result


def map_error(result: "Result[T]", fn: Callable[[Failure], Failure]) -> "Result[T]":
    """Apply function to Failure, leave Success unchanged."""
    if isinstance(result, Failure):
        return fn(result)
    return result
