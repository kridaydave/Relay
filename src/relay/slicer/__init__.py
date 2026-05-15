"""Context slicing strategies and agent manifest definitions.

Owns: AgentManifest, SlicePacker protocol, EmbeddingProvider protocol.
Does NOT: implement embedding providers or token counting.
"""

from relay.slicer.manifest import AgentManifest
from relay.slicer.packers import RecencySlicePacker, RelevanceSlicePacker, StructuralSlicePacker
from relay.slicer.providers import EmbeddingProvider, SlicePacker

__all__ = [
    "AgentManifest",
    "EmbeddingProvider",
    "SlicePacker",
    "RecencySlicePacker",
    "RelevanceSlicePacker",
    "StructuralSlicePacker",
]