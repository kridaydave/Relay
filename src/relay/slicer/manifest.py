import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentManifest:
    """Manifest defining an agent's access boundaries.

    Attributes:
        agent_id: Unique identifier for this agent.
        reads: Section keys the agent may read.
        writes: Section keys the agent may write.
        max_tokens: Maximum tokens allowed for this agent's context.
    """

    agent_id: str
    reads: frozenset[str]
    writes: frozenset[str]
    max_tokens: int

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 hash of the manifest.

        Uses sorted() for frozenset serialization to ensure determinism
        across Python sessions.
        """
        canonical = json.dumps(
            {
                "agent_id": self.agent_id,
                "reads": sorted(self.reads),
                "writes": sorted(self.writes),
                "max_tokens": self.max_tokens,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()