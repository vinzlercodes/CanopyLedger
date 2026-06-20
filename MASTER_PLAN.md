# CanopyLedger v1 Implementation Guide

**Authority:** The full, implementation-locked source of truth is
[CANOPYLEDGER_MASTER_PLAN.md](CANOPYLEDGER_MASTER_PLAN.md). This file is its condensed execution
guide and cannot override it.
**Status:** Approved architecture baseline. M0 artifacts lock implementation contracts.
**Baseline date:** 2026-06-21
**Progress tracker:** [PROGRESS.md](PROGRESS.md)

## 1. Product contract

CanopyLedger is an open-source lender-side reference system for calculating the evidence- and risk-adjusted lendable value of coffee inventory and receivables under a borrowing-base facility.

```text
mutable workspace
-> immutable evidence-complete snapshot
-> immutable deterministic stage outputs
-> recommendation
-> governed human decision
-> canonical report model
-> rendered artifacts
```

Standard build requires no foundation-model or LLM training, fine-tuning, GPU, proprietary data, live provider, or hosted model service. M6 may fit small CPU statistical models using synthetic data. Copilot and agent demonstrations default to deterministic, model-free behavior; optional BYO-model adapters may classify, plan, summarize, or explain, but never calculate or authorize.

### Non-goals

- Production loan management, core banking, ETRM/CTRM, trade execution, or regulatory filing.
- Legal collateral perfection, EUDR certification, or autonomous credit approval.
- Real borrower/farmer data or proprietary market-data redistribution.
- Production SSO, HA, multi-region, HSM, or formal regulatory certification in v1.

## 2. Architecture

- Python 3.12 application target; FastAPI, PostgreSQL/PostGIS, SQLAlchemy, Alembic.
- Next.js/TypeScript UI after M4 backend contracts stabilize.
- Modular monolith plus PostgreSQL-backed workers.
- `ObjectStore` port: local filesystem default; optional S3/MinIO implementation.
- Apache-2.0; synthetic data only.
- Separate DB roles: migration owner, application writer, pipeline writer, analytics reader, report reader.
- Immutable resources deny update/delete; corrections create superseding resources.

### Contractual and internal capacity

Contractual borrowing base (CBB) and internal risk capacity (IRC) are independently calculated, stored, exposed, and displayed. Neither overwrites the other.

```text
recommended_exposure_cap = min(
  facility_commitment,
  contractual_cbb,
  internal_irc,
  liquidity_cap,
  applicable_policy_caps
)
```

The decision records all uncapped values and the binding constraint.

## 3. Canonical Value Profile v1

- RFC 8785 controls JSON object-property ordering and primitive serialization.
- Decimals use fixed-point strings with schema-defined fractional digits.
- Valid: `0.00`, `0.25`, `-0.25`, `123.40`.
- Invalid: `00.25`, `.25`, `+0.25`, `-0.00`, `1e2`.
- Currency, unit, calculation scale, and rounding mode are separate fields.
- Default rounding is `ROUND_HALF_EVEN`; calculation contracts declare exceptions.
- Timestamps use `YYYY-MM-DDTHH:MM:SS.ffffffZ`; offsets normalize to `Z`; leap seconds are rejected.
- Unicode NFC version is pinned; lone surrogates and invalid Unicode are rejected.
- Arrays retain source order unless schema declares set semantics and a canonical sort key.
- Uploaded files hash original bytes.
- Domain-separated digest: `SHA256("canopyledger:<artifact>:v1\0" || canonical_bytes)`.
- Python and TypeScript implementations must pass shared test vectors.

## 4. Snapshot and pipeline contract

### Freeze transaction

One short serializable transaction:

1. Validate strong `If-Match`.
2. Protect working aggregate/version.
3. Validate critical facts and reconciliation.
4. Resolve market, policy, and computation bundles.
5. Create immutable snapshot and manifest.
6. Calculate canonical digest.
7. Insert pipeline-start outbox event.
8. Commit.

Retry the complete transaction on SQLSTATE `40001`. Never extract, call providers, value collateral, run scenarios, wait for workers, or render reports inside freeze. Snapshot is an immutable input package; stage outputs are separate immutable derived resources.

### Queue publication

Execution is at-least-once; authoritative publication is exactly once. A single transaction verifies the current `lease_epoch` and DB-time lease, inserts the uniquely constrained immutable output, marks the attempt complete, emits downstream outbox events, and commits. A stale attempt cannot publish.

```text
pipeline_stage
pipeline_stage_attempt
pipeline_stage_output
```

```text
UNIQUE(pipeline_run_id, stage_definition_id, stage_definition_version)
```

`SKIP LOCKED` is queue-only. Consumer inboxes deduplicate outbox messages. Dead-letter retry is explicit and audited.

## 5. Reproducibility

### Level A: bitwise replay

Guaranteed only on the designated reference image and hardware profile. Pin source/image/lock/computation digests; Python, PostgreSQL, PostGIS, GEOS, PROJ; OS, libc/libm, BLAS, CPU/FP mode; PRNG/seed/thread count; timezone/Unicode data; renderer/fonts/compression libraries.

### Level B: semantic replay

- Decimal outputs exact.
- Rules, reasons, and categorical decisions identical.
- Floating outputs within declared tolerances.
- Monte Carlo metrics within convergence limits.
- Published floats quantized to decimal strings.
- Canonical report-model JSON identical after quantization.
- PDF identity only inside the reference rendering envelope.

## 6. API v1 contract

Base path: `/api/v1`. IDs are type-prefixed UUIDv7 strings. Strong ETags use `"<type>:<id>:v<version>:<digest>"`.

```text
POST   /facilities
GET    /facilities/{facility_id}
PATCH  /facilities/{facility_id}
POST   /facilities/{facility_id}/snapshots
GET    /snapshots/{snapshot_id}
GET    /snapshots/{snapshot_id}/manifest
POST   /snapshots/{snapshot_id}/pipeline-runs
GET    /pipeline-runs/{run_id}
GET    /pipeline-runs/{run_id}/stages
GET    /snapshots/{snapshot_id}/valuations
GET    /snapshots/{snapshot_id}/eligibility-results
GET    /snapshots/{snapshot_id}/contractual-borrowing-bases
GET    /snapshots/{snapshot_id}/hedge-assessments
GET    /snapshots/{snapshot_id}/liquidity-assessments
GET    /snapshots/{snapshot_id}/scenario-results
GET    /snapshots/{snapshot_id}/internal-risk-capacities
POST   /recommendations/{id}/approval-requests
POST   /approval-requests/{id}/actions
POST   /recommendations/{id}/overrides
GET    /final-decisions/{id}
POST   /final-decisions/{id}/report-artifacts
GET    /report-artifacts/{id}
POST   /analytics/queries
GET    /analytics/queries/{id}
```

- RFC 9457 Problem Details with `code`, `trace_id`, and typed errors.
- Opaque base64url cursors; default 50, maximum 200 rows.
- Actor derives from authenticated principal; client-supplied actor is ignored.
- W3C `traceparent` propagates; UUIDv7 correlation ID is returned.
- OpenAPI v1 is versioned and generates the TypeScript client.
- Missing required `If-Match`: 428. Non-match: 412. Semantic rejection: 422. Idempotency fingerprint conflict: 409.
- Breaking API changes require a new major version; deprecated operations receive `Deprecation` and `Sunset` headers with at least 180 days support.

### Idempotency

CanopyLedger owns the normative contract. Scope is actor + operation + resource namespace + key. The fingerprint includes method, normalized path, selected headers, canonical schema version, normalized/defaulted body, and file content digests. Original status, headers, response, and fingerprint are retained. Financial-command keys have seven-year active retention followed by durable tombstones; reuse never silently gains new meaning.

## 7. Roadmap

### M0 - Normative foundation

State machine, invariant catalog, canonical profile, resource/database model, OpenAPI, error catalog, role matrix, calculation contracts, bundle schemas, acceptance-test catalog, charter, glossary, anti-goals, license, synthetic-data statement, and OSS evidence review.

### M1A - Integrity kernel

Working versions, snapshot freeze/manifest, bundle registry, canonicalization/digests, idempotency, outbox, fenced queue, immutable publication, replay harness.

### M1B - Initial domain pipeline

Inventory, receivables, market snapshots, valuation, eligibility, reserves, CBB, certificate JSON, golden fixtures.

### M2 - Evidence controls

Documents, candidate/approved facts, receipts, ownership, pledge, reconciliation, lineage, supersession.

### M3 - Hedge and liquidity

Versioned exchange contract master; separate KC/AC; Black-76 European benchmark; futures-adapted American recombining lattice; physical/futures/options/FX/basis/margin liquidity.

### M4A/M4B - Capacity and governance

Scenarios, Monte Carlo/ES, liquidity cap, independent IRC; then recommendation, approval, override, expiry, final decision, and initial UI.

### M5 - EUDR and climate

Evidence graph, PostGIS validation, three operator-date categories, climate adapters. Evidence status only, never compliance assertion.

### M6 - Credit early warning

Synthetic panel, CPU-trained logistic baseline/tree challenger, calibration, model governance. Output is `synthetic_stress_likelihood`, never PD.

### M7 - Document intelligence

Deterministic extraction, candidate facts, human verification, optional BYO extractor.

### M8 - Governed Analytics Copilot

Templates -> analytical plans -> deterministic SQL -> restricted direct SQL. Model-free default; optional BYO model cannot calculate or authorize. SQLGlot is analysis tooling, not security boundary.

### M9 - Governed agents

Deny-by-default capability registry and authenticated tool calls. Agents may plan, retrieve, summarize, explain, and route; never calculate authoritative values, mutate approved state, approve, override, trade, fund, or assert compliance.

### M10 - Reports and OSS release

Canonical report-model JSON, pinned rendering, `CURRENT_OFFICIAL` and `HISTORICAL_AUDIT` packages, one-command synthetic demo, documentation, tagged release.

## 8. Acceptance policy

Each milestone has executable acceptance tests in `docs/contracts/acceptance-tests.md`. Work is complete only when its tests, type checks, lint, migrations, API contract, replay evidence, and documentation pass. Lossless downgrades are tested; destructive migrations require forward-recovery, backup verification, and safety review.

## 9. Plan governance

- `CANOPYLEDGER_MASTER_PLAN.md` is the canonical approved plan; this guide summarizes it.
- Requirement changes are appended to the decision log before altering existing text.
- `PROGRESS.md` records implementation state, not replacement requirements.
- Every implementation commit updates progress evidence when milestone state changes.
- A milestone cannot be marked complete without command output or artifact links proving its gate.
