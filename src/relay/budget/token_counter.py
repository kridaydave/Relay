from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for counting tokens in text."""

    def count(self, text: str) -> int:
        """Count tokens in the given text."""
        ...


class TiktokenCounter:
    """Token counter using tiktoken library.

    Lazy import - tiktoken is an optional dependency.
    Use `pip install relay[tiktoken]` to install.
    """

    def __init__(self, encoding: str = "cl100k_base"):
        import tiktoken

        self._enc = tiktoken.get_encoding(encoding)

    def count(self, text: str) -> int:
        """Count tokens in the given text."""
        return len(self._enc.encode(text))