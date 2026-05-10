"""Agent manifest definition for context read/write boundaries.

Owns: AgentManifest data model, read/write permission sets, hash computation.
Does NOT: validate manifests, enforce permissions, or manage agent lifecycle.
"""

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentManifest:
    """Manifest defining an agent's read/write permissions and token budget.

    Attributes:
        agent_id: Unique identifier for the agent.
        task_description: Description of the agent's task for relevance scoring.
        reads: Set of section keys the agent may read.
        writes: Set of section keys the agent may write.
        max_tokens: Maximum tokens allowed for this agent's context.
    """

    agent_id: str
    task_description: str
    reads: frozenset[str]
    writes: frozenset[str]
    max_tokens: int

    def compute_hash(self) -> str:
        """Compute deterministic SHA256 hash of the manifest.

        Uses sorted keys for frozenset fields to ensure deterministic
        output across Python sessions.
        """
        canonical = json.dumps(
            {
                "agent_id": self.agent_id,
                "task_description": self.task_description,
                "reads": sorted(self.reads),
                "writes": sorted(self.writes),
                "max_tokens": self.max_tokens,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()