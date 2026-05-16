"""Token counting interfaces and heuristic implementations for budget enforcement.

Owns: TokenCounter protocol, TiktokenCounter implementation, character-based estimation.
Does NOT: enforce budget limits, manage token tracking across steps, or validate token counts.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from tiktoken import Encoding


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        ...

    def close(self) -> None:
        """Release any resources held by the counter. Optional method."""
        ...


class HeuristicCounter:
    """Fallback token counter using character-based estimation.

    Uses len(text) // 3 as a rough approximation of token count.
    Used when tiktoken is not installed.
    """

    def count(self, text: str) -> int:
        return max(1, len(text) // 3)

    def close(self) -> None:
        pass

    def __enter__(self) -> "HeuristicCounter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


try:
    import tiktoken

    class _TiktokenCounter:
        """Token counter using tiktoken library.

        Lazy imports tiktoken - must be installed separately:
            pip install relay[tiktoken]

        Must call close() to release encoding resource.
        """

        def __init__(self, encoding: str = "cl100k_base") -> None:
            self._encoding = encoding
            self._enc: "Encoding | None" = None

        def _get_encoder(self) -> "Encoding":
            if self._enc is None:
                self._enc = tiktoken.get_encoding(self._encoding)
            return self._enc

        def count(self, text: str) -> int:
            enc = self._get_encoder()
            return len(enc.encode(text))

        def close(self) -> None:
            """Release the encoding resource."""
            self._enc = None

        def __enter__(self) -> "_TiktokenCounter":
            """Enter the context manager."""
            return self

        def __exit__(self, *_: object) -> None:
            """Exit the context manager and release resources."""
            self.close()

    AutoTokenCounter: type[TokenCounter] = _TiktokenCounter
except ImportError:
    AutoTokenCounter = HeuristicCounter