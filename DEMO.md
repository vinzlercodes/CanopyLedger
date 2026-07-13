# CanopyLedger demo guide

This guide demonstrates the currently implemented reference scope: deterministic collateral calculations, evidence review, hedge/liquidity, scenario/IRC projections, human governance, and the six Next.js workspaces.

It does not claim to demonstrate planned capabilities. In particular, there is no one-command seed/report demo, no climate/EUDR workflow, no credit model, no copilot/agent runtime, and no official report renderer yet.

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

Expected result: linting and typing pass; the Python suite passes while PostgreSQL-marked tests are skipped if `DATABASE_URL` is absent; TypeScript contracts pass 14 tests; the web suite passes 9 unit tests and 2 SSR end-to-end tests.

The web SSR test is the most complete runnable UI demo. It starts a fixture API and a real Next.js server, then verifies bearer forwarding and all six snapshot workspaces:

- Cockpit
- Collateral
- Evidence and evidence detail
- Hedge Lab
- Scenario Lab
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

It also verifies the fixture’s contractual availability is `104034.45` and that the certificate and final stage include immutable output digests. The same test exercises `canopyledger-cbb-demo`, the CLI that writes a canonical CBB certificate JSON file.

## 5. Backend: inspect hedge/liquidity and scenario/IRC boundaries

Run the focused backend demonstrations:

```bash
uv run pytest -q tests/test_m3_demo_surface.py tests/test_m4a_demo_surface.py
```

They prove two important boundaries:

1. `POST /api/v1/hedge-liquidity/demo` is explicitly a **non-authoritative preview**. It returns no stage/output digest and cannot become a published authoritative output.
2. Snapshot hedge/liquidity and scenario routes return only frozen, published stage outputs. The scenario result preserves the invariant `IRC <= CBB`; it does not overwrite CBB.

For a complete request body and expected hedge result, inspect `tests/test_m3_demo_surface.py`. It intentionally includes both price-risk reduction and a margin-liquidity shortfall, so the demo never equates “more hedged” with “automatically safer.”

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

The API accepts the supplied context values in its in-memory demo mode. In a PostgreSQL-backed production-style application, decision context is loaded from the approved snapshot and published CBB, hedge/liquidity, scenario, and IRC resources instead; browser input never calculates or overrides it.

## 7. Start and inspect the web application

In terminal C, while the local API remains running:

```bash
CANOPYLEDGER_API_BASE_URL=http://127.0.0.1:8000 npm --prefix apps/web run dev
```

Open <http://127.0.0.1:3000>. The root page shows the responsive application shell, facility/snapshot context picker, all six governed workspaces, and the authority vocabulary. The next section gives the exact click-by-click walkthrough.

The reference web app intentionally has no login form or cookie session. It forwards a valid incoming `Authorization: Bearer …` header server-side. A normal browser navigation therefore shows the safe access-guidance state; this prevents resource-existence disclosure without a principal.

To confirm the real server-rendered UI path with an authenticated header, use a second terminal. This does not create browser-side calculations; it asks Next.js to forward the header to FastAPI:

```bash
curl -sS -H "$ANALYST" \
  "http://127.0.0.1:3000/facilities/not-a-real-facility/snapshots/$SNAPSHOT_ID/cockpit" \
  | grep -o 'This resource is unavailable\|Authentication or role access is required' | head -n 1
```

The `not-a-real-facility` example deliberately demonstrates non-disclosure for an unavailable resource. The current in-memory API does not seed the fully published read models required by every UI workspace. The complete authorized, data-bearing UI journey is therefore exercised by the checked-in fixture-backed SSR test below.

## 8. Detailed UI walkthrough

### 8.1 Know which UI experience you are viewing

There are two valid experiences in this reference build:

1. **Public shell and safe access states.** Open the Next.js app normally in a browser. This is the correct way to inspect navigation, context selection, loading, and non-disclosure behavior.
2. **Authorized, data-bearing workspaces.** The web app forwards an incoming bearer header to FastAPI, but intentionally has no browser sign-in or cookie session. To see populated workspace data interactively, place the app behind a local development proxy or header-injection tool that adds one of the synthetic bearer headers to every request. The checked-in SSR test is the reproducible alternative: it starts a fixture API and sends the header itself.

Do not try to add an authorization token to a URL. Tokens belong only in request headers. Do not use the demo tokens outside this synthetic local reference application.

### 8.2 Start at the shell and orient yourself

With the API and web server running, open <http://127.0.0.1:3000>.

On a desktop viewport, look for these elements before doing anything else:

- The left **Primary navigation** sidebar with `Cockpit`, `Collateral`, `Evidence`, `Hedge Lab`, `Scenario Lab`, and `Approval`.
- The top context bar with **Facility ID**, **Immutable snapshot ID**, and **Open context**.
- The **Authority** badge. With no selected context it says `Unavailable`; that is expected.
- The main heading **Select a facility to establish context**.
- The **Governance workflow key**, which defines `Working draft`, `Frozen snapshot`, `Published output`, `Recommendation`, and `Final decision`.

On a narrow/mobile viewport, use the menu button labelled **Toggle workspace navigation**. Click it to open the **Governed workspaces** sheet; click the same control again to close it. The available links are the same as in the desktop sidebar.

Before continuing, read the two statements below the root-page heading:

- Browser code does not calculate CBB, IRC, hedge, scenario, or decision values.
- Human approval remains separate from recommendations.

Those are functional boundaries, not marketing copy: every number in a populated workspace comes from FastAPI.

### 8.3 Select a facility and a snapshot

The context picker establishes the routes that every workspace uses.

#### Use the checked-in UI fixture values

The repeatable UI test uses the following complete, internally consistent
read-only fixture. It is the best set of values to use when comparing the
screens in this guide with the automated browser contract.

| Field | Value | Expected context detail |
|---|---|---|
| Facility ID | `fac_0198a000-0000-7000-8000-000000000801` | `Fixture Coffee Trader`, USD, facility commitment `120,000.00` |
| Immutable snapshot ID | `snp_0198a000-0000-7000-8000-000000000801` | Belongs to the fixture facility and opens the frozen routes below |
| Analyst header | `Authorization: Bearer analyst-demo-token` | Cockpit, Collateral, Evidence, Hedge Lab, and Scenario Lab |
| Approver header | `Authorization: Bearer approver-demo-token` | Approval workspace |

These identifiers and headers exist only in the fixture API launched by
`npm --prefix apps/web run test:e2e`; the default in-memory FastAPI server is
deliberately not seeded with them. If you have a proxy that injects the stated
header into every request and a fixture API compatible with the test, entering
the two IDs opens the data-bearing UI. Otherwise, use the command in section
8.12 as the reproducible visual reference.

1. Click the **Facility ID** field and enter a permitted facility identifier beginning with `fac_`.
2. For a working-facility view, leave **Immutable snapshot ID** empty.
3. Click **Open context**.
4. Expect the browser URL to become `/facilities/{facilityId}/cockpit`.
5. If the API authorizes and finds the facility, expect a **Mutable facility context** page showing the legal name, facility ID, working version, and currency. The authority badge reads `Working draft`.

To open a frozen workspace instead:

1. Enter the same facility identifier.
2. Click **Immutable snapshot ID** and enter the selected snapshot identifier beginning with `snp_`.
3. Click **Open context**.
4. Expect the browser URL to become `/facilities/{facilityId}/snapshots/{snapshotId}/cockpit`.
5. The authority badge reads `Frozen snapshot` only after FastAPI confirms that the snapshot belongs to the facility.

The snapshot field cannot stand alone. If you enter a snapshot without a facility, the client rejects the context and does not navigate. Supply both IDs rather than trying to infer a facility from a snapshot.

### 8.4 Recognize expected safe states

These states are intentional. Do not treat them as calculation results.

| What you do | What you should see | What it means |
|---|---|---|
| Open a workspace while it is loading | **Retrieving authoritative state** and “CanopyLedger will not infer values…” | The web app is waiting for the API; it does not show a placeholder number. |
| Stop the API, then open a context | **CanopyLedger could not load this context** | The API connection failed; restart FastAPI and retry. |
| Open a protected context without an authorization header | **Authentication or role access is required** | The app deliberately does not say whether the facility or snapshot exists. |
| Use an unknown ID with a valid authorized request | **This resource is unavailable** or a workspace-specific unavailable panel | The resource is absent or not visible; no value is inferred. |
| Open a snapshot before the relevant published output exists | **No published workspace output is available** | The snapshot may exist, but that stage is not available for presentation. |

Every unavailable screen has **Return to context selection** or an equivalent workspace return link. Click it, correct the context or authorization, and retry; do not attempt to populate fields by hand in the browser.

### 8.5 Walk through Cockpit

With an authorized fixture or environment that exposes a populated snapshot, click **Cockpit** in the sidebar. The route is:

```text
/facilities/{facilityId}/snapshots/{snapshotId}/cockpit
```

Check the page in this order:

1. Confirm the heading **Governed capacity, never browser-calculated** and the `Frozen snapshot` badge.
2. Read the seven top cards. They must remain separate: **Facility commitment**, **Current exposure**, **Contractual borrowing base**, **Contractual availability**, **Internal risk capacity**, **Liquidity cap**, and **Approved unfunded exposure**. Each card identifies its currency and says it was returned by the API.
3. In **Advisory recommendation**, look for the recommended exposure cap and its binding constraint. If there is no recommendation, the card says **No recommendation published**. This never means approval.
4. In **Human final decision**, distinguish **Awaiting independent approval** from **Recorded decision**. Capacity numbers do not change that status by implication.
5. Expand **Authoritative lineage** under the recommendation or CBB section. Check the selected snapshot ID, stage/digest, and timestamp before using any number.
6. Read **Constraints and blockers**. Reason codes remain visible; do not dismiss a blocker because a high-level capacity number looks acceptable.
7. Compare the raw server-issued **Hedge liquidity projection** and **Scenario projection** panels. They are presented as projections, not reimplemented browser formulas.

Using the fixture values above, the cards should show the following. These are
server responses to look for, not numbers to type into the browser:

| Cockpit element | Expected value |
|---|---|
| Facility commitment | USD `120,000.00` |
| Current exposure | USD `20,000.00` |
| Contractual borrowing base | USD `100,000.00` (`sha256:cbb`) |
| Contractual availability | USD `75,000.00` |
| Internal risk capacity | USD `90,000.00` (`sha256:scenario`) |
| Liquidity cap | USD `95,000.00` (`sha256:hedge`) |
| Approved unfunded exposure | USD `5,000.00` |
| Policy cap | USD `85,000.00` (`sha256:policy`) |
| Hedge-liquidity projection | liquidity coverage ratio `1.12` |
| Scenario projection | expected shortfall USD `12,000.00` |
| Constraint | `MARGIN_STRESS` |

This fixture intentionally has no recommendation or final decision. Therefore
**No recommendation published** and an awaiting-approval state are the correct
outcome; no override control is expected.

If there is a recorded final decision, the Cockpit also exposes **Request dual-control override**. That action is explained in section 8.11; do not use it to modify the original recommendation.

### 8.6 Walk through Collateral

Click **Collateral**. The default route is:

```text
/facilities/{facilityId}/snapshots/{snapshotId}/collateral
```

Use the section tabs in this order:

1. Click **Inventory**. Check the table headings: lot, input quantity, normalized quantity, gross market value, net recovery value, and advanced value.
2. Click **Receivables**. Check open amount, facility value, advanced value, and returned reason codes.
3. Click **Eligible contributions**. This is the server-issued contribution view, not a browser total.
4. Click **Reserves**. Check each contractual reserve type and amount.

For every tab, inspect the line above the table: it says **Frozen server page** and identifies the authoritative row count and page size. If **Next authoritative page** appears, click it to request the API cursor for the next page; do not use client-side sorting or pagination to create an authoritative view.

At the bottom, inspect **Constraints and blockers** and expand **Authoritative lineage**. Inventory and receivables are tied to the collateral-valuation stage; contributions and reserves are tied to eligibility/reserves. Record the selected snapshot and output digest if you are discussing a row outside the UI.

With the fixture context, **Inventory** has one authoritative row (`1` total,
page size `25`): lot `lot-1`, input and normalized quantity `50 metric_tonne`,
conversion table `m1b-v1`, gross market value USD `100,000.00`, net recovery
value USD `90,000.00`, and advanced value USD `70,000.00`. Expect reason code
`MARGIN_STRESS`. The lineage identifies `out_collateral` / `m1b-1` /
`sha256:collateral` and `out_eligibility` / `m1b-1` / `sha256:eligibility`.
The other fixture tabs are empty, so their empty state—not invented rows—is the
expected result.

### 8.7 Walk through Evidence and its actions

Click **Evidence**. On a populated queue, each row shows fact type, normalized value, subject, period, candidate ID, extractor/version, conflicts, and document lineage.

For a candidate row:

1. Read the conflicts and **Document lineage** disclosure first.
2. Click **Open review packet**. The route adds the candidate-fact ID after `/evidence/`.
3. In the review page, compare **Candidate fact** against **Original document**: normalized value, raw value, subject/period, page region, extractor, document version, byte digest, uploader, and content type.
4. If shown, read **Safe text rendition**. It is a bounded derived preview, not the original file.
5. Click **Download original attachment** only when the original immutable bytes are needed. The browser receives it as an attachment, not an embedded document.
6. Read **Conflicts, history, supersession** before acting.

For an unreconciled candidate, the review page provides **Approve fact** and **Reject fact**:

- To approve, click **Approve fact**. Expect the success text **Evidence fact approved by the governed API.** The queue is revalidated; the candidate no longer remains a pending review item.
- To reject, first enter a clear value in **Rejection reason**, then click **Reject fact**. Expect **Evidence fact rejected by the governed API.** A blank reason produces an inline error instead of a mutation.

To correct rather than approve/reject:

1. Scroll to **Record correction candidate**.
2. Edit **Corrected raw value**, **Corrected normalized value**, and **Corrected value JSON**.
3. Click **Create correction candidate**.
4. Expect **Correction candidate created. It is not approved evidence until a human reviews it.**
5. Click **Open correction review**, inspect the new candidate, then use **Approve correction and supersede** only after selecting the active approved fact being replaced.

Supersession preserves the original approved fact and its historical snapshot references. It does not rewrite the earlier fact.

For a concrete read-only review example, open candidate `cf_1`. The queue row
is a `warehouse_receipt` for subject `lot-1`, period `2026-07`, with normalized
value `50`, document version `docv_1`, byte digest `sha256:fixture`, page
region `page 1`, and extractor `human` version `1`. The review packet compares
candidate value `{ "quantity": "50" }` and raw value `50 bags`. Its safe text
rendition is `receipt.txt` (`text/plain`) with preview:

```text
Warehouse receipt
Lot KC-01
```

The fixture is intentionally read-only: it demonstrates inspection,
attachment handling, and lineage but does not expose an evidence mutation
endpoint. To exercise **Approve fact**, **Reject fact**, or correction fields,
use an authorized environment that supplies a pending candidate and mutation
permissions. A useful correction example for a receipt-backed lot is raw value
`48 bags`, normalized value `48`, and corrected JSON
`{"quantity":"48"}`; the UI must still show it as a candidate until an
independent human action approves it.

### 8.8 Walk through Hedge Lab

Click **Hedge Lab**. Check that the page identifies a published hedge-and-liquidity output and has a `Published output` badge.

Read the page from top to bottom:

1. The top cards show **Net price exposure**, **Hedge ratio**, **Liquidity coverage**, and **Margin-call shortfall**.
2. **Physical and hedge delta** separates gross/net physical exposure, futures, option delta, basis, and FX exposure.
3. **Variation margin protection** separates available liquidity, one-day/multi-day stress, required reserve, and timing mismatch.
4. **Valuation and option Greeks** separates futures P&L, option value/P&L, and returned Greeks.
5. **Frozen exchange sources** shows product/exchange, contract size/unit, settlement rule, and source-document digest. Verify `KC` and `AC` are not conflated.
6. Review **Futures and option exposure** and **Physical and hedge month mismatch** tables.
7. Finish with reason codes and **Authoritative lineage**.

Do not expect trade-entry controls. This is an analysis view of a frozen output, not an execution interface.

The fixture output gives you concrete checks for each panel:

| Hedge Lab element | Expected value |
|---|---|
| Net price exposure / hedge ratio | `71,019.428 kilogram` / `0.58` |
| Gross / net physical | `50,000` / `45,000 kilogram` |
| Futures / option delta | `34,019.428` / `-8,000 kilogram` |
| Liquidity coverage / margin shortfall | `2.50` / USD `0.00` |
| Available cash + undrawn availability | USD `10,000.00` + USD `15,000.00` = USD `25,000.00` |
| One-day / multi-day margin stress | USD `5,000.00` / USD `10,000.00` |
| Futures position | `KC`, delivery `2026-09`, `2` contracts, P&L USD `1,200.00` |
| Option position | `KC` put, delivery `2026-12`, `1` contract, value USD `700.00`, P&L USD `-100.00` |
| Exchange source | ICE `KC`; `37,500 pound` contract, digest `sha256:spec` |
| Published lineage / constraint | `out_hedge`, `sha256:hedge`, `MARGIN_STRESS` |

### 8.9 Walk through Scenario Lab

Click **Scenario Lab**. The page is a published scenario/capacity projection.

1. Start with the four top cards: **Contractual CBB**, **Uncapped IRC**, **Governed IRC**, and **Expected shortfall**. The three capacity values must not be collapsed into one number.
2. In **Monte Carlo method**, inspect scenario version, distribution, PRNG/seed, paths/steps, correlation, and VaR.
3. In **Internal capacity composition**, inspect the risk, tail-loss, liquidity, counterparty, and climate/evidence buffers.
4. In **Shortfall and stability**, review CBB-deficiency probability, margin-liquidity-shortfall probability, expected shortfalls, and VaR stability band.
5. In **Published distribution**, inspect hedge-effectiveness values and tail contribution by factor.
6. Read **Stressed CBB and shortfalls** and **Aggregated loss contribution** tables before relying on a headline IRC value.
7. Inspect reason codes and the final lineage disclosure.

The page shows frozen scenario results. It does not provide a browser control to alter seeds, shocks, or capacity rules.

For the fixture snapshot, expect contractual CBB USD `100,000.00`, uncapped
and governed IRC each USD `68,500.00`, and expected shortfall USD `18,000.00`.
The Monte Carlo disclosure shows scenario version `2026.07`, `MT19937`, seed
`7` derived from the snapshot digest, normal distribution, `1,000` paths,
`10` time steps, confidence `0.99`, and correlation `0.40`. Its VaR is USD
`15,000.00`; the stability band is USD `13,000.00`–`17,000.00`.

In the remaining panels, verify risk/tail/liquidity/counterparty/climate buffers
of USD `10,000.00` / `18,000.00` / `2,000.00` / `1,000.00` / `500.00`;
CBB-deficiency and margin-shortfall probabilities `0.10` and `0.05`; expected
collateral and margin shortfalls USD `3,000.00` and `2,000.00`; and the
`stress-price` row with stressed CBB USD `75,000.00`, margin shortfall USD
`2,000.00`, and loss USD `27,000.00`. The lineage is `out_scenario` /
`sha256:scenario`, with reason code `IRC_POLICY_CAP_BINDS`.

### 8.10 Walk through the Approval workspace

Click **Approval** using an approver-authorized request. The route is:

```text
/facilities/{facilityId}/snapshots/{snapshotId}/approvals
```

For each visible approval request:

1. Confirm the heading **Independent human approval queue**.
2. Read the recommended exposure cap, binding constraint, requester, expiry, and **Self-approval prohibited** status.
3. Expand **Authoritative lineage** and verify the recommendation snapshot/digest before deciding.
4. Enter an auditable explanation in **Decision reason**.
5. Click **Approve** or **Reject**.
6. Expect either **Approval recorded by the governed API.** or **Rejection recorded by the governed API.** The queue refreshes after a successful action.

Do not use the analyst identity to approve an analyst-created request. The API rejects it; an error is the correct safety outcome, not a UI defect. An expired request also cannot become a final decision.

Below the approval queue, inspect **Override review queue** and **Snapshot audit timeline**. An empty queue or timeline is meaningful: it means no visible request/event has been returned for the selected snapshot.

The checked-in fixture intentionally returns empty approval, override, and
timeline lists. So, with its IDs, **Independent human approval queue** followed
by the empty-state guidance is the expected screen. It is not evidence that an
approval request has been silently approved or rejected.

For a data-bearing approval environment, select an existing request returned by
that environment—never invent an ID in the URL—and check these example field
values before deciding: recommended cap USD `85,000.00`, binding constraint
`MARGIN_STRESS`, a future expiry such as `2030-07-12T00:00:00Z`, and decision
reason `Reviewed fixture warehouse receipt and margin-stress constraint.` The
last value is an example explanation to enter, not a substitute for the
server-issued recommendation, requester, snapshot, or digest.

### 8.11 Request and approve a dual-control override

This path is visible only after Cockpit shows **Recorded decision**.

To request an override:

1. Return to **Cockpit** and find **Request dual-control override** in the final-decision panel.
2. Enter **Proposed exposure cap**. The currency is prefilled and read-only.
3. Enter the policy citation in **Policy basis**, a future **Expiry**, and a clear **Reason**.
4. Click **Request override**.
5. Expect **Dual-control override request recorded by the governed API.** The UI shows an immutable override ID and an **Open override review** link.

To review it:

1. Click **Open override review** or find the request in the approval workspace’s override queue.
2. Verify proposed cap, policy basis, expiry, requester, reason, original decision ID, recommendation ID, digest, and `n of required approvals`.
3. With an eligible independent approver, enter **Independent approval reason**.
4. Click **Record override approval**.
5. Expect **Override approval recorded. The API enforces dual control.**

The request form disappears once the required approval count is reached or the request expires. The original decision and recommendation remain visible and traceable throughout.

If your authorized environment contains a recorded final decision, safe example
form values are proposed exposure cap `80000.00` (in the displayed decision
currency, normally USD), policy basis `credit-policy-7.2`, expiry
`2030-07-12T00:00:00Z`, and reason `Temporary exception while margin-stress
evidence is independently reviewed.` These values do not make a request valid
on their own: the server must already return the original final decision and
recommendation, and it must accept the requesting actor. On the fixture in this
guide, the form correctly remains absent because there is no final decision.

### 8.12 Use the fixture-backed walkthrough as the reproducible UI reference

Run this command whenever you want the current complete governed-workspace UI demonstration:

```bash
npm --prefix apps/web run test:e2e
```

The test launches a real Next.js server and a local fixture API, then verifies that:

- all six workspace routes render authoritative server-issued values;
- Cockpit keeps commitment, exposure, CBB, liquidity cap, and recommendation/decision concepts distinct;
- Collateral is server-paginated and retains stage lineage;
- Evidence shows safe rendition metadata and attachment-only download;
- Hedge Lab and Scenario Lab show frozen projections rather than browser calculations;
- Approval is separately authorized; and
- only a valid bearer authorization header is forwarded to the API.

It also verifies that unauthenticated snapshot URLs do not disclose resource existence and instead present safe access guidance.

Treat this test as the reproducible data-bearing visual-contract reference. It supplies a frozen fixture snapshot and values for each workspace, starts a real Next.js server, and asserts the visible headings and fields described in sections 8.5–8.10.

## 9. Optional: run the PostgreSQL durability demonstration

This is optional but recommended before evaluating persistence behavior. Start a disposable PostgreSQL 17 instance yourself, then run:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger_demo'
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run alembic check
uv run pytest -m postgres -q
```

Expected result: the suite validates database role isolation, immutable records, durable restart behavior, serializable freeze, fenced stage publication, replay-visible outputs, evidence controls, governance, hedge/liquidity, and scenario capacity.

## 10. What to explain in a live demo

Use this sequence when presenting the system:

1. State the boundary: all data is synthetic and the system is a reference implementation.
2. Show CBB output, its reserve, usage, reason code, and digest.
3. Show that hedge/liquidity is a separate risk and cash-stress view, not a trade blotter.
4. Show the scenario/IRC invariant: IRC is separate from and cannot exceed CBB.
5. Create a recommendation; call out that it is not a final decision.
6. Approve it with a different actor; demonstrate that an analyst cannot self-approve.
7. Walk the UI using sections 8.2–8.11, then run the SSR UI test to prove the six authorized workspace contracts and header forwarding.
8. State remaining scope honestly: climate/EUDR, credit, document intelligence, copilot/agents, reporting, and the seeded one-command demo remain future milestones.

## Troubleshooting

| Symptom | Cause and resolution |
|---|---|
| `401 UNAUTHENTICATED` | Send one of the synthetic bearer tokens exactly as shown; the demo API accepts no anonymous protected request. |
| `403 FORBIDDEN` while approving | Use `approver-demo-token`; the analyst token cannot approve its own recommendation. |
| `422` on a demo request | Check the OpenAPI schema and preserve decimal values as strings with the required resource prefixes. |
| UI shows access guidance | Expected without an incoming bearer header. Use `npm --prefix apps/web run test:e2e` for the fully authorized fixture-backed browser journey. |
| PostgreSQL tests skip | Set a disposable `DATABASE_URL`; never point integration tests at valuable data. |
| Web build changes `next-env.d.ts` | Ensure the tracked checkout includes the current `apps/web/.gitignore`; generated declarations are intentionally ignored. |
