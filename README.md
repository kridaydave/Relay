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

- **Context Broker** — Normalizes, timestamps, and cryptographically signs context envelopes
- **Handoff Validator** — Detects contradictions and triggers rollback on corruption
- **Snapshot Store** — Persists immutable checkpoints for automatic rollback

---

## Installation

```bash
git clone https://github.com/kridaydave/Relay.git
cd Relay
pip install -e .
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
  "relay_version": "0.1.0",
  "pipeline_id": "uuid-v4",
  "step": 2,
  "timestamp": "2026-05-04T10:22:00Z",
  "token_budget_used": 1840,
  "token_budget_total": 8000,
  "payload": {...},
  "signature": "sha256:abc123..."
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