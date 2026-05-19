# Technology Stack — v0.5 & v0.6 Additions

**Project:** Relay
**Researched:** 2026-05-17

## Recommended Stack

### Core (unchanged from v0.4)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | >=3.12 | Runtime | Already established. Static typing via `mypy --strict`. |
| setuptools | >=61.0 | Build | Already established. `[tool.setuptools.packages.find] where = ["src"]`. |

### New Optional Dependencies (v0.5)
| Technology | Version | Purpose | Extra Name | Why |
|------------|---------|---------|------------|-----|
| `opentelemetry-api` | >=1.25 | OTEL tracer API (NOT SDK) | `[otel]` | Smallest OTEL dependency — only the API types. Users bring their own SDK + exporter. No transitive dep on gRPC/protobuf. |
| `click` | >=8.1 | CLI framework | `[cli]` | Standard Python CLI library. Arguable vs `argparse` (stdlib). Click wins for subcommand support (`@click.group`) and auto-help. LOW confidence — argparse works too. |

### New Optional Dependencies (v0.6)
| Technology | Version | Purpose | Extra Name | Why |
|------------|---------|---------|------------|-----|
| `redis` | >=5.0 | Redis snapshot backend | `[redis]` | Sync Redis client. `redis-py` is the standard. `HSET` + JSON serialization. |
| `psycopg` | >=3.1 | Postgres snapshot backend | `[postgres]` | Modern async/sync Postgres driver. Uses `JSONB` column. Schema managed by Relay. |
| `boto3` | >=1.34 | S3 snapshot backend | `[s3]` | AWS SDK for Python. Gzipped JSON objects. |

### Development / Testing (v0.5)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `pytest-benchmark` | >=4.0 | Microbenchmarking | Integrates with existing pytest setup. Provides CI comparison, statistical analysis, and regression detection. |
| `iniconfig` | (transitive) | pytest config | Already a transitive dependency of pytest. No new surface area. |

### Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| OTEL dependency | `opentelemetry-api` only | `opentelemetry-sdk` | SDK pulls in gRPC, protobuf, exporters. Users who don't export to OTLP shouldn't pay that cost. We use the API to create spans only. |
| OTEL integration | Lazy-imported subpackage | Separate `relay-otel` package on PyPI | Premature for v0.5. Keep it in-tree until the API stabilizes. Can extract later. |
| CLI framework | `click` | `argparse` (stdlib) | Both work. Click reduces boilerplate for subcommands. If zero-dependency CLI is preferred, argparse is fine. |
| CLI argument parsing | `argparse` (stdlib) | `click` | Using argparse avoids adding any dependency for the CLI. The CLI has only 3 subcommands — argparse handles this trivially. **argparse wins** for zero-dependency CLI. |
| Pytest plugin approach | In-tree `pytest11` entry point | Separate `relay-pytest` PyPI package | Unnecessary indirection for v0.5. Keep in-tree until ecosystem maturity demands separation. |
| Benchmarking | `pytest-benchmark` | `airspeed-velocity` (asv) | asv is more sophisticated (history tracking, environment isolation) but overkill for Relay's current size. pytest-benchmark integrates directly with existing tests. |
| Snapshot backend storage | Sync Protocol | `AsyncSnapshotStore` Protocol | Async adds complexity without measurable benefit for snapshot I/O (which happens under a sync lock). Sync Redis/Postgres/S3 clients are mature. |

## Installation (New Extras)

```toml
# pyproject.toml additions

[project.optional-dependencies]
# ... existing extras ...
otel = ["opentelemetry-api>=1.25"]
cli = ["click>=8.1"]
test = ["pytest>=8.0"]                      # for the pytest plugin
redis = ["redis>=5.0"]
postgres = ["psycopg>=3.1"]
s3 = ["boto3>=1.34"]
all = [
    # ... existing ...
    "opentelemetry-api>=1.25",
    "click>=8.1",
    "redis>=5.0",
    "psycopg>=3.1",
    "boto3>=1.34",
]

[project.entry-points.pytest11]
relay = "relay.pytest_plugin"

[project.scripts]
relay = "relay.cli:main"
```

## Source Confidence

- **otl API**: HIGH — official OpenTelemetry Python API package, 1.41.1 released April 2026. Docs at opentelemetry.io/docs/languages/python/.
- **click**: HIGH — dominant Python CLI library, actively maintained.
- **argparse**: HIGH — stdlib, zero-dependency alternative.
- **redis-py**: HIGH — official Python client for Redis.
- **psycopg3**: HIGH — modern Postgres driver, psycopg >=3.1.
- **boto3**: HIGH — official AWS SDK for Python.
- **pytest-benchmark**: HIGH — mature pytest plugin, 5M+ weekly downloads.
