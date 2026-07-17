import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer, type Server } from "node:http";
import { once } from "node:events";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer as createTcpServer } from "node:net";
import { fileURLToPath } from "node:url";

const facilityId = "fac_0198a000-0000-7000-8000-000000000801";
const snapshotId = "snp_0198a000-0000-7000-8000-000000000801";
const analystToken = "Bearer analyst-demo-token";
const approverToken = "Bearer approver-demo-token";

type FixtureApi = {
  readonly origin: string;
  readonly requests: Array<{ readonly authorization: string | undefined; readonly path: string }>;
  close(): Promise<void>;
};

let fixture: FixtureApi;
let next: ChildProcess;
let nextOrigin = "";

before(async () => {
  fixture = await startFixtureApi();
  const port = await unusedPort();
  nextOrigin = "http://127.0.0.1:" + port;
  next = spawn(
    process.execPath,
    ["node_modules/next/dist/bin/next", "dev", "--turbopack", "--port", String(port)],
    {
      cwd: fileURLToPath(new URL("..", import.meta.url)),
      env: {
        ...process.env,
        CANOPYLEDGER_API_BASE_URL: fixture.origin,
        CANOPYLEDGER_DEMO_AUTH_ENABLED: "true",
        CANOPYLEDGER_DEMO_SESSION_SECRET: "e2e-demo-session-secret",
        CANOPYLEDGER_NEXT_DIST_DIR: ".next-e2e",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  await waitForNext(nextOrigin, next);
}, { timeout: 60_000 });

after(async () => {
  next.kill("SIGTERM");
  await once(next, "exit");
  await fixture.close();
});

test("authorized M4B workspaces render server-issued projections and forward identity", async () => {
  const pages = [
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/cockpit", analystToken, ["Governed capacity, never browser-calculated", "Facility commitment", "Current exposure", "Liquidity cap", "Climate &amp; Traceability evidence", "review required"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/collateral?section=inventory", analystToken, ["Inventory lots"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/evidence", analystToken, ["Candidate facts await human review", "Ingest a known document", "Ingest and extract", "Extraction never approves a fact"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/evidence/cf_1", analystToken, ["Safe text rendition", "Warehouse receipt", "Extractor confidence", "Download original attachment"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/risk/hedge", analystToken, ["Hedge Lab", "Variation margin protection", "Futures and option exposure"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/risk/scenarios", analystToken, ["Scenario Lab", "Uncapped IRC", "Stressed CBB and shortfalls"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/climate", analystToken, ["Climate &amp; Traceability", "Origin map", "Map-equivalent traceability table", "Evidence readiness"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/analytics", analystToken, ["Analytics Copilot", "Approved template question", "Run approved read", "never sends SQL from the browser"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/agents", analystToken, ["Governed Agents", "Start a bounded snapshot review", "Code-owned capability registry", "No governed agent runs"]],
    ["/facilities/" + facilityId + "/snapshots/" + snapshotId + "/approvals", approverToken, ["Independent human approval queue"]],
  ] as const;

  for (const [path, authorization, expected] of pages) {
    const response = await fetch(nextOrigin + path, { headers: { Authorization: authorization } });
    assert.equal(response.status, 200);
    const body = await response.text();
    for (const text of expected) assert.match(body, new RegExp(text));
  }

  assert.ok(fixture.requests.some((request) => request.path.endsWith("/decision-pack") && request.authorization === analystToken));
  assert.ok(fixture.requests.some((request) => request.path.includes("/collateral?section=inventory") && request.authorization === analystToken));
  assert.ok(fixture.requests.some((request) => request.path.endsWith("/approval-requests") && request.authorization === approverToken));
  assert.ok(fixture.requests.every((request) => request.authorization === analystToken || request.authorization === approverToken));
});

test("an unauthenticated snapshot URL keeps resource existence private and gives access guidance", async () => {
  const response = await fetch(nextOrigin + "/facilities/" + facilityId + "/snapshots/" + snapshotId + "/cockpit");

  assert.equal(response.status, 200);
  assert.match(await response.text(), /Authentication or role access is required/);
  assert.ok(fixture.requests.some((request) => request.path.endsWith("/facilities/" + facilityId) && request.authorization === undefined));
});

test("approval workspace preserves the FastAPI analyst/approver boundary", async () => {
  const path = "/facilities/" + facilityId + "/snapshots/" + snapshotId + "/approvals";

  const analyst = await fetch(nextOrigin + path, { headers: { Authorization: analystToken } });
  assert.equal(analyst.status, 200);
  assert.match(await analyst.text(), /Role access is required/);

  const approver = await fetch(nextOrigin + path, { headers: { Authorization: approverToken } });
  assert.equal(approver.status, 200);
  assert.match(await approver.text(), /Independent human approval queue/);
});

test("context selection is a server redirect and sign-in explains local role boundaries", async () => {
  const selected = await fetch(nextOrigin + "/open-context?facility=" + facilityId + "&snapshot=" + snapshotId, { redirect: "manual" });
  assert.equal(selected.status, 307);
  assert.equal(selected.headers.get("location"), "/facilities/" + facilityId + "/snapshots/" + snapshotId + "/cockpit");

  const signIn = await fetch(nextOrigin + "/sign-in");
  const body = await signIn.text();
  assert.match(body, /Analyst access/);
  assert.match(body, /Approver access/);
  assert.match(body, /does not seed facility, snapshot, or published workspace data/);
});

test("local demo sign-in keeps the bearer token server-side and forwards the selected role", async () => {
  const cockpitPath = "/facilities/" + facilityId + "/snapshots/" + snapshotId + "/cockpit";
  const signIn = await fetch(nextOrigin + "/api/session/demo", {
    method: "POST",
    redirect: "manual",
    headers: {
      Origin: nextOrigin,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ role: "analyst", returnTo: cockpitPath }),
  });

  assert.equal(signIn.status, 303);
  const returnLocation = new URL(signIn.headers.get("location") ?? "", nextOrigin);
  assert.equal(returnLocation.pathname, cockpitPath);
  assert.equal(returnLocation.host, new URL(nextOrigin).host);
  const cookie = signIn.headers.get("set-cookie");
  assert.ok(cookie);
  assert.doesNotMatch(cookie, /demo-token/);

  const decisionPackRequests = fixture.requests.filter((request) => request.path.endsWith("/decision-pack") && request.authorization === analystToken).length;
  const workspace = await fetch(nextOrigin + cockpitPath, { headers: { Cookie: cookie.split(";", 1)[0] } });
  assert.equal(workspace.status, 200);
  assert.ok(fixture.requests.filter((request) => request.path.endsWith("/decision-pack") && request.authorization === analystToken).length >= decisionPackRequests + 1);
  const signedInPage = await fetch(nextOrigin + "/sign-in", { headers: { Cookie: cookie.split(";", 1)[0] } });
  const signedInBody = await signedInPage.text();
  assert.match(signedInBody, /Current local session:[\s\S]*analyst/);
  assert.doesNotMatch(signedInBody, /analyst-demo-token/);
  const body = await workspace.text();
  assert.match(body, /Governed capacity, never browser-calculated/);
  assert.doesNotMatch(body, /analyst-demo-token/);
});

async function startFixtureApi(): Promise<FixtureApi> {
  const requests: Array<{ readonly authorization: string | undefined; readonly path: string }> = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://fixture.local");
    const authorization = request.headers.authorization;
    requests.push({ authorization, path: url.pathname + url.search });

    if (authorization !== analystToken && authorization !== approverToken) {
      return respond(response, 401, problem("UNAUTHENTICATED", "Valid demo bearer token required"));
    }
    if (authorization !== approverToken && isApproverOnlyRoute(url.pathname)) {
      return respond(response, 403, problem("FORBIDDEN", "Credit-approver authority is required", 403));
    }
    return respond(response, 200, fixtureBody(url.pathname));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  return {
    origin: "http://127.0.0.1:" + address.port,
    requests,
    close: () => close(server),
  };
}

function fixtureBody(path: string): Record<string, unknown> {
  if (path === "/api/v1/facilities/" + facilityId) return { id: facilityId, legal_name: "Fixture Coffee Trader", currency: "USD", facility_commitment: "120000.00", version: 1 };
  if (path === "/api/v1/snapshots/" + snapshotId + "/manifest") return { snapshot_id: snapshotId, facility_id: facilityId };
  if (path.endsWith("/decision-pack")) return decisionPack();
  if (path.endsWith("/collateral")) return collateral();
  if (path === "/api/v1/evidence/review-queue") return { items: [{ candidate_fact_id: "cf_1", approval_state: "candidate", fact_type: "warehouse_receipt", subject_id: "lot-1", period: "2026-07", normalized_value: "50", document_version_id: "docv_1", document_byte_digest: "sha256:fixture", page_region: "page 1", extraction_method: "human", extractor_version: "1", conflicts: [] }] };
  if (path === "/api/v1/evidence/candidate-facts/cf_1/review") return evidenceReviewPacket();
  if (path === "/api/v1/evidence/candidate-facts/cf_1/extraction-provenance") return { candidate_fact_id: "cf_1", extraction_id: "exr_1", confidence: "0.9500", approval_state: "candidate" };
  if (path === "/api/v1/evidence/documents/docv_1/rendition") return { document_version_id: "docv_1", filename: "receipt.txt", content_type: "text/plain", byte_digest: "sha256:fixture", preview_status: "available", preview_text: "Warehouse receipt\nLot KC-01", truncated: false };
  if (path.endsWith("/hedge-lab")) return hedgeLab();
  if (path.endsWith("/scenario-lab")) return scenarioLab();
  if (path.endsWith("/climate-traceability")) return climateTraceability();
  if (path === "/api/v1/agent-capabilities") return { items: [] };
  if (path.endsWith("/agent-runs")) return { items: [] };
  if (path === "/api/v1/approval-requests") return { items: [] };
  if (path.endsWith("/override-requests")) return { items: [] };
  if (path.endsWith("/governance-timeline")) return { snapshot_id: snapshotId, items: [] };
  throw new Error("Unexpected fixture API route: " + path);
}

function decisionPack(): Record<string, unknown> {
  const money = (amount: string) => ({ amount, currency: "USD" });
  return {
    snapshot_id: snapshotId,
    contractual_borrowing_base: money("100000.00"),
    contractual_availability: money("75000.00"),
    internal_risk_capacity: money("90000.00"),
    liquidity_cap: money("95000.00"),
    facility_commitment: money("120000.00"),
    outstanding_exposure: money("20000.00"),
    approved_unfunded_exposure: money("5000.00"),
    policy_caps: [money("85000.00")],
    cbb_output_digest: "sha256:cbb",
    hedge_liquidity_output_digest: "sha256:hedge",
    irc_output_digest: "sha256:scenario",
    policy_bundle_digest: "sha256:policy",
    hedge_liquidity: { liquidity_coverage_ratio: "1.12" },
    scenario: { expected_shortfall: "12000.00" },
    climate_traceability: {
      stage_output_id: "out_climate",
      output_digest: "sha256:climate",
      completed_at: "2026-07-15T00:00:00Z",
      eudr_evidence_state: "review_required",
      reason_codes: ["TRACEABILITY_MISSING_LINK"],
      legal_interpretation_bundle_digest: "sha256:legal",
    },
    blockers: ["MARGIN_STRESS"],
  };
}

function collateral(): Record<string, unknown> {
  const money = (amount: string) => ({ amount, currency: "USD" });
  return {
    snapshot_id: snapshotId,
    section: "inventory",
    inventory_items: [{ lot_id: "lot-1", input_quantity: "50", input_quantity_unit: "metric_tonne", quantity: "50", quantity_unit: "metric_tonne", unit_conversion_table_version: "m1b-v1", gross_market_value: money("100000.00"), net_recovery_value: money("90000.00"), advanced_value: money("70000.00") }],
    receivable_items: [],
    contribution_items: [],
    reserve_items: [],
    page: { limit: 25, next_cursor: null, total_count: 1 },
    lineage: { collateral_valuation_stage_output_id: "out_collateral", collateral_valuation_stage_version: "m1b-1", collateral_valuation_output_digest: "sha256:collateral", eligibility_stage_output_id: "out_eligibility", eligibility_stage_version: "m1b-1", eligibility_output_digest: "sha256:eligibility" },
    reason_codes: ["MARGIN_STRESS"],
  };
}

function hedgeLab(): Record<string, unknown> {
  const money = (amount: string) => ({ amount, currency: "USD" });
  return {
    stage_output_id: "out_hedge", snapshot_id: snapshotId, stage: "hedge_liquidity", stage_version: "s5-1", output_digest: "sha256:hedge", completed_at: "2026-07-13T00:00:00Z", reason_codes: ["MARGIN_STRESS"],
    contract_specifications: [{ exchange: "ICE", product_code: "KC", contract_symbol: "KC", contract_size: "37500", contract_size_unit: "pound", contract_size_in_exposure_unit: "17009.714", exposure_unit: "kilogram", price_unit: "usd_per_pound", price_unit_factor: "0.01", tick_size: "0.05", currency: "USD", exercise_style: "european", settlement_rule: "futures_delivery", calendar_version: "2026.1", delivery_months: ["2026-09"], effective_from: "2026-01-01", effective_to: "2026-12-31", source_document_digest: "sha256:spec" }],
    futures_positions: [{ product_code: "KC", delivery_month: "2026-09", contracts: "2", delta_exposure: "34019.428", pnl: money("1200.00") }],
    option_positions: [{ product_code: "KC", delivery_month: "2026-12", option_type: "put", contracts: "1", black76_reference_price: "2.1", authoritative_price: "2.1", delta_exposure: "-8000", value: money("700.00"), pnl: money("-100.00"), delta: "-0.47", gamma: "0.02", vega: "0.03", theta: "-0.01", rho: "0.01" }],
    exposure: { exposure_unit: "kilogram", gross_physical_exposure: "50000", purchase_commitment_exposure: "10000", sales_commitment_exposure: "5000", net_physical_exposure: "45000", futures_exposure: "34019.428", option_delta_equivalent: "-8000", net_price_exposure: "71019.428", hedge_ratio: "0.58", under_hedge_amount: "71019.428", over_hedge_amount: "0", fx_exposure: money("500.00"), fx_exposure_source: money("500.00"), basis_exposure: "125.00", delivery_month_mismatch: [{ delivery_month: "2026-09", physical_exposure: "50000", hedge_delta_exposure: "34019.428", net_price_exposure: "84019.428" }], concentration_by_month: [{ delivery_month: "2026-09", physical_concentration: "1.000000" }] },
    valuation: { futures_pnl: money("1200.00"), option_value: money("700.00"), option_pnl: money("-100.00"), aggregate_greeks: { delta: "-0.47", gamma: "0.02", vega: "0.03", theta: "-0.01", rho: "0.01" } },
    liquidity: { available_cash: money("10000.00"), undrawn_contractual_availability: money("15000.00"), total_liquidity_available: money("25000.00"), one_day_margin_stress: money("5000.00"), multi_day_margin_stress: money("10000.00"), timing_mismatch: money("0.00"), margin_call_shortfall: money("0.00"), liquidity_coverage_ratio: "2.50", required_liquidity_reserve: money("10000.00"), required_liquidity_coverage_ratio: "1.00" },
  };
}

function scenarioLab(): Record<string, unknown> {
  const money = (amount: string) => ({ amount, currency: "USD" });
  return {
    stage_output_id: "out_scenario", snapshot_id: snapshotId, stage: "scenario_capacity", stage_version: "s6-1", output_digest: "sha256:scenario", completed_at: "2026-07-13T00:00:00Z", reason_codes: ["IRC_POLICY_CAP_BINDS"], scenario_version: "2026.07",
    monte_carlo: { prng_family: "MT19937", seed_derivation: "snapshot digest", distribution_assumption: "normal", regime_mixture: [{ name: "base", weight: "1.0" }], seed: 7, path_count: 1000, time_steps: 10, thread_count: 1, confidence_level: "0.99", correlation: "0.40", correlation_matrix: [["1", "0.40"], ["0.40", "1"]], value_at_risk: money("15000.00"), expected_shortfall: money("18000.00"), cbb_deficiency_probability: "0.10", margin_liquidity_shortfall_probability: "0.05", expected_collateral_shortfall: money("3000.00"), expected_margin_liquidity_shortfall: money("2000.00"), threshold_stability: { lower_confidence_level: "0.98", upper_confidence_level: "0.995", lower_value_at_risk: money("13000.00"), upper_value_at_risk: money("17000.00"), band_width: money("4000.00") }, tail_contribution_by_factor: { collateral_price: "0.75", margin_liquidity: "0.25" }, hedge_effectiveness_distribution: { minimum: "0.4", median: "0.7", p95: "0.9", maximum: "1.0" } },
    deterministic_scenarios: [{ scenario_id: "stress-price", family: "price", stressed_cbb: money("75000.00"), cbb_deficiency: money("0.00"), margin_liquidity_shortfall: money("2000.00"), loss: money("27000.00") }],
    worst_scenario_families: [{ family: "price", loss: money("27000.00") }],
    internal_risk_capacity: { risk_buffer: money("10000.00"), tail_loss_buffer: money("18000.00"), liquidity_buffer: money("2000.00"), counterparty_buffer: money("1000.00"), climate_evidence_buffer: money("500.00"), uncapped_irc: money("68500.00"), irc: money("68500.00"), cbb: money("100000.00"), facility_commitment: money("120000.00") },
  };
}

function climateTraceability(): Record<string, unknown> {
  return {
    stage_output_id: "out_climate", snapshot_id: snapshotId, stage: "climate_eudr", stage_version: "1.0.0", input_digests: ["sha256:input"], legal_interpretation_bundle_digest: "sha256:legal", policy_bundle_digest: "sha256:policy", computation_bundle_digest: "sha256:computation", output_digest: "sha256:climate", completed_at: "2026-07-15T00:00:00Z", eudr_evidence_state: "review_required", reason_codes: ["TRACEABILITY_MISSING_LINK"],
    result: {
      traceability: { lots: [{ lot_id: "lot-1", origin_country: "BR", geometry: { type: "Point", coordinates: ["-47.8825", "-15.7942"] }, production_date_class: "on_or_after_cutoff", freshness_state: "current", missing_links: ["warehouse_receipt"], reason_codes: ["TRACEABILITY_MISSING_LINK"] }], origin_concentration: [{ origin_country: "BR", concentration: "1.000000" }] },
      financed_emissions: { total_available: "125.000000", data_quality_score: 2, methodology_version: "pcaf-fixture-v1", restatement_lineage: "restatement-1", missing_data_warnings: [] },
    },
  };
}

function evidenceReviewPacket(): Record<string, unknown> {
  return {
    document: { document_id: "doc_1", document_version_id: "docv_1", version: 1, filename: "receipt.txt", content_type: "text/plain", byte_digest: "sha256:fixture", size_bytes: 28, created_by: "act_1", created_at: "2026-07-13T00:00:00.000Z" },
    candidate_fact: { candidate_fact_id: "cf_1", approval_state: "candidate", fact_type: "warehouse_receipt", subject_id: "lot-1", period: "2026-07", value: { quantity: "50" }, page_region: "page 1", extraction_method: "human", extractor_version: "1", raw_value: "50 bags", normalized_value: "50", lineage: { candidate_fact_id: "cf_1", document_version_id: "docv_1", document_byte_digest: "sha256:fixture" } },
    conflicts: [], approval_history: [], supersession_chain: [],
  };
}

function isApproverOnlyRoute(path: string): boolean {
  return path === "/api/v1/approval-requests" || path.endsWith("/override-requests") || path.endsWith("/governance-timeline");
}

function problem(code: string, detail: string, status = 401): Record<string, unknown> {
  return { type: "about:blank", title: "Request rejected", status, detail, instance: "/", code, trace_id: "trace_fixture" };
}

function respond(response: import("node:http").ServerResponse, status: number, body: Record<string, unknown>): void {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

async function waitForNext(origin: string, child: ChildProcess): Promise<void> {
  let output = "";
  child.stdout?.on("data", (chunk: Buffer) => { output += chunk.toString(); });
  child.stderr?.on("data", (chunk: Buffer) => { output += chunk.toString(); });
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(origin);
      if (response.status > 0) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.fail("Next fixture server did not start: " + output);
}

async function unusedPort(): Promise<number> {
  const server = createTcpServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  await close(server);
  return address.port;
}

async function close(server: Server): Promise<void> {
  server.close();
  await once(server, "close");
}
