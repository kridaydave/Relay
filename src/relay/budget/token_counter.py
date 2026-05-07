"""Token counting interfaces and implementations for budget enforcement."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        ...


try:
    import tiktoken

    class TiktokenCounter:
        """Token counter using tiktoken library.

        Lazy imports tiktoken - must be installed separately:
            pip install relay[tiktoken]

        Must call close() to release encoding resource.
        """

        def __init__(self, encoding: str = "cl100k_base"):
            self._encoding = encoding
            self._enc = None

        def _get_encoder(self):
            if self._enc is None:
                self._enc = tiktoken.get_encoding(self._encoding)
            return self._enc

        def count(self, text: str) -> int:
            enc = self._get_encoder()
            return len(enc.encode(text))

        def close(self) -> None:
            """Release the encoding resource."""
            self._enc = None

except ImportError:
    TiktokenCounter = None  # type: ignore