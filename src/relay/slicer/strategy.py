"""Slice strategy enumeration for context selection."""

from enum import Enum, auto


class SliceStrategy(Enum):
    """Enumeration of context slicing strategies."""

    RECENCY = auto()
    RELEVANCE = auto()
    STRUCTURAL = auto()