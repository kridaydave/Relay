"""Context slicing strategies and agent manifest boundaries.

Provides pluggable context slicing strategies and agent manifest definitions.

Exports:
    AgentManifest: Manifest defining agent read/write permissions.
    EmbeddingProvider: Protocol for embedding implementations.
    RecencySlicePacker: Selects most recent sections by step order.
    RelevanceSlicePacker: Ranks sections by cosine similarity.
    StructuralSlicePacker: Selects sections in manifest reads.
"""

from relay.slicer.manifest import AgentManifest
from relay.slicer.packers import RecencySlicePacker, RelevanceSlicePacker, StructuralSlicePacker, SlicePacker
from relay.slicer.providers import EmbeddingProvider

__all__ = [
    "AgentManifest",
    "EmbeddingProvider",
    "SlicePacker",
    "RecencySlicePacker",
    "RelevanceSlicePacker",
    "StructuralSlicePacker",
]