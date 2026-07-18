# CanopyLedger demo guide

This guide demonstrates deterministic collateral calculations, evidence review, hedge/liquidity,
scenario/IRC projections, climate/EUDR evidence readiness, financed-emissions lineage, credit early
warning, human governance, canonical reports, and the Next.js workspaces.

The canonical one-command path is `make demo`. It runs only synthetic data through a disposable
PostgreSQL/PostGIS pipeline and starts the API and web app. Climate & Traceability reports evidence
readiness only; it never certifies legal compliance or deforestation-free status.

All examples use synthetic fixture data and intentionally non-secret demo tokens.

## 1. Install and verify the checkout

From the repository root:

```bash
uv sync --extra dev
npm --prefix typescript install
npm --prefix apps/web install
```

Run the fast, complete non-PostgreSQL verification path:

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

Expected result: linting and typing pass; the Python suite passes while PostgreSQL-marked tests are skipped if `DATABASE_URL` is absent; TypeScript contracts pass 14 tests; the web suite passes 14 unit tests and 5 end-to-end tests.

The web SSR test is the most complete runnable UI demo. It starts a fixture API and a real Next.js server, then verifies bearer forwarding and all seven snapshot workspaces:

- Cockpit
- Collateral
- Evidence and evidence detail
- Hedge Lab
- Scenario Lab
- Climate & Traceability
- Approval

## 2. Start the local API

In terminal A, start the in-memory FastAPI application:

```bash
uv run uvicorn canopyledger.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In terminal B, verify the service and save the live schema if useful:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json > /tmp/canopyledger-openapi.json
```

Expected health response:

```json
{"status":"ok"}
```

Set the synthetic tokens for the remaining API calls:

```bash
export API='http://127.0.0.1:8000'
export ANALYST='Authorization: Bearer analyst-demo-token'
export APPROVER='Authorization: Bearer approver-demo-token'
```

The in-memory app keeps state only while terminal A is running. Restarting it resets facilities, evidence, and decisions.

## 3. Backend: calculate a deterministic CBB certificate

Send an authenticated CBB demo request. It contains only decimal strings and displays the output without binary-floating-point conversion:

```bash
curl --fail-with-body -sS "$API/api/v1/cbb-certificates/demo" \
  -H "$ANALYST" -H 'Content-Type: application/json' \
  --data @- <<'JSON' | python3 -m json.tool
{
  "certificate_id": "cbb_0198a000-0000-7000-8000-000000000901",
  "snapshot_id": "snp_0198a000-0000-7000-8000-000000000901",
  "facility_id": "fac_0198a000-0000-7000-8000-000000000901",
  "facility_limit": {"amount": "100000.00", "currency": "USD"},
  "contributions": [
    {"source_type": "inventory", "source_id": "lot_0198a000-0000-7000-8000-000000000901", "amount": {"amount": "120000.00", "currency": "USD"}}
  ],
  "reserves": [
    {"reserve_type": "documentation", "amount": {"amount": "5000.00", "currency": "USD"}}
  ],
  "usage": {
    "current_principal": {"amount": "20000.00", "currency": "USD"},
    "lc_exposure": {"amount": "0.00", "currency": "USD"},
    "other_contractual_usage": {"amount": "0.00", "currency": "USD"}
  },
  "reason_codes": ["SYNTHETIC_DEMO"]
}
JSON
```

Inspect `result.contractual_borrowing_base` (`100000.00`) and `result.contractual_availability` (`80000.00`). The certificate also carries an `output_digest`; it is a deterministic, traceable result, not a lending decision.

## 4. Backend: run the initial collateral pipeline and inspect lineage

The full synthetic initial-collateral pipeline request is intentionally kept as a typed test fixture rather than duplicated in this document. Run it directly:

```bash
uv run pytest -q tests/test_m1b_demo_surface.py
```

This executes the public `/api/v1/m1b/pipeline/demo` route and verifies four ordered stage outputs:

```text
market_normalization
collateral_valuation
eligibility_and_reserves
contractual_borrowing_base
```

The test supplies this exact synthetic fixture, so these are the values to
recognize in its assertions and any equivalent API run:

| Pipeline input or result | Value |
|---|---|
| Facility / snapshot / certificate | `fac_0198a000-0000-7000-8000-000000000001` / `snp_0198a000-0000-7000-8000-000000000001` / `cbb_0198a000-0000-7000-8000-000000000001` |
| Facility limit and contractual usage | EUR `500,000.00`; principal EUR `20,000.00`, LC EUR `5,000.00`, other EUR `10,000.00` |
| Inventory lot | `lot_0198a000-0000-7000-8000-000000000001`, `18.4 metric_tonne` of `KC`, advance rate `0.65` |
| Market input | `KC` USD `5,871.42` per metric tonne; EUR/USD `0.918` |
| Receivable | `rec_0198a000-0000-7000-8000-000000000001`; invoice USD `125,000.00`, credit note USD `2,500.00`, advance rate `0.80` |
| Documentation reserve | EUR `12,485.62` |
| Expected result | contractual availability EUR `104,034.45` |

Both the certificate and the final `contractual_borrowing_base` stage include
immutable `sha256:` output digests. The same test exercises
`canopyledger-cbb-demo`, the CLI that writes a canonical CBB certificate JSON
file.

## 5. Backend: inspect hedge/liquidity and scenario/IRC boundaries

Run the focused backend demonstrations:

```bash
uv run pytest -q tests/test_m3_demo_surface.py tests/test_m4a_demo_surface.py
```

They prove two important boundaries:

1. `POST /api/v1/hedge-liquidity/demo` is explicitly a **non-authoritative preview**. It returns no stage/output digest and cannot become a published authoritative output.
2. Snapshot hedge/liquidity and scenario routes return only frozen, published stage outputs. The scenario result preserves the invariant `IRC <= CBB`; it does not overwrite CBB.

For a complete request body and expected hedge result, inspect `tests/test_m3_demo_surface.py`. It intentionally includes both price-risk reduction and a margin-liquidity shortfall, so the demo never equates “more hedged” with “automatically safer.”

The focused tests use the following values; use them to read the results rather
than treating the preview as an authoritative published output:

| Hedge/liquidity preview | Exact fixture value |
|---|---|
| Assessment / snapshot / date | `hdl_0198a000-0000-7000-8000-000000000001` / `snp_0198a000-0000-7000-8000-000000000001` / `2026-06-21` |
| Physical and futures position | `100 metric_tonne` of `KC` for `2026-09`; `-5` ICE KC contracts |
| Futures prices | entry `180`, current `200` US cents per pound |
| Cash and undrawn availability | USD `5,000.00` and USD `3,000.00` |
| Stress moves | one-day `8`, multi-day `25` for `KC` |
| Expected preview outcome | `authoritativeness: "preview"`, no `stage` or `output_digest` |
| Key result | futures P&L USD `-37,500.00`; hedge ratio `0.85048569`; margin-call shortfall USD `38,875.00`; liquidity coverage `0.17066667` |
| Reason codes | `HEDGE_REDUCES_PRICE_EXPOSURE`, `MARGIN_LIQUIDITY_SHORTFALL` |

The scenario fixture uses the same snapshot ID with CBB USD `100,000.00`,
facility commitment USD `120,000.00`, outstanding exposure USD `85,000.00`,
base margin call USD `15,000.00`, and available liquidity USD `12,000.00`.
It uses scenario version `coffee-scenarios-v1`, PRNG
`python-mt19937-v1`, seed `41`, `500` paths, `5` time steps, confidence
`0.95`, and correlation `0.35`. Expect its `price-decline` scenario to have a
stressed CBB below USD `100,000.00`, its `rally-margin` scenario to have a
margin-liquidity shortfall of USD `18,000.00`, and the returned IRC to remain
at or below CBB. These are frozen-output checks; no browser or preview request
may calculate or replace them.

## 6. Backend: create and approve a governed decision

Create a recommendation, request an approval, then approve it with a different actor. Keep terminal A running throughout.

```bash
export SNAPSHOT_ID='snp_0198a000-0000-7000-8000-000000000902'
export RECOMMENDATION_ID='rec_0198a000-0000-7000-8000-000000000902'
export APPROVAL_REQUEST_ID='arq_0198a000-0000-7000-8000-000000000902'
export FINAL_DECISION_ID='fdc_0198a000-0000-7000-8000-000000000902'
export EXPIRES_AT='2030-07-12T00:00:00Z'

curl --fail-with-body -sS "$API/api/v1/snapshots/$SNAPSHOT_ID/recommendations" \
  -H "$ANALYST" -H 'Content-Type: application/json' --data @- <<JSON | python3 -m json.tool
{
  "recommendation_id": "$RECOMMENDATION_ID",
  "requested_amount": {"amount": "70000.00", "currency": "USD"},
  "recommendation_class": "APPROVE_WITH_CONDITIONS",
  "conditions": ["VERIFY_INSURANCE"],
  "reason_codes": ["IRC_POLICY_CAP_BINDS"],
  "expires_at": "$EXPIRES_AT",
  "cbb": {"amount": "100000.00", "currency": "USD"},
  "contractual_availability": {"amount": "75000.00", "currency": "USD"},
  "internal_risk_capacity": {"amount": "90000.00", "currency": "USD"},
  "liquidity_cap": {"amount": "95000.00", "currency": "USD"},
  "facility_commitment": {"amount": "120000.00", "currency": "USD"},
  "policy_caps": [{"amount": "85000.00", "currency": "USD"}],
  "outstanding_exposure": {"amount": "20000.00", "currency": "USD"},
  "approved_unfunded_exposure": {"amount": "5000.00", "currency": "USD"},
  "cbb_output_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "hedge_liquidity_output_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "irc_output_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "policy_bundle_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
}
JSON

curl --fail-with-body -sS "$API/api/v1/recommendations/$RECOMMENDATION_ID/approval-requests" \
  -H "$ANALYST" -H 'Content-Type: application/json' --data @- <<JSON | python3 -m json.tool
{"approval_request_id":"$APPROVAL_REQUEST_ID","expires_at":"$EXPIRES_AT"}
JSON

curl --fail-with-body -sS "$API/api/v1/approval-requests/$APPROVAL_REQUEST_ID/approve" \
  -H "$APPROVER" -H 'Content-Type: application/json' --data @- <<JSON | python3 -m json.tool
{"approval_action_id":"apa_0198a000-0000-7000-8000-000000000902","final_decision_id":"$FINAL_DECISION_ID","reason":"Synthetic independent approval"}
JSON

curl --fail-with-body -sS "$API/api/v1/decisions/$FINAL_DECISION_ID" -H "$APPROVER" | python3 -m json.tool
```

Expected result: the final response has `status: "APPROVED"`. Try the approval call with `$ANALYST` instead of `$APPROVER` to observe the required `403 FORBIDDEN` separation-of-duties failure. Do not use that failure as a successful approval.

These governance calls accept the synthetic snapshot ID as a decision reference, but they do **not** create a facility, frozen snapshot manifest, or published workspace projection. Do not paste `SNAPSHOT_ID` from this section into the web context picker: the stock `create_app` server will correctly return an unavailable state. In a PostgreSQL-backed production-style application, decision context is loaded from the approved snapshot and published CBB, hedge/liquidity, scenario, and IRC resources instead; browser input never calculates or overrides it.

## 7. Start and inspect the web application

### 7.1 Choose the API runtime deliberately

The normal command below starts an empty in-memory API. It is useful for command-level API work and safe unavailable-state UI testing, but the fixed IDs in this guide will not load a workspace there.

For the complete populated UI walkthrough, stop any existing API process on port `8000` and start this opt-in seeded FastAPI factory instead:

```bash
uv run uvicorn canopyledger.demo.workspace:create_demo_app --factory --host 127.0.0.1 --port 8000
```

It serves one immutable synthetic facility and one frozen snapshot through the real FastAPI handlers. It also creates a pending approval request: analyst reads are allowed, while approval-queue and approval actions remain credit-approver-only. Its projections are deliberately checked-in fixtures, not a substitute for the PostgreSQL-backed pipeline or official report package.

Use these exact values in the context picker after signing in:

```text
Facility ID: fac_0198a000-0000-7000-8000-000000000801
Immutable snapshot ID: snp_0198a000-0000-7000-8000-000000000801
```

### 7.2 Start the web server

In terminal C, while the local API remains running, enable the local synthetic sign-in flow:

```bash
export CANOPYLEDGER_DEMO_SESSION_SECRET="$(openssl rand -hex 32)"
CANOPYLEDGER_API_BASE_URL=http://127.0.0.1:8000 \
CANOPYLEDGER_DEMO_AUTH_ENABLED=true \
CANOPYLEDGER_DEMO_SESSION_SECRET="$CANOPYLEDGER_DEMO_SESSION_SECRET" \
npm --prefix apps/web run dev
```

Open <http://127.0.0.1:3000/sign-in>. Use the same host consistently—do not switch between `127.0.0.1` and `localhost`—because the local browser session is host-only. The root page shows the responsive application shell, facility/snapshot context picker, all seven governed workspaces, and the authority vocabulary. The next section gives the exact click-by-click walkthrough.

On the sign-in page, read the two role cards before selecting one. **Analyst access** can inspect governed workspaces and review evidence or recommendations, but cannot record final approval or approve its own work. **Approver access** can inspect governed workspaces and act on eligible approval requests; FastAPI still enforces separation of duties, expiry, and no-self-approval. The browser stores only a signed, HttpOnly role session. It never receives a bearer token in a URL, page markup, JavaScript storage, or a browser request header. The Next.js server maps the selected synthetic role to its local bearer header and FastAPI remains the authorization authority.

The sign-in link preserves the selected facility, snapshot, and workspace route. After either sign-in or sign-out, the browser returns to that same route rather than discarding the context. Selecting a facility/snapshot uses a normal server redirect, so it continues to work even if browser JavaScript has not yet hydrated. With the normal `create_app` API, sign-in proves authorization forwarding only; it does not create facility, snapshot, or published workspace data. With the explicit seeded factory from section 7.1, it authorizes access to the supplied frozen fixture context.

The default in-memory API does not seed the fully published read models required by every UI workspace. Signing in proves the browser-to-server authorization path; an unknown or unseeded context then correctly changes from access guidance to an unavailable-resource state. The complete authorized, data-bearing UI journey is exercised by the checked-in fixture-backed test below.

## 8. Detailed UI walkthrough

The screenshots below are the visual reference for this walkthrough. They were
captured from the local, seeded FastAPI workspace described in section 7.1,
using only the synthetic facility and immutable snapshot in this guide. They
show server-issued read models, not a calculation pipeline or an official
credit record. Expand **Authoritative lineage** before relying on a value: the
snapshot, stage, digest, bundle references, timestamp, and reason codes belong
with that value.

> **Capture context.** The seeded UI factory is for repeatable browser
> verification. `make demo` remains the canonical PostgreSQL/PostGIS
> demonstration. Screens that show an approval or override use an in-memory
> synthetic mutation solely to reveal the governed UI state; they are not
> production instructions or evidence of a real approval.

### 8.1 Choose the local demonstration role

Start at `/sign-in`. Read both role cards before selecting a role. **Analyst**
can inspect and review; **Approver** can act only when FastAPI permits it.
Neither browser session contains a bearer token, and neither role makes the
fixture data authoritative.

![Local synthetic sign-in with analyst and approver role cards](docs/assets/demo-ui/08-01-local-sign-in.png)

### 8.2 Orient yourself in the shell

After signing in, use the left navigation and the top context bar. The current
shell has eleven workspaces: Cockpit, Collateral, Evidence, Hedge Lab, Scenario
Lab, Climate & Traceability, Credit Monitoring, Analytics Copilot, Governed
Agents, Approval, and Reports. With no context selected, `Unavailable` is the
expected authority state.

![Desktop workspace shell with navigation, context picker, role, and governance key](docs/assets/demo-ui/08-02-workspace-shell.png)

On a narrow screen, select **Toggle workspace navigation** to open the same
workspace list. Select it again (shown as **Close**) to dismiss the sheet.

![Mobile workspace navigation sheet](docs/assets/demo-ui/08-02-mobile-navigation.png)

### 8.3 Select the frozen facility context

Enter these values in the top bar, then select **Open context**:

```text
Facility ID: fac_0198a000-0000-7000-8000-000000000801
Immutable snapshot ID: snp_0198a000-0000-7000-8000-000000000801
```

The browser redirects to the frozen Cockpit route only after FastAPI confirms
the facility/snapshot pairing. A snapshot cannot be opened by itself: supply
both IDs. To inspect a working facility instead, leave the snapshot blank.

![Filled context picker before opening the frozen snapshot](docs/assets/demo-ui/08-03-context-ready.png)

### 8.4 Recognize safe states before retrying

An access-safe screen deliberately does not disclose whether a protected
facility or snapshot exists. Select **Sign in locally**, choose a permitted
role, and return to the same route. Other safe states are equally intentional:
loading says **Retrieving authoritative state**; an authorized missing resource
says it is unavailable; and a missing published stage says no published output
is available. Do not infer or enter values in any of these states.

![Unauthenticated snapshot route with non-disclosing access guidance](docs/assets/demo-ui/08-04-safe-access-guidance.png)

### 8.5 Read Cockpit without collapsing authority boundaries

Start at **Cockpit**. Read the top cards first: commitment, exposure, CBB,
contractual availability, IRC, liquidity cap, and approved unfunded exposure
are separate server-issued values. Then distinguish the **Advisory
recommendation** from the **Human final decision**. A recommendation is not an
approval, and CBB and IRC remain independent.

Continue down the page for climate-evidence readiness, blockers, lineage, and
the compact S5 Hedge & liquidity and S6 Scenario & IRC summaries. The
**Inspect canonical JSON** disclosures are read-only source-envelope views;
they do not expose a browser calculation.

![Frozen Cockpit showing capacity cards, recommendation, decision state, blockers, and S5/S6 summaries](docs/assets/demo-ui/08-05-cockpit.png)

### 8.6 Inspect each collateral projection

Select **Collateral**, then use the four tabs. The line above every table says
**Frozen server page** and gives the returned row count and page size. If a
**Next authoritative page** control appears, use it rather than client-side
sorting or pagination. Finish by checking blockers and lineage.

1. **Inventory** shows the normalized quantity and market/recovery/advanced
   values returned for each lot.

   ![Inventory collateral projection](docs/assets/demo-ui/08-06-collateral-inventory.png)

2. **Receivables** keeps open amount, facility value, advanced value, and
   reason codes in the server projection.

   ![Receivables collateral projection](docs/assets/demo-ui/08-06-collateral-receivables.png)

3. **Eligible contributions** is the issued eligibility view, not a browser
   total.

   ![Eligible contributions projection](docs/assets/demo-ui/08-06-collateral-contributions.png)

4. **Reserves** lists the contractual reserve types and amounts.

   ![Contractual reserves projection](docs/assets/demo-ui/08-06-collateral-reserves.png)

### 8.7 Review evidence before taking a human action

Select **Evidence**. A queue entry is candidate evidence—not approved evidence.
Read its extractor, conflict, and document-lineage details before selecting
**Open review packet**.

![Evidence queue with candidate-only intake and human actions](docs/assets/demo-ui/08-07-evidence-queue.png)

In the packet, compare candidate and original-document metadata, including raw
and normalized values, subject/period, source-byte digest, uploader, and
extractor. **Safe text rendition** is a bounded preview; the original remains
an attachment download. Use **Approve fact** only after review. To reject,
provide a reason first. A correction remains a candidate until a person uses
**Approve correction and supersede** against the active approved fact.

![Evidence review packet with provenance, safe rendition, actions, and correction fields](docs/assets/demo-ui/08-07-evidence-packet.png)

After a successful approval, the history identifies the active approved fact;
it does not rewrite the source document or earlier snapshot references.

![Approved evidence state showing the preserved active fact and correction boundary](docs/assets/demo-ui/08-07-evidence-approved-state.png)

### 8.8 Inspect the published Hedge Lab output

Select **Hedge Lab**. This is a frozen S5 output, not a trade-entry screen.
Read the four headline cards, then the physical/hedge delta, variation-margin,
valuation/Greeks, exchange-source, exposure, and delivery-alignment panels.
Verify product and exchange source details before interpreting a hedge ratio or
liquidity result; finish with reason codes and lineage.

![Published Hedge Lab output](docs/assets/demo-ui/08-08-hedge-lab.png)

### 8.9 Inspect the published Scenario Lab output

Select **Scenario Lab**. Keep **Contractual CBB**, **Uncapped IRC**, and
**Governed IRC** distinct. Then inspect the pinned Monte Carlo method,
capacity buffers, shortfall/stability values, distribution, stressed-outcome
table, loss contributions, reason codes, and lineage. The UI has no control to
change seed, shocks, or capacity rules.

![Published Scenario Lab output](docs/assets/demo-ui/08-09-scenario-lab.png)

### 8.10 Record an independent final decision

Sign in as an eligible **Approver**, open **Approval**, and begin with the
requester's identity, expiry, self-approval prohibition, recommendation
lineage, and binding constraint. Enter an auditable **Decision reason** before
selecting **Approve** or **Reject**. FastAPI, not the browser, enforces role,
expiry, and separation of duties.

![Pending approval request with reason field and immutable audit timeline](docs/assets/demo-ui/08-10-approval-queue.png)

After a recorded action, the queue refreshes and the immutable timeline retains
the approval and final-decision events. An empty queue means no request was
returned for that snapshot; it never implies a decision.

![Approval workspace after the synthetic decision, with timeline and override queue](docs/assets/demo-ui/08-10-approval-recorded.png)

### 8.11 Request a dual-control override

The form appears only after the Cockpit shows a recorded final decision. Enter
the proposed cap, policy basis, expiry, and reason, then select **Request
override**. The original recommendation and decision remain unchanged.

![Cockpit dual-control override request form](docs/assets/demo-ui/08-11-override-request.png)

On success, retain the immutable override ID and open the review record.

![Recorded override request with immutable ID and review link](docs/assets/demo-ui/08-11-override-recorded.png)

The review shows the original decision, recommendation, digest, requester, and
`n of required approvals`. A different eligible approver must supply the
independent reason and select **Record override approval**. The requester and
duplicate approvers are rejected, so this seeded walkthrough correctly stops
at `0 of 2 approvals`.

![Dual-control override review awaiting independent approvers](docs/assets/demo-ui/08-11-override-review.png)

### 8.12 Reproduce the visual contract

The images are checked-in UI evidence, while the automated contract below
verifies the rendered workspace routes and server-side identity forwarding. It
uses an isolated test fixture; it is not a substitute for the PostgreSQL
pipeline or a calculation authority.

![Frozen Cockpit visual contract exercised by the fixture-backed UI journey](docs/assets/demo-ui/08-05-cockpit.png)

```bash
npm --prefix apps/web run test:e2e
```

When the application UI changes, recapture the affected screenshot from the
seeded local factory, update its supporting steps, and keep the automation
passing. This keeps the guide, rendered contract, and authoritative-boundary
language aligned.


## 9. Canonical PostgreSQL/PostGIS report demonstration

Run the complete database-backed report walkthrough:

```bash
make demo
```

This starts a disposable PostgreSQL 17/PostGIS database, applies migrations, ingests and approves
synthetic evidence, freezes the snapshot, publishes collateral, hedge/liquidity, scenario/IRC,
climate/traceability, and credit-advisory results, records a separate human approval, creates the
HTML/PDF report package, and serves the API plus web UI. Use the printed `/sign-in` URL and choose the
synthetic approver role; then open the seeded facility’s Reports workspace. Press Ctrl-C when done.
`make demo-verify` performs the same durable seed/report package flow without launching servers.

### 9.1 Optional: run the PostgreSQL durability suite

This is optional but recommended before evaluating persistence behavior. Start a disposable PostgreSQL 17 instance yourself, then run:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger_demo'
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run alembic check
uv run pytest -m postgres -q
```

Expected result: the suite validates database role isolation, immutable records, durable restart behavior,
serializable freeze, fenced stage publication, replay-visible outputs, evidence controls, governance,
hedge/liquidity, scenario capacity, and canonical report persistence.

## 10. What to explain in a live demo

Use this sequence when presenting the system:

1. State the boundary: all data is synthetic and the system is a reference implementation.
2. Show CBB output, its reserve, usage, reason code, and digest.
3. Show that hedge/liquidity is a separate risk and cash-stress view, not a trade blotter.
4. Show the scenario/IRC invariant: IRC is separate from and cannot exceed CBB.
5. Create a recommendation; call out that it is not a final decision.
6. Approve it with a different actor; demonstrate that an analyst cannot self-approve.
7. Walk the UI using sections 8.2–8.11, then run the end-to-end UI test to prove the seven authorized workspace contracts and server-side identity forwarding.
8. State remaining scope honestly: the credit early-warning output is advisory only; document intelligence
and copilot/agent features remain governed support tooling. Climate/EUDR output remains evidence
readiness, never a legal-compliance conclusion.

## Troubleshooting

| Symptom | Cause and resolution |
|---|---|
| `401 UNAUTHENTICATED` | Send one of the synthetic bearer tokens exactly as shown; the demo API accepts no anonymous protected request. |
| `403 FORBIDDEN` while approving | Use `approver-demo-token`; the analyst token cannot approve its own recommendation. |
| `422` on a demo request | Check the OpenAPI schema and preserve decimal values as strings with the required resource prefixes. |
| UI shows access guidance | Expected while signed out or when `CANOPYLEDGER_DEMO_AUTH_ENABLED` is disabled. Open `/sign-in`, choose a local role, then retry. Use `npm --prefix apps/web run test:e2e` for the fully populated fixture-backed browser journey. |
| PostgreSQL tests skip | Set a disposable `DATABASE_URL`; never point integration tests at valuable data. |
| Web build changes `next-env.d.ts` | Ensure the tracked checkout includes the current `apps/web/.gitignore`; generated declarations are intentionally ignored. |
