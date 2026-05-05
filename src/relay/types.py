"""Result types and error handling for Relay.

Owns: Success, Failure, and Result union types.
Does NOT: handle specific domain errors, validate data, or make decisions.
"""

from dataclasses import dataclass
from typing import TypeVar, Generic, Union, Callable, overload


T = TypeVar("T")


@dataclass(frozen=True)
class Success(Generic[T]):
    """Represents a successful operation with a value."""
    value: T


@dataclass(frozen=True)
class RollbackSuccess(Success[T]):
    """Represents a successful rollback operation.
    
    Carries the restored value (envelope) and the reason for the rollback.
    """
    reason: str


@dataclass(frozen=True)
class Failure:
    """Represents a failed operation with a reason and error code."""
    reason: str
    code: str


Result = Union[Success[T], Failure]


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