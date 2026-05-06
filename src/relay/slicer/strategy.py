from enum import Enum, auto


class SliceStrategy(Enum):
    """Context slicing strategies for selecting relevant context."""

    RECENCY = auto()
    RELEVANCE = auto()
    STRUCTURAL = auto()