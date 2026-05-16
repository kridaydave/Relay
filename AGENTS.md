# Relay — AGENTS.md

## Quick start

```bash
pip install -e .[dev]
python -m pre_commit install                  # enable local quality gates
python -m pre_commit run --all-files          # manually run all quality gates
pytest tests/unit -v                          # unit tests
python -m mypy --strict src/relay             # must pass with zero # type: ignore
```

## Architecture

- **Package source**: `src/relay/` (setuptools with `[tool.setuptools.packages.find] where = ["src"]`)
- **Layer dependency order** (lower never imports upper): `types.py` → `envelope.py` → `snapshot.py` → `validator.py` → `context_broker.py` → `budget/` + `slicer/` → `pipeline_state.py` → `pipeline_rollback.py` + `parallel/` → `core_pipeline.py`
- **Entrypoint**: `CoreRelayPipeline` in `core_pipeline.py` — orchestrates all components
- **Error handling**: `Result[T] = Success[T] | RollbackSuccess[T] | Failure` — no exceptions for operational errors
- **Rollback**: Returns `RollbackSuccess` (not `Success`). `unwrap()` raises on RollbackSuccess; `unwrap_or()` returns default on both Failure and RollbackSuccess; `map_result()` transforms RollbackSuccess.
- **Pipeline lock**: Non-reentrant `threading.Lock` held via `pipeline_state.transaction()` context manager. Never call `transaction()` inside another transaction.
- **AutoTokenCounter** is NOT exported from `relay.budget.__init__`. Import from `relay.budget.token_counter` directly.

## Code conventions

- **mypy --strict with zero suppressions** — no `# type: ignore`, no bare `Any` (Rule 2.1)
- **Every domain value type is `@dataclass(frozen=True)`** — use `dataclasses.replace()` or `with_*` methods for copies
- **Module docstrings** use three-line format: summary, `Owns:`, `Does NOT:` (Rule 8.3)
- **Test names are sentences**, e.g. `test_hard_cap_enforcer_blocks_call_when_projected_cost_exceeds_remaining_budget` (Rule 7.1)
- **Test doubles** live in `tests/conftest.py` and module-specific `conftest.py` files: `FixedCounter`, `FixedEmbeddingProvider`, `FixedAgentRunner`, `FixedForkRunner`. No network calls in unit tests. Test doubles must satisfy their Protocol (check with `isinstance(x, Protocol)`).
- **Every `Result`-returning function** needs tests for every distinct `Failure` code (Rule 7.5)
- **Commit format**: `type(scope): imperative sentence` — types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`
- **Signing secret** must be ≥32 characters (validated at `ContextBroker` construction)

## Key constraints

- `pipeline_id` validated against `^[a-zA-Z0-9_-]{1,128}$` before filesystem use (path traversal prevention)
- HMAC comparison always via `hmac.compare_digest`, never `==`
- Framework adapters (`langchain`, `crewai`, `autogen`, `httpx`) are **lazy-imported** — importing `relay.runners` does not require them
- Budget enforcement is advisory under concurrent load (lock released before `adapter.run()`)
- Existing full rulebook: `docs/Relay Coding Rules.md`

## Workflows

Use these superpowers skill workflows in sequence (process → implement → verify):

- **Feature work**: `brainstorming` → `writing-plans` → `test-driven-development` → `verification-before-completion`
- **Bug fix**: `systematic-debugging` → `test-driven-development` → `verification-before-completion`
- **Multi-step parallel work**: `brainstorming` → `writing-plans` → `dispatching-parallel-agents` → `verification-before-completion`
- **Refactoring**: `request-refactor-plan` → `using-git-worktrees` → incremental commits → `verification-before-completion`
- **Design prototype**: `brainstorming` → `huashu-design` → `requesting-code-review`
