# CanopyLedger

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

CanopyLedger is an open-source reference implementation for governed, coffee-backed trade-finance decisions. It turns synthetic facility, collateral, evidence, market, hedge, and scenario inputs into reproducible calculations and keeps final lending decisions with authorized humans.

It is deliberately not a core-banking system, a trading platform, a market-data terminal, a legal-compliance service, or an autonomous credit engine. It is a learning and integration reference; do not use it with real borrower, farmer, trading, market, or credential data.

## Project status

The implemented reference scope includes:

- immutable facility snapshots, versioned bundles, canonical JSON/decimal/timestamp handling, idempotency, audit events, and replay-oriented output digests;
- deterministic inventory and receivables valuation, eligibility, reserves, contractual borrowing base (CBB), and contractual availability;
- evidence documents, candidate facts, human approval/rejection, corrections, receipt/ownership controls, and reconciliation;
- hedge and liquidity assessment, including KC/AC contract separation, futures/options, variation-margin stress, and liquidity coverage;
- scenario capacity and an Internal Risk Capacity (IRC) that stays distinct from CBB;
- deterministic climate/EUDR evidence readiness, PostGIS WGS84 traceability geometry, origin concentration, climate scenarios, and financed-emissions methodology/data-quality lineage;
- recommendations, approval requests, final decisions, overrides, separation of duties, expiry, and audit timeline;
- a Next.js presentation layer with Cockpit, Collateral, Evidence, Hedge Lab, Scenario Lab, Climate & Traceability, Approval, and Reports workspaces;
- canonical report-model JSON with deterministic HTML/PDF renderings, pinned renderer/font metadata,
  current-versus-historical package designation, and immutable report artifacts.

Climate/EUDR output describes frozen evidence readiness; it is not a legal-compliance or
deforestation-free certification. The reference `make demo` command creates an approved synthetic
decision package and prints its report-model and artifact digests.

For an end-to-end walkthrough of the runnable scope, see [DEMO.md](DEMO.md).

## Design commitments

CanopyLedger is built around a few non-negotiable boundaries:

- Mutable working data becomes an immutable, content-addressed snapshot before authoritative calculation.
- Every authoritative output retains snapshot, bundle, input/output digest, timestamp, and reason-code lineage.
- Money and other authoritative decimals are serialized as strings; browser code formats them but never recalculates them.
- CBB is the contractual collateral result. IRC is a separate internal-risk result. Neither is silently substituted for the other.
- A recommendation is advisory. A final decision requires an authorized, independent human actor.
- Corrections and overrides preserve history rather than rewriting immutable records.
- The web app is a contract consumer: FastAPI authorizes requests and Python owns authoritative calculation.

## Architecture

```text
Next.js web app
  Cockpit · Collateral · Evidence · Hedge Lab · Scenario Lab · Approval
                          |
                     HTTPS / JSON
                          |
FastAPI API ── immutable snapshots, evidence, governance, typed read models
                          |
          PostgreSQL adapters / in-memory local adapters
                          |
deterministic Python calculations ── CBB · hedge/liquidity · scenario/IRC
```

The local FastAPI factory uses in-memory adapters for fast experimentation. PostgreSQL-backed adapters, Alembic migrations, and integration tests exercise durable behavior separately.

## Quick start

Prerequisites:

- Python 3.12–3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- PostgreSQL 17 with PostGIS only for PostgreSQL integration tests

Install the Python and JavaScript dependencies:

```bash
uv sync --extra dev
npm --prefix typescript install
npm --prefix apps/web install
```

Run the complete local verification suite:

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/export_openapi.py --check
uv run python scripts/check_typescript_client.py
npm --prefix typescript run typecheck
npm --prefix typescript test
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run test:e2e
CANOPYLEDGER_NEXT_DIST_DIR=.next-e2e npm --prefix apps/web run build
```

`pytest` skips PostgreSQL-marked tests when `DATABASE_URL` is unset. That is expected for a local, non-database checkout; it is not equivalent to the durable integration gate.

Run the canonical local report demo:

```bash
make demo
```

`make demo` starts a fresh disposable PostgreSQL 17/PostGIS instance, applies migrations, ingests
and approves synthetic evidence, freezes one facility snapshot, publishes M1B/M3/M4A/M5/M6,
records an independent final approval, creates the immutable HTML/PDF report package, and starts
the API plus Reports UI. Open the printed `/sign-in` URL, select the synthetic approver role, and
navigate to the facility’s **Reports** workspace. Press Ctrl-C to stop the servers and remove the
disposable database. Use `make demo-verify` to run the same pipeline/package walkthrough without
starting the web servers. Supplying `DATABASE_URL` makes the caller responsible for database lifecycle.

## Run locally

Start the API in one terminal:

```bash
uv run uvicorn canopyledger.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Check it in another terminal:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json > /tmp/canopyledger-openapi.json
```

Then start the web app with the opt-in local synthetic sign-in:

```bash
export CANOPYLEDGER_DEMO_SESSION_SECRET="$(openssl rand -hex 32)"
CANOPYLEDGER_API_BASE_URL=http://127.0.0.1:8000 \
CANOPYLEDGER_DEMO_AUTH_ENABLED=true \
CANOPYLEDGER_DEMO_SESSION_SECRET="$CANOPYLEDGER_DEMO_SESSION_SECRET" \
npm --prefix apps/web run dev
```

Open <http://127.0.0.1:3000/sign-in> and choose the synthetic analyst or approver role. The browser receives only a signed, HttpOnly role cookie; the web server maps it to the synthetic bearer header when calling FastAPI. FastAPI still authorizes every request. This opt-in flow proves identity forwarding only: it does not create facilities, snapshots, or published workspace data. This is a local reference demo, not a production identity provider. [DEMO.md](DEMO.md) has the complete click-by-click walkthrough and fixture limitations.

For a lightweight UI fixture that skips the canonical database pipeline, start the explicit seeded
reference factory instead of `create_app`:

```bash
uv run uvicorn canopyledger.demo.workspace:create_demo_app --factory --host 127.0.0.1 --port 8000
```

Then start the web application with the local sign-in variables above and open the fixed synthetic context:

```text
Facility: fac_0198a000-0000-7000-8000-000000000801
Snapshot: snp_0198a000-0000-7000-8000-000000000801
```

This developer fixture exercises actual FastAPI authorization and read routes, but its frozen values
are checked-in synthetic projections. It is not the canonical database-backed pipeline; use `make demo`
for the full M10 report workflow.

The local demonstration tokens are intentionally non-secret fixtures:

```text
analyst-demo-token
approver-demo-token
second-approver-demo-token
```

They exist solely for the synthetic reference application. Never adapt them into a real authentication design.

## API and generated client

The checked-in OpenAPI contract is [docs/api/openapi-v1.json](docs/api/openapi-v1.json). The generated TypeScript client lives in `typescript/generated/`; do not hand-edit it.

After changing a public API model or route, regenerate/check both artifacts:

```bash
uv run python scripts/export_openapi.py
uv run python scripts/check_typescript_client.py --write
uv run python scripts/export_openapi.py --check
uv run python scripts/check_typescript_client.py
```

Important runnable endpoints include:

- `GET /health`
- `POST /api/v1/cbb-certificates/demo`
- `POST /api/v1/m1b/pipeline/demo`
- `POST /api/v1/hedge-liquidity/demo` (explicitly non-authoritative preview)
- `POST /api/v1/evidence/documents` and candidate-fact review actions
- `POST /api/v1/evidence/documents/{document_version_id}/extractions` (candidate-only M7 parsing)
- `GET /api/v1/evidence/extractions/{extraction_id}` and candidate extraction provenance
- `POST /api/v1/snapshots/{snapshot_id}/recommendations`
- `POST /api/v1/recommendations/{recommendation_id}/approval-requests`
- `POST /api/v1/approval-requests/{approval_request_id}/approve`
- `POST /api/v1/decisions/{decision_id}/reports` (current approved final decision only)
- `GET /api/v1/decisions/{decision_id}/reports`
- `GET /api/v1/reports/{report_id}/artifacts/{HTML|PDF}`
- `GET /api/v1/snapshots/{snapshot_id}/climate-traceability`
- snapshot-scoped Cockpit, Collateral, Evidence, Hedge Lab, Scenario Lab, Climate & Traceability, and Approval read models

## PostgreSQL integration gate

Run the complete fresh-database acceptance gate locally with Docker installed and running:

```bash
make test-m1a-postgres
```

The target starts a uniquely named disposable PostGIS 17 container, bootstraps capability roles,
runs migrations, Alembic drift detection, and the complete PostgreSQL marker suite, then removes
the container. It fails if Docker or any gate is unavailable; it never treats skipped PostgreSQL
tests as acceptance evidence.

To use a separately provisioned disposable PostgreSQL 17/PostGIS database instead, bootstrap its
capability roles first, set `DATABASE_URL`, and run the same target, or execute the individual
steps:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger'
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run alembic check
uv run pytest -m postgres -q
```

Use an empty disposable database. The integration suite verifies immutable persistence, capability-role boundaries, serializable snapshot freeze, durable stage publication, replay, and governance behavior.

## Document intelligence benchmark

M7 classification/extraction is deterministic and candidate-only. Run the checked-in benchmark with
`make document-extraction-benchmark`; its JSON reports classification accuracy and candidate
fact-type exactness without reading or modifying approved evidence.

## Repository layout

```text
apps/web/                 Next.js App Router presentation layer
src/canopyledger/api/     FastAPI routes, typed API models, OpenAPI rendering
src/canopyledger/domain/  Money, IDs, units, domain value objects
src/canopyledger/integrity/ canonicalization, snapshots, digests, replay, idempotency
src/canopyledger/borrowing_base/ CBB calculations and certificate output
src/canopyledger/evidence/ evidence controls and immutable fact lineage
src/canopyledger/hedge/   hedge and liquidity engine
src/canopyledger/scenario/ scenario capacity and IRC engine
src/canopyledger/governance/ recommendations, approvals, decisions, overrides
src/canopyledger/reporting/ canonical report models, pinned rendering, immutable artifacts
typescript/               canonical vectors and generated TypeScript client
tests/                    unit, property, API, SSR, and PostgreSQL integration tests
docs/api/                 checked-in OpenAPI artifact
```

## Contributing and security

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), keep authoritative calculations in Python, preserve snapshot/bundle/approval boundaries, and include executable verification evidence with changes.

See [docs/reporting.md](docs/reporting.md), [docs/data-card.md](docs/data-card.md), and
[docs/release-checklist.md](docs/release-checklist.md) for M10 reporting and release material.

Please do not open public issues containing vulnerabilities, real financial data, credentials, or sensitive documents. See [SECURITY.md](SECURITY.md).

## License

Copyright © CanopyLedger contributors. Licensed under [Apache-2.0](LICENSE).
