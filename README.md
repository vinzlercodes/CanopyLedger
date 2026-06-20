# CanopyLedger

Open-source evidence-adjusted borrowing-base decisioning for coffee trade finance.

CanopyLedger models a fictional European green-coffee importer financed by a revolving secured facility. It converts immutable facility snapshots into reproducible collateral valuations, contractual borrowing-base assessments, independent internal risk capacity, and governed human decisions.

## Status

Early implementation. See the [master plan](CANOPYLEDGER_MASTER_PLAN.md), condensed
[implementation guide](MASTER_PLAN.md), and [progress tracker](PROGRESS.md).

## Development

Prerequisites: Python 3.12+, `uv`, PostgreSQL/PostGIS for integration tests.

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
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
