"""Token counting interfaces and implementations for budget enforcement."""

from typing import Optional, Protocol, runtime_checkable


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
    from tiktoken import Encoding

    class TiktokenCounter:
        """Token counter using tiktoken library.

        Lazy imports tiktoken - must be installed separately:
            pip install relay[tiktoken]

        Must call close() to release encoding resource.
        """

        def __init__(self, encoding: str = "cl100k_base") -> None:
            self._encoding = encoding
            self._enc: Optional[Encoding] = None

        def _get_encoder(self) -> Encoding:
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
    TiktokenCounter = None  # type: ignore