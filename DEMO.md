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

1. `POST /api/v1/hedge-liquidity/demo` is explicitly a **non-authoritative preview**. It returns no stage/output digest and cannot become an S5 publication.
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

The API accepts the supplied context values in its in-memory demo mode. In a PostgreSQL-backed production-style application, decision context is loaded from the approved snapshot and published S4/S5/S6/IRC resources instead; browser input never calculates or overrides it.

## 7. Start and inspect the web application

In terminal C, while the local API remains running:

```bash
CANOPYLEDGER_API_BASE_URL=http://127.0.0.1:8000 npm --prefix apps/web run dev
```

Open <http://127.0.0.1:3000>. The root page shows the responsive application shell, facility/snapshot context picker, all six governed workspaces, and the authority vocabulary.

The reference web app intentionally has no login form or cookie session. It forwards a valid incoming `Authorization: Bearer …` header server-side. A normal browser navigation therefore shows the safe access-guidance state; this prevents resource-existence disclosure without a principal.

To confirm the real server-rendered UI path with an authenticated header, use a second terminal. This does not create browser-side calculations; it asks Next.js to forward the header to FastAPI:

```bash
curl -sS -H "$ANALYST" \
  "http://127.0.0.1:3000/facilities/not-a-real-facility/snapshots/$SNAPSHOT_ID/cockpit" \
  | grep -o 'This resource is unavailable\|Authentication or role access is required' | head -n 1
```

The `not-a-real-facility` example deliberately demonstrates non-disclosure for an unavailable resource. The current in-memory API does not seed the fully published S4/S5/S6 read models required by every UI workspace. The complete authorized, data-bearing UI journey is therefore exercised by the checked-in fixture-backed SSR test below.

## 8. Run the full data-bearing UI walkthrough

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
7. Run the SSR UI test to show all six authorized presentation workspaces and header forwarding.
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
