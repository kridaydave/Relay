# Technology Stack

**Analysis Date:** 2026-05-17

## Languages

**Primary:**
- Python 3.12+ (3.12 minimum, compatible with 3.13) — All source code in `src/relay/`
- Type annotations enforced via `mypy --strict` with zero `# type: ignore` suppressions

**Secondary:**
- YAML — CI workflow configuration (`.github/workflows/ci.yml`), pre-commit hooks (`.pre-commit-config.yaml`)
- Markdown — Documentation files in `docs/`, `README.md`, `AGENTS.md`

## Runtime

**Environment:**
- CPython 3.12+ (no external runtime dependency)
- No Docker, containerization, or orchestration tooling detected

**Package Manager:**
- pip (setuptools-based, `pyproject.toml` build system)
- Lockfile: Not detected (no `requirements.txt`, `Pipfile.lock`, or `poetry.lock`)
- Build backend: `setuptools>=61.0` with `[tool.setuptools.packages.find] where = ["src"]`

## Frameworks

**Core:**
- No web framework — this is a pure Python library, not a web application
- No ORM or database framework — persistence is filesystem-based (JSON snapshots)

**Testing:**
- pytest >=7.0 (from `[project.optional-dependencies] dev`)
  - Config: `pyproject.toml` `[tool.pytest.ini_options]`
  - Test paths: `tests/` (subdirectories: `unit/`, `integration/`)
  - Async support: `pytest-asyncio` with `asyncio_mode = "auto"`
  - Options: `-v --tb=short`
- Coverage: `pytest-cov` with branch coverage, 2 decimal precision, `[tool.coverage.run] source = ["."]`

**Build/Dev:**
- mypy — strict mode (`mypy.ini`), run via pre-commit and CI
  - Key settings: `strict = True`, `disallow_any_expr = True`, `ignore_missing_imports = False` (except tiktoken, httpx)
  - Per-module exceptions: `tests/*`, `relay.budget.token_counter`, `relay.runners.local_model`
- pre-commit — 3 local hooks: `mypy --strict src/`, `pytest tests/unit/`, `check_test_names.py`
- Scripts: `scripts/check_test_names.py` — enforces sentence-style test naming (Rule 7.1)

## Key Dependencies

**Critical (stdlib only — no core runtime dependencies):**
- `hashlib` — SHA-256 for manifest hashing (`src/relay/slicer/manifest.py`, `src/relay/core_pipeline.py`) and HMAC signing (`src/relay/envelope.py`)
- `hmac` — Envelope signing via `hmac.new` + `hmac.compare_digest` (`src/relay/envelope.py`)
- `json` — Snapshot persistence, envelope payload serialization
- `threading` — Pipeline lock (`src/relay/pipeline_state.py`), non-reentrant `threading.Lock`
- `asyncio` — Async adapter execution, parallel fork-join (`src/relay/runners/`, `src/relay/parallel/`)
- `uuid` — Pipeline ID generation (`src/relay/core_pipeline.py`), snapshot IDs (`src/relay/snapshot.py`)
- `datetime` / `time` — Timestamps, latency measurement
- `pathlib` / `os` — Filesystem snapshot storage (`src/relay/snapshot.py`)
- `re` — Pipeline ID and agent ID validation, snapshot ID pattern
- `logging` — Diagnostics (`src/relay/snapshot.py`, `src/relay/parallel/join.py`)
- `dataclasses` — All domain value types (`@dataclass(frozen=True)` for immutability)
- `contextlib` / `enum` / `inspect` / `typing` / `functools` — Python stdlib support

**Infrastructure (optional — lazy-imported):**
- `tiktoken` (optional) — Precise token counting via `cl100k_base` encoding (`relay.budget.token_counter`)
- `httpx` (optional) — HTTP client for OpenAI-compatible REST endpoints (`relay.runners.local_model`)
- `langchain-core>=0.1` (optional) — LangChain Runnable adapter (`relay.runners.langchain`)
- `crewai>=0.30` (optional) — CrewAI Agent adapter (`relay.runners.crewai`)
- `pyautogen>=0.2` (optional) — AutoGen AssistantAgent adapter (`relay.runners.autogen`)

## Configuration

**Environment:**
- No `.env` file detected (listed in `.gitignore`)
- Configuration is programmatic — all parameters passed to `CoreRelayPipeline.create()` constructor
- Key configurable parameters:
  - `signing_secret` — HMAC signing secret (must be ≥32 characters)
  - `token_budget` — Maximum token budget (default: 8000)
  - `storage_path` — Snapshot persistence directory (default: `./relay_data/snapshots`)
  - `token_counter` — Optional `TokenCounter` instance for budget enforcement
  - `slice_packer` — Optional `SlicePacker` for context slicing strategies
  - `registry` — Optional `AdapterRegistry` for agent runners

**Build:**
- `pyproject.toml` — Project metadata, dependencies, pytest config, coverage config
- `mypy.ini` — Strict typing configuration
- `.pre-commit-config.yaml` — Local quality gate hooks
- `.github/workflows/ci.yml` — CI pipeline

## Platform Requirements

**Development:**
- Python >=3.12
- pip
- Optional: `tiktoken`, `httpx`, `langchain-core`, `crewai`, `pyautogen` for adapter testing
- Git + pre-commit for local quality gates

**Production:**
- No production deployment target specified
- Distributed as pip package (`relay-middleware` on PyPI)
- Pure library — no server, no database, no cloud dependencies needed
- CI runs on `ubuntu-latest` with Python 3.12

---

*Stack analysis: 2026-05-17*
