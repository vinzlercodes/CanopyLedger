# CanopyLedger

Open-source borrowing-base and decision-governance reference system for coffee trade
finance.

CanopyLedger models a synthetic green-coffee borrower financed by a secured revolving
facility. It freezes mutable facility data into immutable snapshots, runs deterministic
collateral calculations, publishes replayable outputs, and keeps human approval outside
automated engines.

## Current Build

The public reference build includes:

- Canonical JSON, decimal, timestamp, and digest contracts with Python and TypeScript parity.
- Durable facility and snapshot APIs with idempotency, ETags, Problem Details, and bearer demo auth.
- PostgreSQL schema for immutable bundles, snapshots, inputs, pipeline runs, stage outputs, outbox,
  inbox, and audit records.
- Serializable snapshot freeze and fenced pipeline publication with lease epochs.
- Replay package verification for published immutable outputs.
- Initial domain pipeline for inventory, receivables, market snapshots, reserves, CBB, and
  contractual availability.
- Deterministic CBB certificate output with duplicate-collateral prevention and reason codes.
- Demo CLI/API surface plus generated TypeScript API client.

Current completed milestones: M0 normative foundation, M1A integrity kernel, M1B initial domain
pipeline. Next implementation area: evidence controls.

## Install

Prerequisites:

- Python 3.12+
- `uv`
- Node.js/npm for TypeScript checks
- PostgreSQL 17 for integration tests

```bash
uv sync --extra dev
npm --prefix typescript install
```

## Useful Commands

Full local non-database gate:

```bash
uv run ruff check .
uv run mypy
uv run python scripts/export_openapi.py --check
uv run pytest -q
npm --prefix typescript run client:check
npm --prefix typescript run typecheck
npm --prefix typescript test
uv build
```

PostgreSQL gate against a disposable database:

```bash
export DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run alembic check
uv run pytest -m postgres -q
```

Generate or check API artifacts:

```bash
uv run python scripts/export_openapi.py --check
npm --prefix typescript run client:check
```

## API

OpenAPI v1 artifact:

```text
docs/api/openapi-v1.json
```

Main routes:

- `GET /health`
- `POST /api/v1/facilities`
- `GET /api/v1/facilities/{facility_id}`
- `PATCH /api/v1/facilities/{facility_id}`
- `POST /api/v1/facilities/{facility_id}/snapshots`
- `GET /api/v1/snapshots/{snapshot_id}/manifest`
- `POST /api/v1/cbb-certificates/demo`
- `POST /api/v1/m1b/pipeline/demo`

Demo auth uses bearer token:

```text
Authorization: Bearer analyst-demo-token
```

## CLI

Replay verifier:

```bash
uv run canopyledger-replay replay-package.json \
  --environment '{"git_commit":"...","python":"3.12","timezone":"UTC"}'
```

CBB demo certificate:

```bash
uv run canopyledger-cbb-demo input.json --output certificate.json
```

## Repository Layout

```text
src/canopyledger/
  api/              FastAPI app and typed response models
  application/      use-case services and command models
  borrowing_base/   CBB calculations and certificate builder
  collateral/       inventory valuation and eligibility
  domain/           Money, IDs, and unit normalization
  initial_domain/   M1B pure pipeline and PostgreSQL publication runner
  integrity/        canonicalization, idempotency, snapshots, replay
  market/           market snapshot resource
  persistence/      SQLAlchemy/PostgreSQL adapter and schema
  receivables/      receivable valuation and eligibility
```

Internal planning docs and Codex working files are ignored and kept local. Public docs stay limited
to README, contribution/security files, license, and generated OpenAPI.

## Boundaries

Reference implementation only. Not a production banking system, legal-compliance service, trading
platform, payment system, market-data terminal, or autonomous credit engine. Synthetic data only.

## License

Apache-2.0.
