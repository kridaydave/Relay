"""Token counting interfaces and heuristic implementations for budget enforcement.

Owns: TokenCounter protocol, TiktokenCounter implementation, character-based estimation.
Does NOT: enforce budget limits, manage token tracking across steps, or validate token counts.
"""

from __future__ import annotations

import threading
from typing import Protocol, cast, runtime_checkable


class _Encoding(Protocol):
    """Minimal protocol for tiktoken Encoding — avoids depending on tiktoken type stubs."""

    def encode(self, text: str) -> list[int]: ...


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for token counting implementations."""

    def count(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        ...

    def close(self) -> None:
        """Release any resources held by the counter. Optional method."""
        ...


class HeuristicCounter(TokenCounter):
    """Fallback token counter using character-based estimation.

    Uses len(text) // 3 as a rough approximation of token count.
    Used when tiktoken is not installed.
    """

    def count(self, text: str) -> int:
        return max(1, len(text) // 3)

    def close(self) -> None:
        pass

    def __enter__(self) -> HeuristicCounter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


try:
    import tiktoken  # pyright: ignore[reportMissingImports]

    def _load_encoding(name: str) -> _Encoding:
        """Load a tiktoken encoding by name.

        Casts from Any because tiktoken types may not have stubs installed.
        """
        return cast(_Encoding, tiktoken.get_encoding(name))

    class _TiktokenCounter(TokenCounter):
        """Token counter using tiktoken library.

        Lazy imports tiktoken - must be installed separately:
            pip install relay[tiktoken]

        Thread-safe: uses a lock for lazy encoder loading.
        Must call close() to release encoding resource.
        """

        def __init__(self, encoding: str = "cl100k_base") -> None:
            self._encoding = encoding
            self._enc: _Encoding | None = None
            self._lock = threading.Lock()

        def _get_encoder(self) -> _Encoding:
            if self._enc is None:
                with self._lock:
                    if self._enc is None:
                        self._enc = _load_encoding(self._encoding)
            return self._enc

        def count(self, text: str) -> int:
            enc = self._get_encoder()
            return len(enc.encode(text))

        def close(self) -> None:
            """Release the encoding resource."""
            self._enc = None

        def __enter__(self) -> _TiktokenCounter:
            """Enter the context manager."""
            return self

        def __exit__(self, *_: object) -> None:
            """Exit the context manager and release resources."""
            self.close()

    AutoTokenCounter: type[TokenCounter] = _TiktokenCounter
except ImportError:
    AutoTokenCounter = HeuristicCounter
