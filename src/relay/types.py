"""Result types and error handling for Relay.

Owns: Success, Failure, and Result union types.
Does NOT: handle specific domain errors, validate data, or make decisions.
"""

from dataclasses import dataclass
from typing import TypeVar, Generic, Union, Callable, overload, TypeAlias


T = TypeVar("T")


class RelayError(Exception):
    """Base exception for Relay-specific errors."""
    pass


@dataclass(frozen=True)
class BudgetExceededError(RelayError):
    """Raised when token budget would be exceeded by an agent call."""
    used: int
    projected: int
    limit: int
    step: int


@dataclass(frozen=True)
class HandoffValidationError(RelayError):
    """Raised when an agent writes to a section not in its manifest."""
    agent_id: str
    offending_section: str
    step: int


@dataclass(frozen=True)
class ManifestHashMismatchError(RelayError):
    """Raised when manifest hash doesn't match expected value."""
    expected_hash: str
    actual_hash: str
    step: int


@dataclass(frozen=True)
class Success(Generic[T]):
    """Represents a successful result with a value."""
    value: T


@dataclass(frozen=True)
class Failure:
    """Represents a failed result with a reason and error code."""
    reason: str
    code: str = "UNKNOWN_ERROR"


@dataclass(frozen=True)
class RollbackSuccess(Generic[T]):
    """Represents a successful rollback result with restored value and reason."""
    value: T
    reason: str


Result: TypeAlias = Union[Success[T], RollbackSuccess[T], Failure]


def is_success(result: Result[T]) -> bool:
    """Check if a Result is a Success."""
    return isinstance(result, Success)


def is_failure(result: Result[T]) -> bool:
    """Check if a Result is a Failure."""
    return isinstance(result, Failure)


def unwrap(result: Result[T]) -> T:
    """Extract value from Success, raise on Failure."""
    if isinstance(result, Success):
        return result.value
    raise ValueError(f"Unwrap called on Failure: {result.reason}")


def unwrap_or(result: Result[T], default: T) -> T:
    """Extract value from Success, return default on Failure."""
    if isinstance(result, Success):
        return result.value
    return default


def map_result(result: Result[T], fn: Callable[[T], T]) -> Result[T]:
    """Apply function to Success value, leave Failure unchanged."""
    if isinstance(result, Success):
        return Success(fn(result.value))
    return result


def map_error(result: Result[T], fn: Callable[[Failure], Failure]) -> Result[T]:
    """Apply function to Failure, leave Success unchanged."""
    if isinstance(result, Failure):
        return fn(result)
    return result