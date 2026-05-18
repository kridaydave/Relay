---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "arch"
---

# STRUCTURE.md — Directory Layout

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## Top-Level Structure

```
Relay/
├── src/relay/                    # Package source (setuptools find: where=["src"])
├── tests/                        # Test suite
├── docs/                         # Documentation, design docs, website
├── scripts/                      # Quality gate scripts
├── .github/workflows/            # CI configuration
├── .planning/                    # GSD planning artifacts
├── dist/                         # Build artifacts (wheels, tarballs)
├── pyproject.toml                # Project configuration
├── mypy.ini                      # Type checker configuration
├── .pre-commit-config.yaml       # Pre-commit hooks
├── README.md                     # Project readme
├── AGENTS.md                     # Agent/developer instructions
├── LICENSE                       # MIT License
└── Internal-changelog.md         # Internal change log
```

## Source Code Structure (`src/relay/`)

```
src/relay/
├── __init__.py                   # Public API exports (23 symbols)
├── types.py                      # Result types, ErrorCode, SigningKey, version
├── envelope.py                   # ContextEnvelope data model, signing, factories
├── context_broker.py             # Envelope lifecycle, secret management
├── core_pipeline.py              # Main orchestrator (967 lines)
├── pipeline_state.py             # Thread-safe state manager with lock
├── pipeline_rollback.py          # Rollback handler
├── validator.py                  # HandoffValidator, contradiction detection
├── snapshot.py                   # LocalFileSnapshotStore (filesystem persistence)
├── snapshot_in_memory.py         # InMemorySnapshotStore (testing/dev)
├── snapshot_protocol.py          # SnapshotStore Protocol, snapshot ID patterns
├── py.typed                      # PEP 561 marker for type hints
│
├── budget/
│   ├── __init__.py               # Exports: HardCapEnforcer, TokenCounter
│   ├── enforcer.py               # HardCapEnforcer (budget check)
│   └── token_counter.py          # TokenCounter protocol, HeuristicCounter, TiktokenCounter
│
├── audit/
│   ├── __init__.py               # Exports: all event types, AuditSink, JsonLogSink, PayloadRedactor
│   ├── events.py                 # 18 typed audit event dataclasses
│   ├── sink.py                   # AuditSink Protocol, JsonLogSink implementation
│   └── redactor.py               # PayloadRedactor (sensitive field redaction)
│
├── slicer/
│   ├── __init__.py               # Exports: AgentManifest, SlicePackers, EmbeddingProvider
│   ├── manifest.py               # AgentManifest dataclass (reads/writes/max_tokens)
│   ├── packers.py                # RecencySlicePacker, RelevanceSlicePacker, StructuralSlicePacker
│   └── providers.py              # SlicePacker Protocol, EmbeddingProvider Protocol
│
├── parallel/
│   ├── __init__.py               # Exports: JoinStrategy, ForkSpec, ForkResult, run_single_fork
│   ├── types.py                  # ForkSpec, ForkResult, JoinStrategy enum, agent_output_to_payload
│   ├── fork_runner.py            # run_single_fork async function
│   └── join.py                   # apply_join_strategy (FIRST_WINS, UNION, VOTE)
│
└── runners/
    ├── __init__.py               # Lazy imports for framework adapters
    ├── protocol.py               # AgentRunner Protocol, AgentOutput, ContextSlice
    ├── registry.py               # AdapterRegistry (register/get/list)
    ├── raw_sdk.py                # RawSDKAdapter (stdlib + httpx only)
    ├── langchain.py              # LangChainAdapter (lazy import)
    ├── crewai.py                 # CrewAIAdapter (lazy import)
    ├── autogen.py                # AutoGenAdapter (lazy import)
    └── local_model.py            # LocalModelAdapter (lazy import)
```

## Test Structure (`tests/`)

```
tests/
├── __init__.py
├── conftest.py                   # Shared test doubles: FixedCounter, FixedAuditSink, FixedEmbeddingProvider
│
├── unit/
│   ├── __init__.py
│   ├── test_types.py
│   ├── test_envelope.py
│   ├── test_context_broker.py
│   ├── test_validator.py
│   ├── test_pipeline.py
│   ├── test_pipeline_state.py
│   ├── test_pipeline_rollback.py
│   ├── test_snapshot.py
│   ├── test_snapshot_in_memory.py
│   ├── test_budget.py
│   ├── test_slicer.py
│   ├── test_audit_events.py
│   ├── test_audit_sink.py
│   ├── test_audit_redactor.py
│   │
│   ├── test_parallel/
│   │   ├── __init__.py
│   │   ├── conftest.py           # Parallel-specific fixtures
│   │   ├── test_fork_runner.py
│   │   ├── test_join.py
│   │   └── test_types.py
│   │
│   └── test_runners/
│       ├── __init__.py
│       ├── conftest.py           # Runner-specific fixtures (FixedAgentRunner, FixedForkRunner)
│       ├── test_protocol.py
│       ├── test_registry.py
│       ├── test_raw_sdk.py
│       ├── test_langchain.py
│       ├── test_crewai.py
│       ├── test_autogen.py
│       └── test_local_model.py
│
└── integration/
    ├── __init__.py
    ├── test_pipeline_integration.py
    ├── test_parallel_pipeline.py
    └── test_runners_integration.py
```

## Key File Locations

| Purpose | Path |
|---------|------|
| Package entry point | `src/relay/__init__.py` |
| Main orchestrator | `src/relay/core_pipeline.py` |
| Result types | `src/relay/types.py` |
| Envelope model | `src/relay/envelope.py` |
| Project config | `pyproject.toml` |
| Type check config | `mypy.ini` |
| CI pipeline | `.github/workflows/ci.yml` |
| Developer guide | `AGENTS.md` |
| Coding rules | `docs/Relay Coding Rules.md` |
| Design document | `docs/Relay Design Document.md` |

## Naming Conventions

- **Modules**: `snake_case.py` (e.g., `pipeline_state.py`, `token_counter.py`)
- **Classes**: `PascalCase` (e.g., `CoreRelayPipeline`, `HardCapEnforcer`, `ContextEnvelope`)
- **Protocols**: `PascalCase` ending in `Protocol` or domain name (e.g., `TokenCounter`, `SnapshotStore`, `AgentRunner`)
- **Functions**: `snake_case` (e.g., `create_context_broker`, `validate_manifest_boundaries`)
- **Test files**: `test_<module>.py` (e.g., `test_pipeline.py`, `test_envelope.py`)
- **Test functions**: full sentences in `snake_case` (Rule 7.1: `test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget`)
- **Error codes**: `UPPER_SNAKE_CASE` (e.g., `INVALID_PIPELINE_ID`, `BUDGET_EXCEEDED`)
- **Private modules**: prefixed with `_` (e.g., `_Encoding` in `token_counter.py`)

## Package Layout Pattern

- `src/relay/` — setuptools with `where = ["src"]`
- `py.typed` marker present for PEP 561 compatibility
- `__init__.py` exports all public symbols via `__all__`
- Internal modules not listed in `__all__` are private
