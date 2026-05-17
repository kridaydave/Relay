# Codebase Structure

**Analysis Date:** 2026-05-17

## Directory Layout

```
Relay/
├── .claude/                        # Claude Code configuration
│   └── settings.local.json
├── .github/
│   └── workflows/                  # CI workflow definitions
├── .planning/
│   └── codebase/                   # Codebase mapping documents (this file + STACK.md, ARCHITECTURE.md, etc.)
├── docs/                           # Project documentation
│   ├── Audits/
│   ├── GSD/
│   ├── Images/
│   ├── superpowers/
│   ├── untracked/
│   ├── codename.md
│   ├── Relay Coding Rules.md
│   ├── Relay Design Document.md    # Full architectural design document (434 lines)
│   └── success.md
├── relay_data/                     # Runtime data directory (snapshot storage, gitignored)
├── scripts/
│   └── check_test_names.py         # Pre-commit hook: enforces test naming convention
├── src/
│   └── relay/                      # Package source (setuptools `where = ["src"]`)
│       ├── __init__.py             # Public API exports (__all__ list)
│       ├── budget/                 # Token budget enforcement module
│       ├── context_broker.py       # Envelope lifecycle management
│       ├── core_pipeline.py        # Central orchestrator (663 lines)
│       ├── envelope.py             # ContextEnvelope data model + HMAC signing
│       ├── parallel/               # Parallel fork-join execution
│       ├── pipeline_rollback.py    # Snapshot-based rollback restoration
│       ├── pipeline_state.py       # Thread-safe state management
│       ├── py.typed                # PEP 561 type information marker
│       ├── runners/                # Universal adapter layer
│       ├── slicer/                 # Context slicing strategies
│       ├── snapshot.py             # Immutable JSON checkpoint persistence
│       ├── types.py                # Core types: Result, Success, Failure, ErrorCode
│       └── validator.py            # Handoff validation + contradiction detection
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared test doubles (FixedCounter, FixedEmbeddingProvider)
│   ├── integration/
│   │   ├── test_parallel_pipeline.py
│   │   ├── test_pipeline_integration.py
│   │   └── test_runners_integration.py
│   └── unit/
│       ├── conftest.py             # (uses tests/conftest.py)
│       ├── test_budget.py
│       ├── test_context_broker.py
│       ├── test_envelope.py
│       ├── test_parallel/          # Parallel execution tests
│       │   ├── conftest.py         # FixedForkRunner, make_fork_spec, etc.
│       │   ├── test_fork_runner.py
│       │   ├── test_join.py
│       │   └── test_types.py
│       ├── test_pipeline.py        # Main pipeline orchestration tests (864 lines)
│       ├── test_pipeline_rollback.py
│       ├── test_pipeline_state.py
│       ├── test_runners/           # Adapter layer tests
│       │   ├── conftest.py         # FixedAgentRunner, make_test_slice, etc.
│       │   ├── test_autogen.py
│       │   ├── test_crewai.py
│       │   ├── test_langchain.py
│       │   ├── test_local_model.py
│       │   ├── test_protocol.py
│       │   ├── test_raw_sdk.py
│       │   └── test_registry.py
│       ├── test_slicer.py
│       ├── test_snapshot.py
│       ├── test_types.py
│       └── test_validator.py
├── AGENTS.md                       # Agent instructions for development
├── CHANGELOG.md
├── LICENSE                         # MIT License
├── mypy.ini                        # mypy --strict configuration
├── pre-commit-config.yaml          # Pre-commit hooks (mypy, pytest-unit, check-test-names)
├── pyproject.toml                  # Project metadata, dependencies, pytest configuration
└── README.md
```

## Directory Purposes

**`src/relay/`:**
- Purpose: Core package source code — all library logic
- Contains: Python modules organized by layer (budget, runners, slicer, parallel, plus top-level modules)
- Key files: `core_pipeline.py` (orchestrator), `types.py` (core types), `envelope.py` (data model + signing)

**`src/relay/budget/`:**
- Purpose: Token counting and budget enforcement
- Contains: `TokenCounter` protocol, `HeuristicCounter`/`TiktokenCounter` implementations, `HardCapEnforcer`
- Key files: `enforcer.py` (41 lines), `token_counter.py` (85 lines)
- Note: `AutoTokenCounter` is NOT exported from `budget/__init__.py` — import from `relay.budget.token_counter` directly

**`src/relay/runners/`:**
- Purpose: Framework-agnostic adapter layer — implements AgentRunner Protocol for 5 backends
- Contains: `AgentRunner` Protocol, `AgentOutput`, `ContextSlice`, `AdapterRegistry`, 5 adapter implementations
- Lazy imports: `LangChainAdapter`, `CrewAIAdapter`, `AutoGenAdapter`, `LocalModelAdapter` auto-imported via `__getattr__` in `__init__.py`

**`src/relay/slicer/`:**
- Purpose: Context slicing strategies and agent manifest definition
- Contains: `AgentManifest` (frozen dataclass), `SlicePacker` Protocol, `EmbeddingProvider` Protocol, 3 packer implementations
- Key files: `manifest.py` (57 lines), `packers.py` (160 lines), `providers.py` (46 lines)

**`src/relay/parallel/`:**
- Purpose: Parallel fork-join execution (v0.4)
- Contains: `ForkSpec`, `ForkResult`, `JoinStrategy` (UNION/VOTE/FIRST_WINS), fork runner, join strategies
- Key files: `fork_runner.py` (123 lines), `join.py` (178 lines), `types.py` (72 lines)

**`tests/unit/`:**
- Purpose: Unit tests — no network calls, no external dependencies
- Contains: One test file per source module, test doubles in module-specific `conftest.py`
- Key files: `test_pipeline.py` (864 lines), `test_types.py` (197 lines)

**`tests/integration/`:**
- Purpose: Integration tests with realistic adapter configurations
- Contains: Pipeline integration, parallel pipeline, adapter runner integration tests

## Key File Locations

**Entry Points:**
- `src/relay/__init__.py`: Public API surface — exports all 18 public names
- `src/relay/core_pipeline.py:48`: `CoreRelayPipeline` — main orchestrator class
- `src/relay/core_pipeline.py:74`: `CoreRelayPipeline.create()` — factory with validation

**Configuration:**
- `pyproject.toml`: Project metadata, dependencies, pytest config, setuptools config
- `mypy.ini`: mypy --strict configuration with per-module overrides
- `.pre-commit-config.yaml`: 3 hooks: mypy, pytest-unit, check-test-names

**Core Logic:**
- `src/relay/types.py`: `Result[T]`, `Success[T]`, `Failure`, `RollbackSuccess[T]`, `ErrorCode`, `JSONDict`, helper functions
- `src/relay/envelope.py`: `ContextEnvelope`, `create_initial_envelope()`, `create_next_envelope()`, `compute_signature()`, `verify_signature()`, `estimate_tokens()`
- `src/relay/context_broker.py`: `ContextBroker`, `create_context_broker()` factory
- `src/relay/validator.py`: `HandoffValidator`, `ValidationResult`, `validate_manifest_boundaries()`
- `src/relay/snapshot.py`: `SnapshotStore` with `save_snapshot()`, `load_snapshot()`, `list_snapshots()`
- `src/relay/pipeline_state.py`: `PipelineState` with non-reentrant lock `transaction()`
- `src/relay/pipeline_rollback.py`: `RollbackHandler.restore_to_previous()`

**Testing:**
- `tests/conftest.py`: `FixedCounter`, `FixedEmbeddingProvider` — shared test doubles
- `tests/unit/test_parallel/conftest.py`: `FixedForkRunner`, `make_fork_spec()`, `make_passing_fork_result()`, `make_failing_fork_result()`
- `tests/unit/test_runners/conftest.py`: `FixedAgentRunner`, `make_test_slice()`, `make_test_manifest()`

**Scripts:**
- `scripts/check_test_names.py`: Enforces `test_*` function naming convention in pre-commit hook

## Naming Conventions

**Files:**
- Source modules: `snake_case.py` (e.g., `context_broker.py`, `pipeline_state.py`, `token_counter.py`)
- Test files: `test_{module}.py` (e.g., `test_pipeline.py`, `test_context_broker.py`)
- Config files: `pyproject.toml`, `mypy.ini`, `.pre-commit-config.yaml`, `AGENTS.md`

**Functions:**
- All functions: `snake_case` (e.g., `create_initial_envelope`, `compute_signature`, `validate_manifest_boundaries`)
- Private/helper: `_leading_underscore` (e.g., `_check_budget`, `_apply_manifest`, `_sign_envelope`)
- Test functions: `snake_case` starting with `test_` (enforced by pre-commit hook `check_test_names.py`)
- Test names are sentences: `test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget`

**Variables:**
- All variables: `snake_case` (e.g., `pipeline_id`, `signing_secret`, `token_budget_used`)
- Private instance attributes: `_leading_underscore` (e.g., `_state`, `_context_broker`, `_enforcer`)
- Type variables: Uppercase single letters (e.g., `T`, `U`)

**Types:**
- Classes: `PascalCase` (e.g., `CoreRelayPipeline`, `ContextEnvelope`, `HandoffValidator`, `HardCapEnforcer`)
- Frozen dataclasses used for all domain value types: `@dataclass(frozen=True)` (e.g., `ContextEnvelope`, `AgentManifest`, `ForkSpec`, `ValidationResult`)
- Protocols: `PascalCase` (e.g., `AgentRunner`, `TokenCounter`, `EmbeddingProvider`, `SlicePacker`)
- Enums: `PascalCase` (e.g., `ErrorCode`, `JoinStrategy`)
- Type aliases: `PascalCase` (e.g., `Result[T]`, `JSONDict`)

**Directories:**
- Source: `src/relay/`
- Subpackages: `snake_case` (e.g., `budget/`, `runners/`, `slicer/`, `parallel/`)
- Tests: `unit/`, `integration/`, with subdirectories matching source structure: `test_parallel/`, `test_runners/`

## Where to Add New Code

**New Feature (Core Logic):**
- Primary code: Add a new module in `src/relay/` for new functionality, or extend existing module
- If adding a new subpackage (like a new `budget/` strategy), create `src/relay/{module_name}/` with `__init__.py`
- Tests: `tests/unit/test_{module_name}.py` for unit tests; `tests/integration/` for integration tests
- Exports: Add new public names to `src/relay/__init__.py` `__all__` list

**New Adapter (AgentRunner):**
- Implementation: `src/relay/runners/{name}.py`
- Must implement `AgentRunner` protocol (`async def run(slice_, manifest) -> AgentOutput`)
- Registration: Add to `_LAZY_ADAPTERS` dict in `src/relay/runners/__init__.py` and to `__all__`
- Tests: `tests/unit/test_runners/test_{name}.py`

**New Slice Packer:**
- Implementation: `src/relay/slicer/packers.py` (or new file if complex)
- Must implement `SlicePacker` protocol (`def pack(payload, manifest) -> Result[JSONDict]`)
- Tests: `tests/unit/test_slicer.py`

**New Join Strategy:**
- Implementation: `src/relay/parallel/join.py` — add new `_apply_{name}()` function
- Registration: Add to `JoinStrategy` enum in `src/relay/parallel/types.py`
- Tests: `tests/unit/test_parallel/test_join.py`

**Utilities:**
- Shared helpers: Add to existing module if closely related, or `src/relay/` if cross-cutting (e.g., new type definitions go in `types.py`, new envelope utilities go in `envelope.py`)

## Special Directories

**`relay_data/`:**
- Purpose: Runtime data directory for snapshot persistence (default: `./relay_data/snapshots`)
- Generated: Yes — created at runtime by `SnapshotStore`
- Committed: No — gitignored

**`dist/`:**
- Purpose: Build artifacts from `pip install` / `python -m build`
- Generated: Yes
- Committed: No — gitignored

**`.mypy_cache/`, `.pytest_cache/`, `__pycache__/`:**
- Purpose: Cached type-checking, test, and bytecode data
- Generated: Yes — created by mypy, pytest, Python runtime
- Committed: No — gitignored

**`src/relay_middleware.egg-info/`:**
- Purpose: Setuptools egg-info metadata for development install
- Generated: Yes — created by `pip install -e .`
- Committed: No — gitignored

---

*Structure analysis: 2026-05-17*
