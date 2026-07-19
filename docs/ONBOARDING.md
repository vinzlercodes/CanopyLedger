# Getting started with CanopyLedger

CanopyLedger is a local, synthetic reference application for learning how a governed borrowing-base
review can be made repeatable and auditable. It is not production software: do not expose it to a
network or connect it to real people, documents, market data, or credit decisions.

## Choose your first path

| If you want to... | Start here | What you will learn |
|---|---|---|
| See the product quickly | `make demo` and the [demo guide](../DEMO.md) | The analyst and approver journeys through a populated synthetic workspace. |
| Run only the browser walkthrough | The local workspace instructions in [DEMO.md](../DEMO.md#7-run-the-populated-browser-demo) | The UI without setting up the disposable database pipeline. |
| Integrate with the API | [README](../README.md#api-and-client) and [OpenAPI](api/openapi-v1.json) | Snapshot-scoped endpoints, generated TypeScript types, and decimal-string handling. |
| Contribute | [CONTRIBUTING.md](../CONTRIBUTING.md) and the verification section below | The safeguards and tests a change must preserve. |

## Install and run the full synthetic demo

You need Python 3.12 through 3.14, [uv](https://docs.astral.sh/uv/), Node.js 20 or later, npm, and
Docker for the full database-backed demonstration.

```bash
git clone https://github.com/vinzlercodes/CanopyLedger.git
cd CanopyLedger
uv sync --extra dev
npm --prefix typescript install
npm --prefix apps/web install
make demo
```

`make demo` starts a disposable PostgreSQL/PostGIS database, loads synthetic records, applies
migrations, produces an approved decision and report package, then starts the API and browser app.
Open the `/sign-in` URL printed by the command. Stop it with Ctrl-C; the disposable database is
removed.

## Your first 20 minutes

1. At sign-in, read both local role cards. Choose **Analyst** to inspect the workspaces or
   **Approver** to see the approval role. These roles are synthetic fixtures, not an authentication
   design.
2. Select the populated facility and frozen snapshot. The snapshot is the exact set of inputs used
   for that review; it cannot be changed afterwards.
3. In **Cockpit**, distinguish the contractual borrowing base (CBB) from internal risk capacity
   (IRC). CBB is the contract-based collateral result. IRC is a separate internal risk view.
4. Open **Evidence** to see why candidate facts require human review before they can support a
   decision.
5. Open **Approvals** to see the distinction between a recommendation and a final human decision.
   An actor cannot approve their own work.
6. Open **Reports** to inspect the immutable JSON, HTML, and PDF package produced from the frozen,
   approved decision context.

The [detailed demo walkthrough](../DEMO.md#8-detailed-ui-walkthrough) includes screenshots and the
exact clicks for both roles.

## The business flow

```text
Working facility data
        ↓ freeze
Immutable snapshot and pinned bundles
        ↓ run governed stages
Collateral and CBB   +   independent IRC and risk views
        ↓ compare constraints
Advisory recommendation
        ↓ independent human approval
Final decision
        ↓
Immutable report package
```

Evidence follows the same discipline: document extraction creates candidate facts, a human reviews
them, and only approved facts can support a required control. Analytics, document intelligence, and
agents provide governed support; they do not make authoritative calculations or approve decisions.

## Architecture map

| Area | Start with | Why it matters |
|---|---|---|
| Domain and calculations | `src/canopyledger/borrowing_base/`, `scenario/`, `hedge/`, and `integrity/` | Defines deterministic, snapshot-bound calculations and replay controls. |
| Application workflows | `src/canopyledger/application/`, `evidence/`, `governance/`, and `reporting/` | Coordinates review, approval, reporting, and audit lineage. |
| API and persistence | `src/canopyledger/api/app.py`, `migrations/`, and `persistence/` | Exposes the governed API and durable PostgreSQL/PostGIS path. |
| Browser application | `apps/web/src/app/`, `components/`, and `lib/` | Displays server-issued values and keeps authorization on the server. |
| Contracts and tests | `docs/contracts/`, `tests/`, and `apps/web/tests/` | States the safeguards and proves them across API, database, and browser flows. |

The highest-risk areas to change are the snapshot/integrity workflow, calculations, evidence review,
governance, reporting, and their PostgreSQL adapters. Read the relevant contract before modifying a
behavioral rule.

## Verify your setup

Run the normal local checks:

```bash
make verify
npm --prefix typescript run typecheck
npm --prefix typescript test
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run test:e2e
```

Use `make test-postgres` for the disposable PostgreSQL/PostGIS acceptance gate. If you change an API
contract, also run `npm --prefix typescript run client:check` to confirm the generated client stays
in sync.

## Essential safeguards

- Frozen snapshots, published stage outputs, and report packages are immutable.
- CBB and IRC remain independent; one must not silently replace the other.
- Candidate evidence is not approved evidence.
- Recommendations are advisory; a final decision needs an authorized independent human approver.
- The browser presents authoritative API values and lineage. It does not recalculate them.

For the complete contract language, read [docs/contracts](contracts/). For local commands,
screenshots, and expected demo behavior, return to the [demo guide](../DEMO.md).
