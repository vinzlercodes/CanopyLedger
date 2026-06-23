# CanopyLedger

Open-source evidence-adjusted borrowing-base decisioning for coffee trade finance.

CanopyLedger models a fictional European green-coffee importer financed by a revolving secured facility. It converts immutable facility snapshots into reproducible collateral valuations, contractual borrowing-base assessments, independent internal risk capacity, and governed human decisions.

## Status

M1A integrity kernel complete; M1B domain pipeline is in progress. See the
[master plan](CANOPYLEDGER_MASTER_PLAN.md), condensed [implementation guide](MASTER_PLAN.md), and
[progress tracker](PROGRESS.md).

## Development

Prerequisites: Python 3.12+, `uv`, PostgreSQL/PostGIS for integration tests.

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy
uv run python scripts/export_openapi.py --check
uv run pytest -m "not postgres" -q
npm --prefix typescript test
npm --prefix typescript run typecheck
npm --prefix typescript run client:check
uv build
```

PostgreSQL M1A gate against a disposable PostgreSQL 17 database:

```bash
export DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run alembic check
uv run pytest -m postgres -q
```

Generated OpenAPI and TypeScript client drift checks:

```bash
uv run python scripts/export_openapi.py --check
npm --prefix typescript run client:check
```

Replay CLI:

```bash
canopyledger-replay replay-package.json --environment '{"git_commit":"...","python":"3.12","timezone":"UTC"}'
```

System-Python environment created for local tooling:

```bash
source .venv-system/bin/activate
python -m pytest -q
ruff check .
mypy
```

## Boundaries

Reference implementation only. Not a production banking system, legal-compliance service, trading platform, or autonomous credit engine. Synthetic data only.

## License

Apache-2.0.
