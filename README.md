# Relay

**Agent-agent context passing, done right.**

Relay is a lightweight, open source Python middleware library for passing context reliably between AI agents in a multi-agent pipeline. Works with any LLM provider or framework — LangChain, OpenAI, Anthropic, LiteLLM, or your own agents.

---

## The Problem

One hallucinating agent silently corrupts the shared context, and every downstream agent inherits the damage. Existing orchestration tools treat the context window as a mutable blob with no version control.

## The Solution

Relay treats context like a ledger: append-only, signed at every step, and reversible.

---

## Features

- **Agent Runners** — Universal adapter layer for any LLM provider or framework (v0.3)
- **Context Broker** — Normalizes, timestamps, and cryptographically signs context envelopes
- **Handoff Validator** — Detects contradictions and triggers rollback on corruption
- **Snapshot Store** — Persists immutable checkpoints for automatic rollback
- **Budget Enforcer** — Hard token cap enforcement before every agent call
- **Slicer** — Pluggable context slicing strategies (recency, relevance, structural)
- **Manifest Boundaries** — Agent manifests define read/write permissions with hash verification

---

## Installation

```bash
pip install relay-middleware
```

Or from source:

```bash
git clone https://github.com/kridaydave/Relay.git
cd Relay
pip install -e .
```

Optional: install tiktoken for precise token counting:

```bash
pip install relay-middleware[tiktoken]
```

---

## The Aha Moment

**Without Relay** (manual, error-prone):

```python
# Agent 1 produces output
agent1_output = {"entities": ["Apple", "2024 revenue"], "summary": "Apple grew"}

# Manual serialization — easy to lose data, corrupt context
context = json.dumps(agent1_output)

# Agent 2 receives corrupted context
agent2_input = f"Given: {context}\nAnalyze this."
```

**With Relay** (automatic, verified):

```python
from relay.core_pipeline import CoreRelayPipeline

pipeline = CoreRelayPipeline(
    signing_secret="your-secret-key",
    token_budget=8000
)

# Agent 1 — creates signed envelope
result = pipeline.execute_step({"entities": ["Apple"], "revenue": "2024"})
envelope1 = result.value  # signed, immutable

# Agent 2 — validator detects contradiction
# If Agent 2 accidentally drops "entities", rollback triggers automatically
result = pipeline.execute_step({"summary": "growth"})  # contradiction!
```

**What happens on contradiction:**

```python
# Validator detects: critical key "entities" disappeared
# Relay automatically rolls back to last clean snapshot

result = pipeline.rollback()
restored_envelope = result.value
# Now you have the clean envelope from step 1
```

---

## Budget & Slicing (v0.2)

Enforce token limits and slice context intelligently:

```python
from relay.core_pipeline import CoreRelayPipeline
from relay.budget import TiktokenCounter
from relay.slicer import AgentManifest, RecencySlicePacker

# Create manifest defining agent permissions
manifest = AgentManifest(
    agent_id="agent-1",
    task_description="Analyze entities and summarize findings",
    reads=frozenset({"entities", "summary"}),
    writes=frozenset({"analysis"}),
    max_tokens=4000
)

# Initialize pipeline with budget enforcement and slicer
pipeline = CoreRelayPipeline(
    signing_secret="your-secret",
    token_budget=8000,
    token_counter=TiktokenCounter(),
    slice_packer=RecencySlicePacker()
)

# Execute step with manifest validation
result = pipeline.execute_step_with_manifest(
    agent_output={"analysis": "growth at 5%"},
    manifest=manifest
)
```

The budget enforcer checks projected token cost before each call. The slicer selects context based on strategy. Manifest boundaries validate write permissions.

---

## Agent Runners (v0.3)

Use the adapter registry to plug any LLM provider into Relay without touching Relay internals:

```python
import asyncio
from relay.runners import AdapterRegistry, RawSDKAdapter, AgentManifest

registry = AdapterRegistry()

# Register any callable — sync or async
def openai_callable(messages):
    return openai.chat.completions.create(model="gpt-4", messages=messages)

registry.register("openai", RawSDKAdapter(callable=openai_callable))

# Or use bundled adapters
from relay.runners import LocalModelAdapter
registry.register("ollama", LocalModelAdapter(base_url="http://localhost:11434", model="llama3"))
```

```python
from relay.core_pipeline import CoreRelayPipeline

pipeline = CoreRelayPipeline(
    signing_secret="your-secret",
    token_budget=8000,
    registry=registry,
)

manifest = AgentManifest(
    agent_id="openai",
    task_description="Analyze entities and summarize findings",
    reads=frozenset({"entities", "summary"}),
    writes=frozenset({"analysis"}),
    max_tokens=4000,
)

async def run():
    # First step: seed the pipeline
    pipeline.execute_step({"entities": ["Apple"], "summary": "revenue up"})

    # Execute via adapter — no LLM calls in Relay, only normalisation
    result = await pipeline.execute_step_with_runner("openai", manifest)
    # result is Success(SignedEnvelope) or Failure(ErrorCode.*)
```

All adapters are lazy-loaded. Install only what you need:

```bash
pip install relay-middleware[langchain]   # LangChain Runnable
pip install relay-middleware[crewai]      # CrewAI Agent
pip install relay-middleware[autogen]     # AutoGen AssistantAgent
pip install relay-middleware[local]       # Ollama / vLLM / OpenAI-compatible
pip install relay-middleware[all]         # everything
```

---

## How It Works

```
Agent 1 → [Sign Envelope] → Agent 2 → [Validate] → Agent 3
                              ↓
                         [Snapshot]
                              ↓
                    [Rollback if dirty]
```

Every handoff is signed and validated. If corruption is detected, Relay silently rolls back to the last clean checkpoint.

---

## Context Envelope

Every context move between agents is wrapped in a signed, immutable envelope:

```python
{
  "relay_version": "0.3.0",
  "pipeline_id": "uuid-v4",
  "step": 2,
  "timestamp": "2026-05-04T10:22:00Z",
  "token_budget_used": 1840,
  "token_budget_total": 8000,
  "payload": {...},
  "manifest_hash": "sha256:abc123...",
  "signature": "sha256:def456..."
}
```

---

## Error Handling

Relay uses Result types instead of exceptions:

```python
from relay.types import Success, Failure, Result

result = pipeline.execute_step({"task": "work"})
if isinstance(result, Success):
    envelope = result.value
elif isinstance(result, Failure):
    print(f"Error: {result.reason} (code: {result.code})")
```

---

## Testing

```bash
pytest tests/unit -v
```

Quality gates:
- mypy --strict passes
- >80% test coverage
- Every public function has a test

---

## License

MIT License - see LICENSE file

---

## Resources

- [Design Document](docs/Relay%20Design%20Document.txt)
- [Coding Rules](docs/Relay%20Coding%20Rules.txt)