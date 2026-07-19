# CanopyLedger

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

CanopyLedger is an open-source reference application for making transparent, repeatable
borrowing-base decisions in coffee trade finance. It brings collateral, receivables, evidence,
market inputs, hedges, scenarios, climate and traceability evidence, and human approvals into one
auditable decision record.

The project exists to demonstrate a safer decisioning pattern: calculations are reproducible,
evidence is reviewable, and an authorized person, not an automated system, makes the final decision.
It is intended for learning, prototyping, and integration design. All bundled data is synthetic;
do not use the reference application with real borrower, farmer, customer, market, credential, or
regulated production data.

## What you can do with it

- Calculate contractual borrowing base and availability from inventory, receivables, reserves, and
  usage.
- Review document-derived evidence, approve or reject candidate facts, and preserve correction and
  supersession history.
- Explore hedge liquidity, scenario capacity, internal risk capacity, credit early-warning signals,
  and climate/traceability evidence readiness without conflating them with the contractual result.
- Create recommendations, request independent approval, record final decisions and overrides, and
  inspect their audit timeline.
- Create immutable decision report packages with a canonical JSON model plus HTML and PDF artifacts.
- Use the FastAPI service directly or explore the same API through the included Next.js web app.

## Key safeguards

CanopyLedger keeps several concepts deliberately separate:

- **Contractual borrowing base (CBB)** is the collateral calculation defined by the facility terms.
- **Internal risk capacity (IRC)** is a risk-management view; it never silently replaces CBB.
- **Evidence candidates** are not approved evidence until a human reviewer accepts them.
- **Recommendations** are advisory; a final decision needs an authorized, independent approver.
- **Current reports** are issued only for the active approved decision. Historical reports remain
  clearly designated as audit records.

The browser displays API-provided results and lineage. It does not calculate authoritative
financial values or create official reports from client state.

## Terms used here

- A **facility** is the lending agreement being reviewed.
- **Collateral** is the inventory or receivables that support that facility.
- The **borrowing base** is the contractual value of eligible collateral after agreed limits and reserves.
- **CBB** is that contractual borrowing base. **IRC** is a separate internal risk view.
- A **snapshot** is a frozen copy of the inputs used for one review.
- Money is returned as strings, such as `"120000.00"`, so clients do not lose decimal precision.

## Architecture

```text
Next.js web app
  Cockpit · Collateral · Evidence · Hedge · Scenarios · Climate · Credit
  Analytics · Agents · Approvals · Reports
                                      |
                                 HTTPS / JSON
                                      |
FastAPI service ── snapshots · evidence · governance · reporting read models
                                      |
              PostgreSQL/PostGIS adapters or in-memory local adapters
                                      |
     deterministic Python engines ── valuation · eligibility · liquidity · scenarios
```

Local experimentation uses in-memory adapters. The durable path uses PostgreSQL, PostGIS,
Alembic migrations, and the integration suite.

## Quick start

### Prerequisites

- Python 3.12 through 3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or later and npm
- Docker, only for the complete disposable PostgreSQL/PostGIS demonstration and integration gate

### Install

```bash
git clone https://github.com/vinzlercodes/CanopyLedger.git
cd CanopyLedger
uv sync --extra dev
npm --prefix typescript install
npm --prefix apps/web install
```

### Run the full synthetic demonstration

```bash
make demo
```

This starts a disposable PostgreSQL/PostGIS database, loads only synthetic records, applies the
schema migrations, creates an approved decision and its immutable report package, then starts the
API and web app. Open the `/sign-in` address printed by the command, choose a synthetic role, and
open the facility’s **Reports** workspace. Stop the command with Ctrl-C; it removes the disposable
database it created.

Use `make demo-verify` when you want the same end-to-end workflow and report verification without
starting the web servers. See the [demo guide](DEMO.md) for a click-by-click walkthrough, direct API
examples, expected synthetic results, and known limits of the demo.

### Choose your path

| Goal | Start here |
|---|---|
| See both user roles in a populated UI | [Demo walkthrough](DEMO.md#8-detailed-ui-walkthrough) |
| Learn the project from installation to a first contribution | [Getting started and onboarding](docs/ONBOARDING.md) |
| Call the API or use generated client types | [API and client](#api-and-client) |
| Understand the non-negotiable safeguards | [Key safeguards](#key-safeguards) and [contracts](docs/contracts/) |

### How a decision moves through the system

```text
Working facility → frozen snapshot → governed calculations → recommendation
                                                    ↓                 ↓
                                      evidence reviewed by a human   independent approval
                                                                      ↓
                                                           final decision → immutable report
```

The snapshot is the boundary that makes a review reproducible. CBB remains the contractual
collateral result; IRC remains a separate internal risk view. Candidate evidence, recommendations,
analytics, and agents never become final authority on their own.

## Run the application locally

Start the API in one terminal:

```bash
CANOPYLEDGER_DEMO_AUTH_ENABLED=true \
uv run uvicorn canopyledger.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Confirm it is running:

```bash
curl http://127.0.0.1:8000/health
```

For a populated UI walkthrough without the database pipeline, use the checked-in synthetic workspace
instead:

```bash
uv run uvicorn canopyledger.demo.workspace:create_demo_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal, start the web app with the explicitly enabled local sign-in:

```bash
export CANOPYLEDGER_DEMO_SESSION_SECRET="$(openssl rand -hex 32)"
CANOPYLEDGER_API_BASE_URL=http://127.0.0.1:8000 \
CANOPYLEDGER_DEMO_AUTH_ENABLED=true \
CANOPYLEDGER_DEMO_SESSION_SECRET="$CANOPYLEDGER_DEMO_SESSION_SECRET" \
npm --prefix apps/web run dev
```

Open <http://127.0.0.1:3000/sign-in>. The demo roles and tokens are public synthetic fixtures, not
an authentication design. They are disabled by default and may be enabled only for a loopback,
synthetic demonstration. Do not expose this API to a network or connect it to real data. The web
server forwards the selected synthetic identity to FastAPI, where authorization remains enforced.

## Reports

Reports are compiled from a frozen snapshot, published outputs, a recommendation, and an approved
final decision. The canonical report model is JSON; HTML and PDF are derived, immutable artifacts.
Each package records its input and output digests, renderer metadata, and whether it is the current
official report or a retained historical audit report.

Use the Reports workspace to inspect a package and download its HTML or PDF artifact. Integrations
can create a package with `POST /api/v1/decisions/{decision_id}/reports`, list packages with
`GET /api/v1/decisions/{decision_id}/reports`, and download an artifact from
`GET /api/v1/reports/{report_id}/artifacts/{format}`. The detailed [reporting guide](docs/reporting.md)
explains the report lifecycle and reproducibility guarantees.

## API and client

The live schema is available at `/openapi.json`; the versioned checked-in contract is
[docs/api/openapi-v1.json](docs/api/openapi-v1.json). A generated TypeScript client is kept in
[`typescript/generated`](typescript/generated/).

The most useful starting points are:

- `GET /health` for service status.
- `POST /api/v1/cbb-certificates/demo` for a synthetic borrowing-base calculation.
- Evidence document and candidate-fact endpoints for the review workflow.
- Snapshot-scoped Cockpit, Collateral, Evidence, Hedge, Scenario, Climate, Approval, and Reports
  read models for UI or integration use.

API callers must treat monetary values and other authoritative decimals as strings, retain returned
lineage fields, and keep authorization on the server side.

## Verification

Run the standard local checks:

```bash
make verify
npm --prefix typescript run typecheck
npm --prefix typescript test
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run test:e2e
CANOPYLEDGER_NEXT_DIST_DIR=.next-e2e npm --prefix apps/web run build
```

`pytest` skips tests that require PostgreSQL when `DATABASE_URL` is unset. To run the full durable
acceptance gate with Docker, use:

```bash
make test-postgres
```

The command provisions an isolated PostGIS database, runs migrations and database checks, executes
the PostgreSQL-marked tests, then removes the database.

## Documentation

- [Getting started and onboarding](docs/ONBOARDING.md): choose a demo, integration, or contribution path and learn the core business flow.
- [Demo guide](DEMO.md): install, API, UI, and report-package walkthrough.
- [Reporting guide](docs/reporting.md): report lifecycle, artifacts, and reproducibility.
- [Synthetic data card](docs/data-card.md): what the bundled fixtures are and are not.
- [API contract](docs/api/openapi-v1.json): versioned OpenAPI document.
- [Contributing guide](CONTRIBUTING.md): development setup and contribution expectations.
- [Code of conduct](CODE_OF_CONDUCT.md): expectations for a respectful community.
- [Support](SUPPORT.md): where to get help and what to include in a question.
- [Security policy](SECURITY.md): reporting a vulnerability and handling sensitive data.
- [Changelog](CHANGELOG.md): changes on the default branch and historical releases.

## Repository layout

```text
apps/web/                   Next.js presentation layer
src/canopyledger/api/       FastAPI routes and API models
src/canopyledger/*/         Domain engines and durable adapters
src/canopyledger/reporting/ Canonical report models and renderers
typescript/                 Shared canonical utilities and generated API client
migrations/                 Alembic database migrations
docs/                       User, integration, and release documentation
tests/                      Unit, API, UI, and PostgreSQL integration tests
```

## Scope and limitations

CanopyLedger is not a core-banking system, market-data terminal, trading platform, legal compliance
service, or autonomous credit engine. Climate and traceability output describes evidence readiness;
it does not certify legal compliance or deforestation-free status. The project has no production
identity-provider, secrets-management, operational-monitoring, or regulatory deployment setup.
It must not be exposed to a network or used with real data.

## Contributing and security

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull
request. Do not include vulnerabilities, real financial data, sensitive documents, or credentials
in public issues; follow [SECURITY.md](SECURITY.md) instead.

## License

Copyright © CanopyLedger contributors. Licensed under [Apache-2.0](LICENSE).
