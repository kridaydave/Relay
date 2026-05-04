# Relay

**Agent-agent context passing, done right.**

Relay is a lightweight, open source Python middleware library for passing context reliably between AI agents in a multi-agent pipeline.

---

## The Problem

One hallucinating agent silently corrupts the shared context, and every downstream agent inherits the damage. Existing orchestration tools treat the context window as a mutable blob with no version control.

## The Solution

Relay treats context like a ledger: append-only, signed at every step, and reversible.

---

## Features

### v0.1 (Core)
- **Context Broker** — Normalizes, timestamps, and cryptographically signs context envelopes
- **Handoff Validator** — Detects contradictions and triggers rollback on corruption
- **Snapshot Store** — Persists immutable checkpoints for rollback

### Post-v0.1
- **Slice Packager** — Cuts minimal context slices per agent (agents never see full history)
- **Agent Runner** — Framework-agnostic execution for any LLM provider
- **Token Budget Enforcement** — Pre-execution budget checking
- **Multi-Provider Support** — ProviderRegistry with fallback chain
- **Async Pipelines** — Async support for concurrent execution

---

## Installation

```bash
pip install relay
```

Or install from source:

```bash
git clone https://github.com/kridaydave/Relay.git
cd Relay
pip install -e .
```

---

## Quick Start

```python
from relay.pipeline import RelayPipeline

pipeline = RelayPipeline(
    signing_secret="your-secret-key",
    token_budget=8000
)

# First agent
result = pipeline.execute_step({"task": "analyze data"})
if isinstance(result, Success):
    envelope = result.value

# Second agent
result = pipeline.execute_step({"analysis": "completed"})
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     RelayPipeline                          │
├─────────┬─────────┬─────────┬─────────┬─────────────────────┤
│  Layer1 │  Layer2 │  Layer3 │  Layer4 │       Layer5        │
│ Context │  Slice  │  Agent  │ Validator│     Snapshot       │
│  Broker │ Packager│  Runner │          │       Store         │
└─────────┴─────────┴─────────┴─────────┴─────────────────────┘
```

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| 1 | Context Broker | Normalizes, timestamps, signs envelopes |
| 2 | Slice Packager | Cuts minimal context slices |
| 3 | Agent Runner | Executes agent calls |
| 4 | Handoff Validator | Detects contradictions, triggers rollback |
| 5 | Snapshot Store | Persists checkpoints |

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