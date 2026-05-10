"""Token counting interfaces and heuristic implementations for budget enforcement.

Owns: TokenCounter protocol, TiktokenCounter implementation, character-based estimation.
Does NOT: enforce budget limits, manage token tracking across steps, or validate token counts.
"""

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

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

try:
    import tiktoken

    class TiktokenCounter:
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

        def __enter__(self) -> "TiktokenCounter":
            """Enter the context manager."""
            return self

        def __exit__(self, *_: object) -> None:
            """Exit the context manager and release resources."""
            self.close()

except ImportError:
    TiktokenCounter = None  # type: ignore[assignment, misc]