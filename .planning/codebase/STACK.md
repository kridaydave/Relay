---
last_mapped_date: "2026-05-18"
last_mapped_commit: "N/A"
focus: "tech"
---

# STACK.md — Technology Stack

> **Last updated:** 2026-05-18
> **Scope:** Full repo

## Languages & Runtime

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | ≥3.12 (tested on 3.12, 3.13) |
| Type hints | PEP 695 `type` syntax | Python 3.12+ (`type Result[T] = ...`) |
| Package manager | pip / setuptools | setuptools ≥61.0 |

## Core Dependencies (Zero Runtime Deps)

The core package has **zero required runtime dependencies**. All external libraries are optional extras:

```toml
# pyproject.toml — [project]
dependencies = []
```

This is a deliberate design choice: Relay is a middleware library that doesn't force any specific LLM framework on consumers.

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `dev` | `pytest>=8.0,<9`, `pytest-asyncio>=0.23,<0.25`, `anyio>=4.0,<5`, `mypy>=1.10,<2`, `coverage>=7.0,<8` | Development tooling |
| `tiktoken` | `tiktoken` | Accurate BPE token counting (cl100k_base) |
| `langchain` | `langchain-core>=0.1` | LangChain adapter |
| `crewai` | `crewai>=0.30` | CrewAI adapter |
| `autogen` | `pyautogen>=0.2` | AutoGen adapter |
| `local` | `httpx>=0.27` | Local model runner (HTTP-based) |
| `all` | All of the above | Full feature set |

Install: `pip install relay-middleware[all]`

## Development Tooling

| Tool | Version Constraint | Config Location | Purpose |
|------|-------------------|-----------------|---------|
| pytest | ≥8.0, <9 | `pyproject.toml:[tool.pytest.ini_options]` | Unit + integration tests |
| pytest-asyncio | ≥0.23, <0.25 | `pyproject.toml` | Async test support (`asyncio_mode = "auto"`) |
| mypy | ≥1.10, <2 | `mypy.ini` | Static type checking (`--strict`) |
| coverage | ≥7.0, <8 | `pyproject.toml:[tool.coverage]` | Branch coverage (≥80% threshold) |
| pre-commit | — | `.pre-commit-config.yaml` | Quality gate hooks |

## Type Checking

- **Strictness:** `mypy --strict` with **zero `# type: ignore` suppressions** (enforced in CI)
- **Coverage:** Both `src/` and `tests/` are type-checked
- **Config file:** `mypy.ini` (separate from pyproject.toml)
- **Marker:** `src/relay/py.typed` present for PEP 561 compatibility
- **Version consistency check:** CI verifies `pyproject.toml` version matches `__version__` in `src/relay/types.py`

## Build System

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Package name: `relay-middleware` (import as `relay`)
Current version: `0.5.1`

## CI Pipeline (`.github/workflows/ci.yml`)

Runs on push/PR to `main`, matrix: Python 3.12 + 3.13:

1. Install `.[dev]`
2. Check `py.typed` marker exists
3. `mypy --strict src/`
4. `mypy --strict tests/`
5. No `assert` statements in production code
6. Version consistency (pyproject.toml vs types.py)
7. Test naming convention check (`scripts/check_test_names.py`)
8. `coverage run -m pytest tests/ -v` → `coverage report --fail-under=80`
9. No `# type: ignore` in source
10. Layer violation check (`scripts/check_layer_violations.py`)
11. Private API import check (`scripts/check_no_private_api_imports.py --warn`)
12. Failure code coverage check (`scripts/check_failure_coverage.py`)

## Python Standard Library Usage

Heavy use of stdlib modules:
- `dataclasses` — all domain value types are `@dataclass(frozen=True)`
- `typing` — `Protocol`, `TypeVar`, `Generic`, `runtime_checkable`, `cast`
- `enum` — `ErrorCode` enum for typed error codes
- `hmac` + `hashlib` — HMAC-SHA256 signing (`hmac.compare_digest` for constant-time comparison)
- `json` — canonical serialization for signatures and snapshots
- `uuid` — pipeline IDs, snapshot IDs, nonces
- `datetime` — UTC timestamps with `timezone.utc`
- `threading` — `Lock` for pipeline state (non-reentrant)
- `asyncio` — `asyncio.gather` for parallel fork execution
- `pathlib` — filesystem paths for snapshot store
- `logging` — structured logging for audit events
- `stat` / `os` — symlink detection, atomic file writes (`O_NOFOLLOW`, `O_EXCL`)
