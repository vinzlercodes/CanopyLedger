# CanopyLedger v1 — Final Master Build Plan

> **Canonical document:** This file is the authoritative product, architecture, domain, governance, delivery, and testing plan for CanopyLedger v1.
>
> **Repository path:** `CANOPYLEDGER_MASTER_PLAN.md`
>
> **Intended use:** The root `AGENTS.md` should instruct Codex and other contributors to read this document before planning or implementing any substantial CanopyLedger change.
>
> **Status:** Implementation-locked master plan.
>
> **Last consolidated:** 2026-06-21.
>
> **Change control:** Any change that weakens an architectural invariant, alters the meaning of CBB or IRC, changes snapshot or bundle semantics, expands model or agent authority, or changes the source of truth for official reports must update this document and include an explicit architectural decision record.

---

## Document authority and interpretation

This document is the system-level source of truth for:

- product scope and anti-goals;
- domain language;
- architectural invariants;
- authoritative calculation ownership;
- immutable snapshot and publication semantics;
- policy, market, legal-interpretation, and computation bundles;
- Contractual Borrowing Base;
- hedge and liquidity calculations;
- scenario analysis and Internal Risk Capacity;
- climate, EUDR, and financed-emissions treatment;
- lightweight credit-model governance;
- document intelligence;
- approvals, overrides, and reporting;
- governed analytics and agents;
- milestone sequencing;
- testing and release gates.

When implementation and this plan conflict, do not silently rationalize the difference. Either:

1. correct the implementation to match the plan; or
2. formally approve and document a plan change, update this file, and record the decision.

Direct task instructions may specify a narrower implementation choice, but they must not silently weaken the non-negotiable invariants in this plan.

---

# 1. Executive definition

**CanopyLedger is a bank-side collateral, commodity-risk, credit, climate-evidence, and decision-governance operating system for coffee trade finance.**

It answers:

> **How much can a bank safely lend today against a coffee trader's inventory and receivables after contractual eligibility, reserves, commodity-price exposure, hedge coverage, liquidity stress, counterparty deterioration, climate risk, and EUDR evidence are considered?**

The canonical lifecycle is:

```text
mutable working facility
→ validated immutable snapshot
→ deterministic valuation and eligibility
→ contractual borrowing base
→ hedge and liquidity analysis
→ scenarios and internal risk capacity
→ bounded recommendation
→ governed human decision
→ reproducible report
```

The core design principle is:

> **Mutable working data becomes an immutable snapshot. Versioned deterministic engines calculate authoritative outputs. Models provide bounded advisory signals. Humans approve decisions. Reports reproduce frozen approved state.**

---

# 2. Product scope

## 2.1 Primary institution and use case

The primary institution is a bank or trade-finance lender providing a revolving borrowing-base facility to a mid-market coffee trader.

The first reference implementation models:

- one lending institution;
- one synthetic coffee trader;
- one revolving credit facility;
- four coffee-origin regions;
- approximately 20–30 inventory lots;
- approximately 10–20 receivables;
- warehouse receipts, invoices, contracts, insurance, and collateral documents;
- ICE Coffee C futures and options;
- both traditional `KC` and metric `AC` contract specifications;
- three to five deterministic stress scenarios;
- a small synthetic borrower history for credit early warning;
- a complete analyst-to-approver workflow;
- an official reproducible decision package.

## 2.2 Core users

| Role | Responsibilities |
|---|---|
| Collateral analyst | Maintains inventory, receivables, receipts, ownership, pledge, and reconciliations |
| Market-risk analyst | Reviews commodity pricing, basis, futures, options, FX, and liquidity |
| Credit analyst | Reviews borrower condition, scenarios, IRC, and recommendation |
| Climate/EUDR reviewer | Reviews origin, geolocation, traceability, evidence status, and climate indicators |
| Credit approver | Approves, rejects, or authorizes controlled overrides |
| Operations user | Monitors facility state, pipeline runs, stale data, and exceptions |
| Auditor/model-risk reviewer | Replays calculations and inspects lineage, bundles, and model artifacts |
| Administrator | Manages users, approved bundles, permissions, and controlled configuration |

## 2.3 Explicit anti-goals

CanopyLedger v1 is not:

- a core banking or loan-accounting system;
- a payment, funding, settlement, or trade-execution platform;
- an autonomous credit-underwriting engine;
- a legal opinion or EUDR compliance-certification service;
- a generic ESG reporting suite;
- a generic commodity-trading platform;
- a live market-data terminal;
- a multi-bank multi-tenant SaaS product in the first release;
- a foundation-model training project;
- a microservice demonstration;
- a replacement for human collateral, credit, compliance, or legal review.

---

# 3. Capabilities inherited from earlier projects

| Prior capability | CanopyLedger use |
|---|---|
| Coffee futures and options pricing | Mark collateral, value hedges, and calculate liquidity exposure |
| Cost of carry, Black–Scholes/Black–76, and Monte Carlo | Hedge valuation, option analysis, and scenario simulation |
| CVaR/Expected Shortfall and regime analysis | Internal risk capacity and tail-risk overlays |
| Counterparty and delinquency modelling | Borrower early-warning signals |
| Operational and credit-risk controls | Reconciliation, approvals, audit, and exception management |
| Financed-emissions analysis | Facility-level climate accounting |
| NGFS-style scenario design | Physical and transition-risk scenario overlays |
| EUDR and traceability research | Evidence graph and evidence-readiness assessment |
| Document extraction | Warehouse receipt, invoice, statement, and declaration ingestion |
| BIRD/Nemotron Text2SQL work | Evaluation methodology for governed analytical querying |
| Agent runtimes and approval gates | Controlled orchestration without autonomous finance decisions |
| Deterministic reporting work | Replayable committee packs and immutable decision evidence |

---

# 4. Final model-training decision

## 4.1 Locked position

The standard deployed runtime is **training-free**.

| Activity | Required? | Runtime dependency? |
|---|---:|---:|
| Foundation-model or LLM training | No | No |
| Text2SQL fine-tuning | No | No |
| Document-model fine-tuning | No | No |
| Lightweight statistical fitting for M6 | Yes, to reproduce the reference artifact from source | No |
| Optional bring-your-own inference model | Optional | Optional and non-authoritative |

M6 Credit Early Warning includes one small offline CPU-only fitting workflow:

- logistic-regression baseline;
- optional shallow-tree challenger;
- optional probability calibration;
- synthetic data in the public reference build;
- borrower-level temporal split;
- fixed seeds;
- versioned feature schema;
- serialized preprocessing and estimator artifact;
- model card;
- local deterministic inference.

No GPU, neural model, distributed training, online learning, external model provider, or model server is required.

A normal operator may deploy an approved pre-fitted bundle. A developer or reviewer may reproduce it with:

```bash
make fit-credit-reference-model
```

The output is a **versioned computation artifact**, not a decision-maker.

## 4.2 Why a small statistical fit remains in scope

The M6 fit exists to demonstrate:

- temporal validation;
- leakage controls;
- calibration;
- baseline/challenger governance;
- feature-schema versioning;
- reason-code stability;
- model-card production;
- the separation between an advisory prediction and an authoritative lending decision.

The output must be labelled:

> **Synthetic borrower deterioration likelihood**

It may not:

- alter collateral eligibility;
- change contractual reserves;
- calculate CBB;
- approve a facility;
- change a final decision;
- reduce or increase availability automatically.

## 4.3 Text2SQL decision

CanopyLedger does not train a Text2SQL model.

The standard analytical path is:

```text
approved question templates
→ structured analytical plan
→ deterministic SQL compiler
→ restricted analyst-authored SQL fallback
```

An optional model may:

- classify question intent;
- choose an approved template;
- populate a typed analytical plan;
- explain deterministic results.

It may not:

- define business metrics;
- invent policy;
- generate authoritative financial values;
- modify CBB or IRC rules;
- execute arbitrary SQL;
- mutate approved state;
- approve or override decisions.

---

# 5. Architectural constitution

## 5.1 Non-negotiable invariants

1. Working data may be mutable; frozen snapshots may not be.
2. A snapshot contains inputs and references, not calculated outputs.
3. Snapshot freeze is short, transactional, and free of external calls.
4. Every snapshot pins market, policy, legal-interpretation, and computation bundles.
5. Authoritative finance values come only from deterministic calculation code.
6. Published stage outputs are immutable.
7. Corrections create superseding resources and never rewrite history.
8. Unverified critical evidence cannot enter a valid snapshot.
9. A failed stage leaves prior published outputs untouched.
10. Contractual Borrowing Base and Internal Risk Capacity remain separate concepts.
11. A recommendation is not a decision.
12. A final decision requires an authorized human action.
13. An override preserves the original recommendation, rules, and outputs.
14. Reports read frozen approved resources and never recalculate finance.
15. Agents and copilots cannot become an authorization mechanism.
16. Pipeline execution is at least once; publication is effectively exactly once.
17. Every official number traces to inputs, policy, calculation version, and code.
18. Critical conflicts fail closed rather than being guessed through.
19. Versioned bundles are immutable after approval.
20. Every official artifact is content-addressed or references content-addressed components.
21. Market staleness is explicit and policy-evaluated.
22. Legal and regulatory interpretations are versioned operational policy, not live web assumptions.
23. Report rendering cannot read current mutable facility state.
24. No model output is authoritative merely because it is confident.

## 5.2 Canonical lifecycle

```text
DRAFT WORKSPACE
   │
   ├─ edit facility
   ├─ ingest documents
   ├─ review candidate facts
   ├─ reconcile collateral
   └─ resolve critical conflicts
   │
   ▼
FREEZE REQUEST
   │
   ├─ optimistic-concurrency check
   ├─ validation
   ├─ approved-bundle resolution
   ├─ manifest creation
   └─ canonical digest
   │
   ▼
IMMUTABLE SNAPSHOT
   │
   ▼
DETERMINISTIC PIPELINE
   │
   ├─ market normalization
   ├─ valuation
   ├─ eligibility
   ├─ reserves and CBB
   ├─ hedge and liquidity
   ├─ scenarios and IRC
   ├─ climate/EUDR
   ├─ credit signal
   └─ recommendation
   │
   ▼
HUMAN GOVERNANCE
   │
   ├─ approve
   ├─ reject
   ├─ request changes
   └─ override with required control
   │
   ▼
FINAL DECISION
   │
   ▼
CANONICAL REPORT MODEL
   │
   ├─ PDF
   ├─ HTML
   └─ machine-readable package
```

---

# 6. Technical architecture

## 6.1 Deployment shape

```text
┌─────────────────────────────────────────────────┐
│ Next.js web                                     │
│ Cockpit · Evidence · Hedge · Scenarios · Approval│
└──────────────────────┬──────────────────────────┘
                       │ HTTPS/JSON
┌──────────────────────▼──────────────────────────┐
│ FastAPI application                             │
│ commands · queries · auth · bundle registry     │
└──────────────┬──────────────────────┬────────────┘
               │                      │
┌──────────────▼──────────┐  ┌────────▼───────────┐
│ PostgreSQL + PostGIS    │  │ Object storage     │
│ canonical state         │  │ local/S3/MinIO     │
│ jobs/outbox/audit       │  │ original documents │
└──────────────┬──────────┘  └────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ Python worker                                   │
│ deterministic stages · reports · adapters       │
└─────────────────────────────────────────────────┘
```

## 6.2 Core stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API | FastAPI |
| Contracts | Pydantic and JSON Schema |
| Database | PostgreSQL with PostGIS |
| Migrations | Alembic |
| Quantitative computing | NumPy and SciPy where needed |
| Data transformation | Polars or Pandas where justified |
| Statistical fitting | scikit-learn, CPU only |
| SQL parsing | SQLGlot for AST inspection |
| Web | Next.js and TypeScript |
| Object storage | Filesystem through an object-storage port; optional S3/MinIO adapter |
| Reports | Canonical JSON plus pinned HTML/PDF rendering |
| Packaging | Docker/Compose reference environment |
| Testing | Pytest, property tests, contract tests, migration tests, and browser tests |

The standard build deliberately has:

- no Redis requirement;
- no Kafka requirement;
- no Temporal requirement;
- no vector database;
- no model server;
- no live third-party API dependency for the canonical demo.

## 6.3 Suggested repository

```text
canopyledger/
├── AGENTS.md
├── README.md
├── apps/
│   ├── api/
│   ├── worker/
│   ├── web/
│   └── cli/
├── packages/
│   ├── canopy_domain/
│   ├── canopy_application/
│   ├── canopy_canonical/
│   ├── canopy_persistence/
│   ├── canopy_jobs/
│   ├── canopy_evidence/
│   ├── canopy_market/
│   ├── canopy_valuation/
│   ├── canopy_collateral/
│   ├── canopy_hedge/
│   ├── canopy_scenarios/
│   ├── canopy_credit/
│   ├── canopy_climate/
│   ├── canopy_documents/
│   ├── canopy_analytics/
│   ├── canopy_agents/
│   ├── canopy_reporting/
│   └── canopy_shared_contracts/
├── policies/
│   ├── eligibility/
│   ├── reserves/
│   ├── approvals/
│   ├── climate/
│   └── legal_interpretation/
├── computation_bundles/
├── market_fixtures/
├── scenarios/
├── synthetic_data/
├── tests/
│   ├── golden/
│   ├── property/
│   ├── replay/
│   ├── security/
│   ├── migrations/
│   └── browser/
├── docs/
│   ├── architecture/
│   ├── domain/
│   ├── calculations/
│   ├── governance/
│   ├── threat-model/
│   └── roadmap.md
├── scripts/
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

Python owns authoritative calculations and workflow services. TypeScript owns presentation and browser contracts but must not independently reimplement authoritative finance formulas.

## 6.4 Module boundaries

### `canopy_domain`

Owns:

- domain types;
- resource identifiers;
- state machines;
- invariants;
- domain errors;
- value objects;
- reason-code types.

Must not depend on:

- FastAPI;
- SQLAlchemy;
- object storage;
- external APIs;
- UI code.

### `canopy_application`

Owns:

- commands;
- queries;
- use cases;
- authorization checks;
- transaction boundaries;
- orchestration across domain ports.

### `canopy_persistence`

Owns:

- SQLAlchemy mappings;
- repository implementations;
- migration-facing persistence concerns;
- database constraints;
- lock and transaction helpers.

### Calculation packages

Each authoritative stage package owns:

- typed input contract;
- typed output contract;
- formula version;
- validation;
- deterministic calculation;
- reason codes;
- lineage;
- golden and property tests.

### Adapter packages

External data, object storage, optional model providers, and report renderers must sit behind explicit ports. Domain code must remain usable without those adapters.

---

# 7. Canonical values, hashing, and reproducibility

## 7.1 Canonical Value Profile v1

Use RFC 8785-style deterministic JSON serialization plus finance-specific constraints.

Rules:

- Use `Decimal` for money, quantity, rates, prices, percentages, and contractual calculations.
- Never use binary floating point for authoritative persisted financial fields.
- Serialize decimals as fixed-point strings.
- Prohibit exponent notation in canonical artifacts.
- Prohibit a leading plus sign.
- Prohibit negative zero.
- Declare exact scale in the schema.
- Store currency, quantity unit, and price unit explicitly.
- Default authoritative rounding is `ROUND_HALF_EVEN`.
- A calculation contract may declare a different rounding rule explicitly.
- Store timestamps in UTC RFC 3339 with exactly six fractional digits.
- Normalize structured strings to Unicode NFC.
- Never normalize uploaded document bytes before hashing.
- Every collection declares a canonical sort key.
- Every database query feeding a canonical artifact uses explicit ordering.

Domain-separated digest:

```text
SHA256(
  "canopyledger:<artifact-type>:v1\0"
  || canonical_bytes
)
```

Examples:

```text
canopyledger:snapshot:v1
canopyledger:market-bundle:v1
canopyledger:policy-bundle:v1
canopyledger:stage-output:v1
canopyledger:report-model:v1
```

Python and TypeScript canonicalization test vectors must agree byte-for-byte.

## 7.2 Reproducibility levels

### Level A — bitwise replay

Bitwise replay requires pinning:

- Git commit;
- container image digest;
- Python and dependency versions;
- computation bundle;
- policy bundle;
- market bundle;
- legal-interpretation bundle;
- PRNG implementation and version;
- seed derivation;
- CPU architecture;
- thread count;
- locale and timezone;
- report renderer;
- fonts;
- templates;
- compression and metadata settings.

### Level B — semantic replay

Across supported environments:

- Decimal values match exactly.
- Rules and reason codes match exactly.
- Categorical decisions match exactly.
- Floating-point analytical values meet declared tolerances.
- Monte Carlo estimates meet convergence tolerances.
- Published values match after declared quantization.
- Canonical report-model JSON matches.
- PDF bytes may differ outside the pinned rendering envelope.

## 7.3 Time

- Business event time and record creation time are distinct fields.
- Tests use an injected clock.
- Canonical calculations may not call the system clock directly.
- Report generation may not insert a current timestamp unless the timestamp is presentation metadata excluded from the canonical report-model digest.
- Market observation time, ingestion time, approval time, and snapshot time remain separate.

---

# 8. Mutable working state and immutable snapshots

## 8.1 Working aggregate

```text
FacilityWorkingAggregate
├── facility terms
├── borrower and guarantor facts
├── inventory lots
├── receivables
├── warehouse receipts
├── hedge positions
├── market-data selection
├── documents and candidate facts
├── approved facts
├── climate/EUDR evidence
└── working version
```

Every mutation increments the aggregate version.

Clients submit:

```http
If-Match: "facility-version-42"
```

A stale version returns:

```http
412 Precondition Failed
```

## 8.2 Freeze transaction

Freeze runs in one short retryable `SERIALIZABLE` transaction:

1. Authenticate and authorize the actor.
2. Verify `If-Match`.
3. Protect the current working version.
4. Validate facility terms.
5. Validate approved critical facts.
6. Validate inventory and receivables reconciliation.
7. Reject unresolved critical conflicts.
8. Resolve approved market, policy, legal, and computation bundles.
9. Create the immutable snapshot.
10. Create the snapshot manifest.
11. Calculate the canonical snapshot digest.
12. Insert the pipeline-start outbox event.
13. Commit.

A serialization failure retries the entire transaction from the beginning.

Freeze must not perform:

- document extraction;
- network requests;
- market-data downloads;
- valuation;
- scenario generation;
- statistical inference;
- report rendering;
- worker waiting;
- calls to an LLM or external model.

## 8.3 Snapshot manifest

```json
{
  "snapshot_id": "snap_...",
  "facility_id": "fac_...",
  "working_version": 42,
  "schema_version": "1.0",
  "market_bundle_digest": "sha256:...",
  "policy_bundle_digest": "sha256:...",
  "legal_interpretation_bundle_digest": "sha256:...",
  "computation_bundle_digest": "sha256:...",
  "approved_fact_ids": ["fact_..."],
  "document_digests": ["sha256:..."],
  "created_by": "actor_...",
  "created_at": "2026-06-21T12:00:00.000000Z",
  "snapshot_digest": "sha256:..."
}
```

A snapshot stores immutable references and copied immutable values required to reproduce the pipeline. It does not point to mutable working rows as its source of truth.

---

# 9. Jobs, outbox, and publication semantics

## 9.1 Required guarantee

> **At-least-once execution and effectively exactly-once immutable publication.**

## 9.2 Queue design

Use PostgreSQL-backed leased jobs with:

- atomic claim through `FOR UPDATE SKIP LOCKED`;
- monotonic `lease_epoch`;
- lease expiration;
- bounded heartbeat;
- maximum lease lifetime;
- deterministic `run_key`;
- unique stage-run constraints;
- unique published-output constraints;
- transactional outbox;
- consumer inbox/deduplication;
- audited retries;
- dead-letter status.

A stale worker may continue computing locally but cannot publish after its lease epoch is superseded.

## 9.3 Publication transaction

A stage publishes only if:

- the job still owns the current lease epoch;
- all input references match the run contract;
- no output already exists for the unique publication key;
- the stage result validates against the versioned output schema;
- all digests are successfully calculated.

Publication and outbox insertion occur in one database transaction.

## 9.4 Failure behavior

- Stage failure creates an immutable attempt record.
- A failed retry does not delete a prior successful output.
- Retrying with the same input and code may reuse or verify an existing identical output.
- A conflicting output for the same publication key is a critical integrity failure.
- Dead-lettering is visible to operators and does not silently skip a stage.
- Pipeline completion requires every mandatory stage to have a valid published output.

---

# 10. Domain model

## 10.1 Facility and parties

```text
Facility
FacilityWorkingAggregate
FacilityTerms
Borrower
Guarantor
Obligor
FacilityLimit
Covenant
Utilization
LetterOfCreditExposure
```

## 10.2 Inventory and receivables

```text
InventoryLot
Warehouse
WarehouseReceipt
InventoryOwnershipClaim
PledgeRecord
QualityGrade
Origin
PurchaseContract
Receivable
ReceivableInvoice
ReceivableObligor
PaymentRecord
```

## 10.3 Evidence

```text
Document
DocumentVersion
DocumentByteDigest
CandidateFact
ApprovedFact
RejectedFact
FactCorrection
EvidenceLink
ReconciliationIssue
```

## 10.4 Market and hedge

```text
MarketSnapshot
FXRate
FuturesSettlement
VolatilityInput
InterestRateInput
BasisInput
ExchangeContractSpecification
PhysicalExposure
FuturesPosition
OptionPosition
HedgeBook
```

## 10.5 Governance and derived resources

```text
Snapshot
SnapshotManifest
PipelineDefinition
PipelineRun
StageRun
StageOutput
CBBResult
HedgeLiquidityResult
ScenarioResult
IRCResult
CreditSignal
ClimateEvidenceResult
Recommendation
ApprovalRequest
ApprovalAction
OverrideRequest
FinalDecision
ReportModel
RenderedArtifact
AuditEvent
```

## 10.6 Candidate and approved facts

Document extraction never changes authoritative facility facts directly.

```text
document
→ candidate fact
→ reconciliation and human review
→ approved fact
→ future snapshot eligibility
```

An approved fact is immutable.

A correction creates:

```text
ApprovedFact v1
  superseded_by → ApprovedFact v2
```

Historical snapshots continue to reference the fact version originally approved for them.

## 10.7 State machines

### Evidence fact

```text
candidate
→ approved
→ superseded

candidate
→ rejected
```

### Pipeline run

```text
pending
→ running
→ succeeded

pending/running
→ failed
→ retry_requested
→ running
```

### Approval request

```text
requested
→ approved
→ decision_created

requested
→ rejected

requested
→ expired

requested
→ cancelled
```

### Final decision

```text
active
→ superseded

active
→ expired
```

A rejected, expired, or superseded decision cannot be represented as the current official decision.

---

# 11. Versioned bundle architecture

Every snapshot pins four major bundle types.

## 11.1 Market bundle

Contains:

- futures settlements;
- FX rates;
- volatility inputs;
- interest rates;
- basis inputs;
- exchange-contract specifications;
- observation timestamps;
- data-source references;
- staleness state;
- bundle digest.

No calculation may silently query a newer market value than the one pinned to the snapshot.

## 11.2 Policy bundle

Contains:

- inventory eligibility rules;
- receivables eligibility rules;
- advance rates;
- concentration limits;
- reserve rules;
- documentation requirements;
- approval thresholds;
- scenario thresholds;
- recommendation rules;
- reason-code catalogue.

Rules are typed Python primitives with schema-validated parameter files.

Example:

```yaml
inventory:
  max_document_age_days: 30
  advance_rate_by_grade:
    specialty: "0.75"
    commercial: "0.65"

receivables:
  max_age_days: 90
  cross_aging_threshold: "0.25"
  single_obligor_concentration: "0.20"
```

Configuration files provide parameters. They must not become a general-purpose expression language.

## 11.3 Computation bundle

Contains:

- calculation package versions;
- formula-contract versions;
- unit-conversion table;
- rounding specifications;
- scenario-engine version;
- PRNG version;
- approved credit-model artifact;
- model feature schema;
- report-model compiler version;
- source or container digests.

## 11.4 Legal-interpretation bundle

Contains the institution's approved operational interpretation of:

- EUDR evidence requirements;
- applicable dates;
- country-risk references;
- traceability fields;
- evidence freshness;
- review stop conditions;
- legal-review disclaimers.

Legal or regulatory changes require a new approved bundle. Historical snapshots retain the earlier bundle.

## 11.5 Bundle lifecycle

```text
draft
→ validated
→ approved
→ active
→ superseded
```

An approved bundle is immutable. Activation and supersession are separate governance actions.

---

# 12. Deterministic calculation pipeline

## 12.1 Stage graph

```text
S0 Snapshot Validation
        │
        ▼
S1 Market Normalization
        │
        ▼
S2 Inventory and Receivables Valuation
        │
        ▼
S3 Eligibility and Reserves
        │
        ▼
S4 Contractual Borrowing Base
        │
        ├───────────────┐
        ▼               ▼
S5 Hedge/Liquidity   S6 Climate/EUDR
        │               │
        └───────┬───────┘
                ▼
         S7 Scenario Engine
                │
                ▼
         S8 Internal Risk Capacity
                │
                ├──── S9 Credit Signal
                │
                ▼
         S10 Recommendation
```

Every stage:

- accepts immutable references;
- declares an input schema and output schema;
- declares a formula or logic version;
- emits reason codes and warnings;
- records lineage;
- publishes one immutable output;
- is independently replayable.

## 12.2 Stage output contract

```json
{
  "stage_output_id": "out_...",
  "snapshot_id": "snap_...",
  "stage": "inventory_valuation",
  "stage_version": "1.2.0",
  "input_digests": ["sha256:..."],
  "policy_bundle_digest": "sha256:...",
  "computation_bundle_digest": "sha256:...",
  "result": {},
  "warnings": [],
  "reason_codes": [],
  "started_at": "...",
  "completed_at": "...",
  "output_digest": "sha256:..."
}
```

Stage output schemas are append-only within a major version. Breaking changes require a new major version and migration/replay strategy.

---

# 13. Units, currencies, and valuation

## 13.1 Unit normalization

Source quantities retain original units. Calculation inputs convert using a versioned unit table.

Examples:

```text
bags → kilograms
kilograms → metric tonnes
metric tonnes → pounds
local currency → facility currency
cents per pound → USD per pound
USD per tonne → USD per pound
```

Every conversion records:

- input value;
- input unit;
- factor;
- output value;
- output unit;
- conversion-table version.

## 13.2 Inventory mark

A simplified lot reference price is:

\[
\text{ReferencePrice}_i =
\text{FuturesPrice}_{c(i)}
+
\text{BasisDifferential}_i
-
\text{QualityDiscount}_i
\]

\[
\text{GrossMarketValue}_i =
\text{EligibleQuantity}_i
\times
\text{ReferencePrice}_i
\times
\text{FXConversion}_i
\]

Depending on policy:

\[
\text{CollateralValue}_i =
\min(
\text{GrossMarketValue}_i,
\text{DocumentedCost}_i,
\text{InsuredValue}_i
)
\]

The lower-of-market, cost, or insured-value rule is policy-controlled and not universal hard-coded behavior.

## 13.3 Inventory eligibility

A lot may be excluded or haircut because of:

- missing approved warehouse receipt;
- duplicate receipt;
- unresolved ownership;
- missing or defective pledge;
- quantity mismatch;
- unapproved warehouse;
- stale inspection;
- excess age;
- quality mismatch;
- insurance deficiency;
- origin or country restriction;
- concentration limit;
- EUDR evidence stop condition;
- prior lien;
- unresolved document conflict.

\[
\text{AdvancedInventoryValue}_i =
\text{EligibleCollateralValue}_i
\times
\text{InventoryAdvanceRate}_i
\]

## 13.4 Receivables eligibility

A receivable may be excluded or reduced for:

- excess age;
- past-due status;
- cross-aging;
- dispute;
- related-party obligor;
- missing delivery evidence;
- foreign-currency mismatch;
- obligor concentration;
- credit-insurance deficiency;
- prohibited jurisdiction;
- duplicate assignment.

\[
\text{AdvancedReceivableValue}_j =
\text{EligibleReceivableAmount}_j
\times
\text{ReceivableAdvanceRate}_j
\]

Concentration excess must be separately reported rather than hidden inside an aggregate amount.

---

# 14. Contractual Borrowing Base

## 14.1 Definition

The **Contractual Borrowing Base**, or `CBB`, is produced only from the facility agreement's approved collateral and reserve rules.

\[
\text{GrossAdvancedCollateral} =
\sum_i \text{AdvancedInventoryValue}_i
+
\sum_j \text{AdvancedReceivableValue}_j
\]

\[
\text{CBB} =
\max(
0,
\text{GrossAdvancedCollateral}
-
\text{ContractualReserves}
)
\]

Potential reserves include:

- prior-lien reserve;
- freight and landing-cost reserve;
- taxes and duties;
- unpaid warehouse charges;
- insurance deficiency;
- quality or shrinkage reserve;
- documentation reserve;
- receivables dilution reserve;
- FX mismatch reserve;
- contractual hedge reserve;
- concentration reserve.

## 14.2 Contractual availability

\[
\text{ContractualExposureLimit} =
\min(
\text{FacilityCommitment},
\text{CBB}
)
\]

\[
\text{ContractualAvailability} =
\max(
0,
\text{ContractualExposureLimit}
-
\text{CurrentPrincipal}
-
\text{LCExposure}
-
\text{OtherContractualUsage}
)
\]

The CBB output includes:

- gross collateral;
- eligible collateral;
- ineligible collateral;
- advance rates;
- each reserve;
- commitment cap;
- utilization;
- availability;
- formula lineage;
- reason codes;
- output digest.

## 14.3 Required properties

Unless an explicitly documented policy interaction explains otherwise:

- removing eligible collateral cannot increase CBB;
- increasing a reserve cannot increase CBB;
- increasing utilization cannot increase availability;
- reducing an advance rate cannot increase CBB;
- making a receivable older cannot improve eligibility;
- adding a critical unresolved conflict cannot permit freeze;
- duplicate collateral cannot be counted twice;
- negative availability is floored at zero;
- a facility commitment cap cannot be exceeded.

---

# 15. Hedge and liquidity engine

## 15.1 Exchange-contract specifications

Exchange specifications are versioned data, not constants hidden in calculation code.

```text
exchange
product_code
contract_symbol
contract_size
contract_size_unit
price_unit
tick_size
currency
exercise_style
delivery_months
effective_from
effective_to
source_document_digest
```

The traditional ICE Coffee C `KC` contract and the metric `AC` contract are distinct products. They must never be treated as interchangeable.

## 15.2 Exposure

```text
physical exposure
+ purchase commitments
- sales commitments
+ futures delta
+ option delta
= net price exposure
```

Outputs include:

- gross physical exposure;
- futures exposure;
- option delta-equivalent;
- FX exposure;
- basis exposure;
- hedge ratio;
- over-hedge or under-hedge amount;
- delivery-month mismatch;
- concentration by month.

## 15.3 Futures valuation

\[
\text{FuturesPnL} =
N
\times
Q
\times
(F_t-F_0)
\times
\text{PriceUnitFactor}
\]

where:

- \(N\) is contract count;
- \(Q\) is contract size;
- \(F_t\) is current futures price;
- \(F_0\) is entry price.

## 15.4 Options

Black–76 is a transparent European reference:

\[
C=e^{-rT}[F N(d_1)-K N(d_2)]
\]

\[
d_1=
\frac{\ln(F/K)+\frac{1}{2}\sigma^2T}
{\sigma\sqrt{T}},
\qquad
d_2=d_1-\sigma\sqrt{T}
\]

The authoritative v1 American option calculation uses a recombining Cox–Ross–Rubinstein lattice.

Tests must cover:

- American value not below comparable European value;
- lattice convergence;
- early-exercise behavior;
- near-expiry behavior;
- deep in/out-of-the-money cases;
- low-volatility cases;
- zero or near-zero rates;
- stable Greeks;
- independent reference comparison.

An external library may be used as a CI reference but must not be the sole untested source of correctness.

## 15.5 Variation-margin liquidity

A hedge may reduce economic price risk while increasing cash demands.

\[
\text{VMStress} =
|N|
\times
Q
\times
|\Delta F_{\text{stress}}|
\]

Outputs include:

- one-day and multi-day margin stress;
- available cash;
- undrawn contractual availability;
- timing mismatch;
- margin-call shortfall;
- liquidity coverage ratio;
- required liquidity reserve.

The system must never represent “more hedged” as automatically “safer” without showing liquidity consequences.

---

# 16. Scenario engine and Internal Risk Capacity

## 16.1 Scenario library

### Base case

Current approved market and borrower assumptions.

### Price-decline stress

- coffee-price decline;
- receivables collection delay;
- collateral revaluation;
- reduced CBB.

### Supply-shock or rally stress

- coffee-price increase;
- futures margin calls;
- basis widening;
- liquidity pressure.

### Climate-production stress

- origin-level yield disruption;
- quality deterioration;
- shipment delay;
- replacement-cost increase.

### Evidence or transition stress

- EUDR evidence deficiency;
- delayed sale into an EU-linked channel;
- inventory ineligibility or added reserve;
- working-capital-cycle extension.

## 16.2 Deterministic scenario contract

Every scenario pins:

- shock values;
- correlation assumptions;
- revaluation ordering;
- policy response;
- scenario version;
- input bundle;
- output quantization.

## 16.3 Monte Carlo

Monte Carlo is for internal risk analysis, not contractual CBB.

Pin:

- PRNG family and version;
- seed derivation;
- path count;
- time steps;
- thread count;
- correlation matrix;
- distribution assumptions;
- regime or scenario mixture;
- quantization scale.

Metrics include:

\[
\text{VaR}_{\alpha}
\]

\[
\text{Expected Shortfall}_{\alpha}
=
E[L \mid L \geq \text{VaR}_{\alpha}]
\]

Also calculate:

- probability of borrowing-base deficiency;
- probability of margin-liquidity shortfall;
- expected collateral shortfall;
- worst scenario families;
- tail contribution by factor;
- hedge-effectiveness distribution.

## 16.4 Internal Risk Capacity

The **Internal Risk Capacity**, or `IRC`, is an internal bank-risk measure and not a contractual figure.

An illustrative structure is:

\[
\text{RiskBuffer} =
\text{TailLossBuffer}
+
\text{LiquidityBuffer}
+
\text{CounterpartyBuffer}
+
\text{ClimateEvidenceBuffer}
\]

\[
\text{UncappedIRC} =
\max(0,\text{CBB}-\text{RiskBuffer})
\]

\[
\text{IRC} =
\min(
\text{CBB},
\text{FacilityCommitment},
\text{UncappedIRC}
)
\]

The final formula is policy-bundle controlled.

Required invariant:

\[
\text{IRC} \leq \text{CBB}
\]

CBB and IRC require:

- different domain types;
- different tables;
- different API resources;
- different pipeline stages;
- different UI panels;
- different reason-code namespaces.

A generic `capacity` field is prohibited.

---

# 17. Credit early warning

## 17.1 Target

The M6 reference artifact estimates deterioration within a defined 90-day horizon.

A synthetic target event may include:

- missed interest;
- borrowing-base deficiency;
- covenant breach;
- material payment delay;
- margin-call failure;
- receivables deterioration;
- watchlist transfer.

The exact target definition is part of the model bundle.

## 17.2 Feature groups

### Financial

- leverage;
- liquidity ratio;
- interest coverage;
- profitability;
- working-capital cycle;
- cash-flow volatility.

### Behavioural

- payment delays;
- reporting delays;
- covenant exceptions;
- document exceptions;
- frequency of collateral corrections;
- utilization pattern.

### Market-sensitive

- coffee-price shock;
- hedge ratio;
- basis volatility;
- margin-liquidity requirement;
- FX mismatch;
- inventory aging.

### Climate and evidence

- origin concentration;
- weather anomaly;
- traceability gaps;
- evidence staleness;
- EUDR evidence readiness;
- financed-emissions data quality.

## 17.3 Fitting workflow

```text
synthetic panel generation
→ schema validation
→ borrower-level temporal split
→ leakage audit
→ preprocessing fit
→ logistic baseline
→ shallow-tree challenger
→ optional calibration
→ evaluation
→ reason-stability tests
→ artifact packaging
→ model card
→ approval
```

Required evaluation:

- ROC-AUC;
- PR-AUC;
- Brier score;
- calibration curve;
- precision and recall at policy thresholds;
- time stability;
- segment performance;
- leakage report;
- reason-code stability;
- baseline/challenger comparison.

## 17.4 Runtime output

```json
{
  "signal_type": "synthetic_deterioration_likelihood",
  "horizon_days": 90,
  "probability": "0.1842",
  "band": "moderate",
  "top_reason_codes": [
    "LIQUIDITY_COVERAGE_DECLINE",
    "RECEIVABLE_DAYS_RISING",
    "MARGIN_STRESS_INCREASE"
  ],
  "model_bundle_digest": "sha256:...",
  "advisory_only": true
}
```

A credit signal may affect a recommendation only through an approved policy rule. It cannot directly alter CBB.

---

# 18. Climate, EUDR, and financed emissions

## 18.1 Evidence graph

```text
inventory lot
→ purchase contract
→ supplier
→ producer/farm/cooperative
→ geolocation or production area
→ production period
→ shipment
→ warehouse receipt
→ customer/market channel
→ supporting documents
```

Checks include:

- geometry validity;
- point or polygon consistency;
- duplicate coordinates;
- missing supplier or producer link;
- missing production date;
- country-risk reference;
- document freshness;
- chain-of-custody gaps;
- contradictory origin;
- unsupported lot split or merge;
- lineage to original document bytes.

PostGIS performs spatial validation.

## 18.2 Evidence status, not legal conclusion

CanopyLedger may report:

```text
complete
incomplete
conflicting
stale
not reviewed
review required
```

It must not assert:

```text
legally compliant
certified deforestation-free
approved for EU placement
```

Regulatory dates and interpretations belong in an approved legal-interpretation bundle.

## 18.3 Climate scenarios

Support:

- origin concentration;
- drought and excess-rainfall indicators;
- temperature anomaly;
- shipment disruption;
- yield or quality shock;
- physical-risk overlay;
- transition or evidence-cost overlay.

Global climate scenarios may inform design, but institution-specific coffee-trade shocks must be explicit. Do not imply that a global scenario mechanically determines a single borrower's result.

## 18.4 Financed emissions

\[
\text{FinancedEmissions}
=
\text{AttributionFactor}
\times
\text{BorrowerEmissions}
\]

The methodology bundle defines:

- denominator;
- asset-class treatment;
- scope coverage;
- data-quality scoring;
- estimation approach;
- restatement treatment.

Outputs include:

- attribution factor;
- Scope 1;
- Scope 2;
- available Scope 3;
- financed-emissions result;
- data-quality score;
- source period;
- estimation method;
- missing-data warnings;
- methodology version;
- restatement lineage.

Financed emissions do not directly alter CBB. A transition-risk scenario may use them only through approved policy.

---

# 19. Document intelligence

## 19.1 Supported document types

- warehouse receipts;
- inventory statements;
- purchase contracts;
- sales invoices;
- receivables aging reports;
- borrower financial statements;
- insurance certificates;
- inspection reports;
- origin and traceability declarations;
- hedge statements;
- facility notices.

## 19.2 Processing priority

```text
deterministic known template
→ schema-guided parser
→ text/table extraction
→ optional model-assisted candidate extraction
→ human review
```

Model or parser output is a candidate fact, never an approved fact.

## 19.3 Provenance

Every candidate fact records:

- document ID and version;
- original byte digest;
- page or region;
- extraction method;
- extractor version;
- raw value;
- normalized value;
- confidence where applicable;
- review status;
- reviewer;
- approval or rejection reason.

## 19.4 Critical facts

Examples:

- inventory quantity;
- warehouse receipt number;
- ownership;
- pledge status;
- receivable amount;
- obligor;
- currency;
- contract maturity;
- facility limit;
- utilization;
- hedge symbol and quantity;
- origin or geolocation when policy requires it.

Critical facts must be approved or deterministically reconciled before freeze.

## 19.5 Document security

Treat all document text as untrusted data.

- Do not execute embedded instructions.
- Do not let document content alter agent permissions.
- Do not interpolate untrusted content into SQL.
- Virus/malware scanning is an adapter concern and should be enabled in production.
- Validate MIME type and file signature.
- Enforce file-size and page-count limits.
- Store original bytes immutably.
- Generate previews as separate derived artifacts.

---

# 20. Recommendation and decision governance

## 20.1 Recommendation

Possible recommendation classes:

```text
APPROVE
APPROVE_WITH_CONDITIONS
REDUCE_REQUESTED_DRAW
REQUIRE_ADDITIONAL_COLLATERAL
REQUIRE_HEDGE_ADJUSTMENT
REQUIRE_LIQUIDITY_BUFFER
INCREASE_MONITORING
DEFER_PENDING_EVIDENCE
DECLINE
```

A recommendation contains:

- requested amount;
- contractual availability;
- IRC;
- recommended incremental draw;
- conditions;
- reason codes;
- referenced outputs;
- policy bundle;
- expiry;
- author;
- immutable digest.

## 20.2 Human decision

A final decision requires:

- authorized actor;
- current unexpired approval request;
- current recommendation;
- approved snapshot;
- required separation of duties;
- structured reason.

No self-approval:

```text
recommendation_author != final_approver
```

## 20.3 Override

An override preserves:

- original recommendation;
- original calculation outputs;
- original reason codes;
- proposed override;
- override reason;
- requester;
- approver;
- approval time;
- expiry;
- policy basis;
- second approver where required.

The original recommendation is never overwritten.

## 20.4 Dual control

Dual control applies to:

- overrides beyond tolerance;
- high-risk approvals;
- exceptions to required evidence;
- approval above actor authority;
- reinstatement of a rejected decision.

An expired approval request cannot create a decision.

---

# 21. API contract

## 21.1 Command rules

Every mutation requires:

- authenticated actor;
- authorization;
- correlation ID;
- audit context;
- reason for business transitions or corrections;
- `Idempotency-Key` for non-idempotent operations;
- `If-Match` for mutable aggregate changes.

## 21.2 Idempotency

Scope:

```text
actor
+ operation
+ resource namespace
+ idempotency key
```

Fingerprint:

```text
canonical HTTP method
+ canonical path
+ relevant headers
+ canonical request body
```

Behavior:

- same key and same fingerprint: return original response;
- same key and changed fingerprint: `409 Conflict`;
- persist original status, relevant headers, and body;
- retention is command-specific;
- an in-progress duplicate receives a documented deterministic response;
- idempotency records are not reused across actors or operation namespaces.

## 21.3 Error contract

| Status | Meaning |
|---:|---|
| `400` | Malformed request |
| `401` | Unauthenticated |
| `403` | Capability denied |
| `404` | Resource not found |
| `409` | Idempotency or state-transition conflict |
| `412` | Stale `If-Match` |
| `422` | Business validation or freeze failure |
| `429` | Controlled request limit |
| `503` | Required infrastructure unavailable |

Example freeze failure:

```json
{
  "error": "SNAPSHOT_VALIDATION_FAILED",
  "issues": [
    {
      "code": "DUPLICATE_WAREHOUSE_RECEIPT",
      "severity": "critical",
      "resource_ids": ["receipt_17", "receipt_31"],
      "blocks_freeze": true
    }
  ]
}
```

## 21.4 Representative endpoints

```text
GET    /facilities
POST   /facilities
GET    /facilities/{id}
PATCH  /facilities/{id}

POST   /facilities/{id}/documents
POST   /candidate-facts/{id}/approve
POST   /candidate-facts/{id}/reject
POST   /approved-facts/{id}/correct

POST   /facilities/{id}/validate
POST   /facilities/{id}/freeze

GET    /snapshots/{id}
POST   /snapshots/{id}/pipeline-runs
GET    /pipeline-runs/{id}

GET    /snapshots/{id}/valuation
GET    /snapshots/{id}/cbb
GET    /snapshots/{id}/hedge-liquidity
GET    /snapshots/{id}/scenarios
GET    /snapshots/{id}/irc
GET    /snapshots/{id}/credit-signal
GET    /snapshots/{id}/climate-evidence

POST   /snapshots/{id}/recommendations
POST   /recommendations/{id}/approval-requests
POST   /approval-requests/{id}/approve
POST   /approval-requests/{id}/reject
POST   /recommendations/{id}/override-requests

GET    /decisions/{id}
POST   /decisions/{id}/reports

POST   /analytics/query-plans
POST   /analytics/execute
GET    /audit-events
```

## 21.5 API schema discipline

- All public request and response models are versioned.
- OpenAPI is generated and checked into CI artifacts.
- Breaking contract changes require explicit versioning.
- Domain reason codes are stable identifiers, not presentation strings.
- Presentation text may change without changing reason-code identity.
- Money and decimal fields serialize as strings.
- Units and currencies are mandatory where meaningful.
- Database IDs are opaque and not overloaded with domain meaning.

---

# 22. User interface

The web application begins after M4 backend contracts are stable.

## 22.1 Facility Cockpit

Display:

- commitment;
- current exposure;
- CBB;
- contractual availability;
- IRC;
- recommended draw;
- final decision;
- evidence blockers;
- hedge state;
- liquidity state;
- credit signal;
- climate/EUDR evidence state.

CBB and IRC must be visually and semantically distinct.

## 22.2 Collateral workspace

Display:

- inventory lots;
- receivables;
- warehouse receipts;
- eligibility;
- haircuts;
- reserves;
- reconciliation issues;
- evidence lineage.

## 22.3 Evidence review

Display:

- original document;
- candidate facts;
- page/region provenance;
- conflicts;
- review actions;
- approval history;
- supersession chain.

## 22.4 Hedge Lab

Display:

- physical exposure;
- futures and options;
- `KC` versus `AC`;
- contract-month mismatch;
- hedge ratio;
- basis exposure;
- option value and Greeks;
- variation-margin stress;
- liquidity shortfall.

It is an analytical interface, not a trade-entry screen.

## 22.5 Scenario Lab

Display:

- assumptions;
- CBB under stress;
- IRC;
- tail-loss distribution;
- Expected Shortfall;
- margin-liquidity outcomes;
- risk-factor contribution;
- threshold sensitivity.

## 22.6 Climate and traceability

Display:

- origin map;
- geolocation state;
- evidence graph;
- missing links;
- document freshness;
- climate indicators;
- EUDR evidence-readiness state;
- legal-review disclaimer.

## 22.7 Approval workspace

Display:

- recommendation;
- requested amount;
- CBB and IRC;
- conditions;
- evidence blockers;
- scenario outcomes;
- credit signal;
- original recommendation versus override;
- separation-of-duty state;
- expiry.

## 22.8 Report viewer

Every official number should expose:

```text
number
→ calculation field
→ stage output
→ formula version
→ policy rule
→ snapshot input
→ approved fact
→ source document
```

---

# 23. Governed analytics copilot

## 23.1 Architecture

The copilot reads curated analytical views only.

```text
natural-language question
→ intent classification
→ approved template or plan schema
→ plan validation
→ deterministic SQL compilation
→ SQL AST validation
→ cost gate
→ read-only execution
→ structured answer
→ lineage and assumptions
→ optional explanation
```

## 23.2 Priority ladder

1. Approved parameterized templates.
2. Structured analytical-plan compiler.
3. Deterministic SQL compiler.
4. Restricted analyst-authored SQL fallback.

Example questions:

- Why did availability decline between snapshots?
- Which inventory lots contribute most to reserves?
- Which receivables were excluded due to age?
- What is the hedge ratio by delivery month?
- Which scenario produces the lowest IRC?
- Which approved facts changed since the previous decision?

## 23.3 SQL containment

Controls:

- allowlisted statement and AST types;
- approved schemas, views, columns, and joins;
- approved functions;
- fixed `search_path`;
- dedicated read-only analytics role;
- read-only transaction;
- repeatable-read isolation;
- no temporary objects;
- no schema creation;
- no operational write tables;
- no system catalogs;
- no `information_schema`;
- no recursive CTEs;
- no volatile functions;
- no security-definer functions;
- no unbounded generators;
- no Cartesian joins;
- no multiple statements;
- no parser fallback;
- no `EXPLAIN ANALYZE`.

Operational limits:

- `statement_timeout`;
- `lock_timeout`;
- `idle_in_transaction_session_timeout`;
- restricted `work_mem`;
- restricted `temp_file_limit`;
- row, byte, and cell limits;
- `EXPLAIN (FORMAT JSON)` cost gate;
- cancellation and rollback on disconnect.

SQL AST validation is defense in depth. Database permissions and curated views remain the primary boundary.

## 23.4 Answer contract

Every answer includes:

- question;
- interpreted scope;
- analytical plan;
- snapshot or data cutoff;
- result;
- units;
- assumptions;
- referenced views;
- query digest;
- lineage;
- warnings;
- refusal reason where applicable.

## 23.5 Benchmark

Create 100–150 CanopyLedger-specific gold cases covering:

- template selection;
- plan correctness;
- SQL correctness;
- result correctness;
- scope;
- units;
- lineage;
- ambiguity;
- refusal;
- query isolation;
- cost containment;
- repeatability;
- prompt-injection-as-data resistance.

---

# 24. Governed agents

## 24.1 Purpose

Agents orchestrate authoritative tools. They do not replace the domain engine.

Logical roles:

```text
FacilityOrchestrator
EvidenceReviewAssistant
CollateralAnalysisAssistant
MarketRiskAssistant
CreditAnalysisAssistant
ClimateEvidenceAssistant
DecisionPackAssistant
ReportingAssistant
```

These roles need not be separate model processes.

## 24.2 Default mode

The canonical demo uses a deterministic replayable planner.

An optional local or bring-your-own planner may select permitted tools through the same capability registry.

## 24.3 Allowed actions

Agents may:

- read facility and snapshot state;
- retrieve approved evidence;
- start an approved pipeline;
- inspect pipeline state;
- retrieve stage outputs;
- explain deterministic results;
- assemble a draft decision pack;
- route an approval request;
- surface conflicts and missing facts.

## 24.4 Prohibited actions

Agents may not:

- calculate authoritative values themselves;
- change approved policy;
- select an unapproved bundle;
- mutate a snapshot;
- alter a published output;
- approve or reject a facility;
- approve an override;
- execute a trade;
- transfer or release funds;
- assert legal compliance;
- promote a candidate fact without human review;
- treat prompt text or document text as permission.

## 24.5 Capability registry

```json
{
  "tool": "pipeline.start",
  "risk_level": "controlled_write",
  "allowed_roles": ["facility_orchestrator"],
  "input_schema": "PipelineStartInput/v1",
  "output_schema": "PipelineRun/v1",
  "requires_approval": false,
  "audit_required": true
}
```

Authorization is enforced in code and database permissions, not natural-language instructions.

## 24.6 Runtime records

```text
AgentRun
TaskPlan
AgentTask
ToolCallRecord
ToolResultRecord
ApprovalRequest
ApprovalDecision
TraceEvent
HandoffRecord
```

Record:

- planner type and version;
- model/provider metadata when used;
- context retrieved;
- tool inputs and outputs;
- authorization decisions;
- human interruptions;
- final state;
- errors and retries.

---

# 25. Security and audit

## 25.1 Database roles

```text
migration_owner
application_writer
pipeline_writer
analytics_reader
report_reader
audit_reader
```

Runtime roles own no tables.

Immutable tables deny ordinary `UPDATE` and `DELETE`.

## 25.2 Capabilities

```text
facility.read
facility.edit
evidence.upload
fact.review
snapshot.freeze
pipeline.start
recommendation.create
approval.request
approval.act
override.request
override.approve
report.generate
analytics.query
audit.read
bundle.approve
```

## 25.3 Audit event

Sensitive actions record:

- actor;
- acting role;
- operation;
- resource;
- before and after version references;
- reason;
- correlation ID;
- request ID;
- policy decision;
- timestamp;
- result;
- relevant digest.

Audit events are append-only.

## 25.4 Threats to test

- duplicate command;
- concurrent freeze;
- stale `If-Match`;
- worker crash after calculation before publication;
- stale-lease publication;
- bundle mutation;
- document replacement;
- artifact-type hash confusion;
- prompt injection in documents;
- analytics escalation;
- SQL cost bomb;
- approval self-dealing;
- expired approval use;
- report from superseded decision;
- silent font substitution;
- model artifact replacement;
- feature-schema mismatch;
- cross-facility data leakage;
- malicious filenames and MIME spoofing;
- object-storage path traversal;
- replay with missing dependencies;
- forged reason codes;
- unauthorized bundle activation.

---

# 26. Reporting

## 26.1 Primary artifact

The primary reporting artifact is canonical report-model JSON.

```text
approved snapshot
+ immutable stage outputs
+ active final decision
+ pinned report template
→ canonical report model
→ rendered PDF/HTML
```

PDF and HTML are renderings, not the source of truth.

## 26.2 Sections

1. Facility summary.
2. Requested and approved amount.
3. Contractual Borrowing Base.
4. Inventory and receivables eligibility.
5. Reserves.
6. Hedge and basis exposure.
7. Variation-margin liquidity.
8. Scenario results.
9. Internal Risk Capacity.
10. Credit early-warning signal.
11. Climate and EUDR evidence state.
12. Financed-emissions information.
13. Recommendation.
14. Approval or override.
15. Conditions and expiry.
16. Data and methodology limitations.
17. Artifact manifest.

## 26.3 Rendering rules

- fixed ordering;
- fixed locale;
- fixed timezone;
- pinned fonts;
- pinned renderer;
- pinned template;
- normalized metadata;
- deterministic identifiers;
- no current-clock canonical fields;
- no network calls;
- no model calls;
- no recalculation;
- no mutable-state reads;
- missing fonts cause failure;
- silent font substitution is prohibited.

Only the current approved final decision can create an official report.

Draft or superseded outputs must carry an unmistakable non-official watermark/state.

---

# 27. Detailed roadmap

## M0 — Normative Foundation

### Deliverables

- Apache-2.0 license.
- Product charter.
- Glossary.
- Anti-goals.
- Role and authority matrix.
- State-machine specification.
- Architectural invariants.
- Canonical Value Profile v1.
- Snapshot specification.
- Bundle specifications.
- Evidence stop conditions.
- Calculation-contract template.
- Threat model.
- Synthetic reference scenario.
- Architecture diagrams.
- Full roadmap.
- Concise README.
- OSS landscape review.
- Public namespace decision pending trademark review.

### Exit criteria

No implementation starts until CBB, IRC, snapshot, approved fact, recommendation, override, and final decision each have one unambiguous definition.

---

## M1A — Integrity Kernel

### Deliverables

- working facility aggregate;
- optimistic versioning;
- canonicalization library;
- snapshot freeze;
- snapshot manifest;
- domain-separated hashing;
- bundle registry;
- bundle immutability;
- idempotency store;
- transactional outbox;
- PostgreSQL queue;
- lease fencing;
- consumer inbox;
- immutable publication protocol;
- replay CLI;
- audit foundation.

### Required tests

- concurrent freeze;
- repeated identical command;
- idempotency key reused with changed request;
- serialization retry;
- process crash;
- stale worker;
- duplicate event;
- bundle mutation denial;
- bundle deletion denial;
- cross-platform semantic replay;
- Python/TypeScript canonicalization parity.

### Exit output

A facility can be frozen, content-addressed, replayed, and verified before financial calculations exist.

---

## M1B — Initial Domain Pipeline

### Deliverables

- inventory;
- receivables;
- market snapshot;
- unit and currency normalization;
- inventory valuation;
- receivables valuation;
- typed eligibility;
- reserves;
- CBB;
- contractual availability;
- CBB certificate;
- CLI and API demo;
- golden fixtures.

### Required tests

- formula goldens;
- rounding;
- units;
- currencies;
- ineligibility reasons;
- reserve application;
- monotonicity;
- duplicate collateral prevention.

### Exit output

```text
facility snapshot
→ deterministic CBB certificate
```

---

## M2 — Evidence Controls

### Deliverables

- original document storage;
- byte hashing;
- document versions;
- candidate facts;
- approved facts;
- rejected facts;
- superseding corrections;
- receipt controls;
- ownership and pledge evidence;
- duplicate-receipt detection;
- quantity reconciliation;
- lineage;
- human review API/UI.

### Exit output

No critical value enters a snapshot without evidence lineage and approval state.

---

## M3 — Hedge and Liquidity

### Deliverables

- exchange specifications;
- `KC` and `AC` distinction;
- physical exposure;
- futures;
- options;
- FX exposure;
- basis exposure;
- hedge ratio;
- futures P&L;
- Black–76 reference;
- CRR American option model;
- Greeks;
- variation-margin stress;
- liquidity coverage;
- hedge/liquidity output.

### Required tests

- contract units;
- Black–76 cases;
- lattice convergence;
- American/European relationship;
- early exercise;
- near expiry;
- deep ITM/OTM;
- low volatility;
- near-zero rate;
- independent reference comparison.

### Exit output

The system explains economic hedge effect and cash-liquidity consequences.

---

## M4A — Scenario Capacity

### Deliverables

- deterministic scenarios;
- shock compiler;
- Monte Carlo engine;
- Expected Shortfall;
- CBB-deficiency probability;
- margin-liquidity shortfall probability;
- threshold stability;
- IRC policy;
- separate IRC resources.

### Exit output

```text
CBB
+ hedge/liquidity
+ scenario losses
→ IRC
```

---

## M4B — Governance and Initial UI

### Deliverables

- recommendation;
- approval request;
- approval action;
- final decision;
- override workflow;
- dual control;
- expiry;
- supersession;
- Facility Cockpit;
- collateral view;
- Hedge Lab;
- Scenario Lab;
- approval workspace.

### Required tests

- no self-approval;
- expired request rejection;
- original recommendation preservation;
- dual control;
- superseded decision rejection;
- report-ineligible state rejection.

### Exit output

A deterministic facility decision can be governed and approved through the UI.

---

## M5 — Climate, EUDR, and Financed Emissions

### Deliverables

- evidence graph;
- PostGIS geometry validation;
- traceability state;
- legal-interpretation bundle;
- climate-data adapter;
- reference fixtures;
- origin concentration;
- climate scenarios;
- financed-emissions methodology bundle;
- financed-emissions output;
- data-quality score;
- climate/traceability UI.

### Exit output

The decision pack includes climate and EUDR evidence state without making an unsupported legal conclusion.

---

## M6 — Credit Early Warning

### Deliverables

- synthetic borrower panel;
- 90-day target;
- feature schema;
- leakage controls;
- temporal split;
- logistic baseline;
- shallow-tree challenger;
- optional calibration;
- comparison report;
- reason-code mapper;
- model card;
- versioned model bundle;
- local deterministic inference;
- monitoring panel.

### Constraints

- CPU only;
- no runtime training;
- no external model server;
- no proprietary-data requirement;
- advisory only;
- no direct CBB effect.

### Exit output

A reproducible and explainable synthetic deterioration signal is available as a bounded recommendation input.

---

## M7 — Document Intelligence

### Deliverables

- deterministic template parsers;
- PDF text/table extraction;
- document classification;
- candidate fact generation;
- reconciliation;
- optional extractor adapter;
- human verification UI;
- extraction benchmark.

### Exit output

Known documents can be ingested efficiently while human verification remains authoritative.

---

## M8 — Governed Analytics Copilot

### Deliverables

- curated analytics schema;
- approved templates;
- analytical plan DSL;
- deterministic SQL compiler;
- AST validator;
- cost gate;
- read-only execution;
- lineage answer contract;
- optional explanation adapter;
- 100–150 case benchmark;
- security/refusal suite.

### Adversarial tests

- unknown AST;
- parser fallback;
- recursive CTE;
- system catalog;
- volatile function;
- `pg_sleep`;
- `generate_series`;
- Cartesian join;
- regex/spatial cost bomb;
- oversized output;
- cancellation cleanup;
- ambiguous question;
- prompt injection in stored text;
- cross-facility access.

### Exit output

Analysts ask controlled questions without unrestricted model-to-database access.

---

## M9 — Governed Agents

### Deliverables

- agent specification;
- agent runner;
- deterministic replay planner;
- optional planner adapter;
- capability registry;
- typed tools;
- run/task/tool-call records;
- handoffs;
- approval routing;
- trace timeline;
- safety evaluation.

### Exit output

Agents orchestrate and explain while authoritative calculations and decisions remain outside the agent.

---

## M10 — Reporting, Hardening, and OSS Release

### Deliverables

- canonical report model;
- deterministic HTML;
- deterministic PDF in pinned environment;
- artifact manifest;
- pinned fonts;
- metadata normalization;
- report replay;
- demo seed;
- architecture and calculation documentation;
- security documentation;
- model card;
- data card;
- contributor guide;
- release checklist;
- CI matrix;
- migration recovery process.

### Canonical demo

```bash
make demo
```

It must:

1. Start PostgreSQL/PostGIS.
2. Run migrations.
3. Seed the synthetic facility.
4. Ingest reference evidence.
5. Approve fixture facts.
6. Freeze a snapshot.
7. Execute the pipeline.
8. Create a recommendation.
9. Apply fixture approval.
10. Generate the report package.
11. Start the web application.
12. Expose replay and audit views.

---

# 28. Testing and release gates

| Milestone | Mandatory gate |
|---|---|
| M1A | Canonical vectors, concurrent freeze, crash replay, lease fencing, bundle immutability |
| M1B | Formula goldens, units, currencies, exact rounding, property invariants |
| M2 | Duplicate receipts, fact supersession, byte integrity, critical-fact blocking |
| M3 | Option references, lattice convergence, early exercise, contract-spec correctness |
| M4 | Scenario repeatability, `IRC <= CBB`, approval separation, expiry, override preservation |
| M5 | Geometry validation, evidence lineage, legal-bundle pinning, no compliance overclaim |
| M6 | Leakage audit, temporal validation, calibration, reason stability, schema enforcement |
| M7 | Candidate-only extraction, reconciliation, human review for critical facts |
| M8 | SQL isolation, AST denial, cost limits, ambiguity refusal, cancellation cleanup |
| M9 | Capability denial, complete trace, prompt-injection resistance, no agent approval |
| M10 | Report replay, font failure, metadata normalization, superseded-report rejection |

## 28.1 Required test categories

- unit tests;
- domain-invariant tests;
- formula golden tests;
- property tests;
- schema contract tests;
- API contract tests;
- idempotency tests;
- concurrency tests;
- migration tests;
- replay tests;
- security tests;
- browser tests;
- deterministic demo test.

## 28.2 Migration rules

- Every schema change uses Alembic.
- Do not edit an applied migration.
- Lossless downgrade claims require downgrade tests.
- Destructive changes require a forward-recovery plan.
- Backups and restore procedures must be documented before production use.
- Data migration and schema migration should be separated when risk justifies it.
- Large table rewrites require explicit review.
- New non-null columns require a safe rollout plan.
- Bundle and immutable-artifact tables receive especially strict migration review.

---

# 29. Canonical reference scenario

## 29.1 Starting position

A synthetic coffee trader requests an additional draw.

The working facility contains:

- 24 inventory lots;
- four origin regions;
- two warehouses;
- 14 receivables;
- `KC` futures;
- a small `AC` hedge;
- two option positions;
- warehouse receipts and invoices;
- one duplicate receipt;
- one quantity mismatch;
- one stale insurance document;
- one origin-evidence gap;
- approved market and FX snapshots.

## 29.2 Workflow

1. Upload documents.
2. Review extracted candidates.
3. Reject one incorrect quantity.
4. Approve corrected facts.
5. Resolve the duplicate receipt.
6. Address or reserve for stale insurance.
7. Freeze the snapshot.
8. Calculate valuation and CBB.
9. Calculate hedge and margin liquidity.
10. Run price-decline, rally/margin, and climate/evidence stresses.
11. Calculate IRC.
12. Produce the synthetic credit signal.
13. Create a recommendation.
14. Route to an approver.
15. Approve with conditions or perform dual-control override.
16. Generate the official committee pack.
17. Replay the decision from its snapshot and bundles.

## 29.3 Final package distinctions

The package must separately show:

```text
contractual borrowing base
contractual availability
internal risk capacity
recommended incremental draw
final approved draw
```

It must explain why the values differ.

---

# 30. Definition of success

CanopyLedger v1 is successful when:

1. A user can edit and reconcile a synthetic coffee-trade facility.
2. Critical evidence conflicts block freeze.
3. A frozen snapshot is immutable and content-addressed.
4. CBB is deterministic and traceable.
5. `KC` and `AC` cannot be confused.
6. Hedge benefits and margin-liquidity costs are both visible.
7. Scenario results reproduce under the declared envelope.
8. IRC remains separate from and never exceeds CBB.
9. Credit early warning uses a small reviewable synthetic model bundle.
10. EUDR output describes evidence state rather than legal compliance.
11. Financed emissions include methodology and data-quality lineage.
12. A recommendation remains separate from a human decision.
13. Overrides preserve the original recommendation.
14. Agents cannot calculate, approve, trade, or fund.
15. The copilot cannot escape curated read-only analytics.
16. Official reports require a current approved decision.
17. Every official value traces to evidence, policy, bundles, and code.
18. `make demo` reproduces the complete scenario from an empty environment.

---

# 31. Codex implementation standards

## 31.1 Python

- Python 3.12.
- Full type hints for public functions and domain/application code.
- Use `Decimal` and typed value objects for authoritative values.
- Prefer dataclasses or Pydantic models according to boundary needs.
- Avoid untyped dictionaries in domain and calculation layers.
- Use explicit exceptions with stable error codes.
- Keep I/O outside pure calculation functions.
- Inject clock, random generator, repositories, and adapters.
- Avoid module-level mutable state.
- Do not swallow exceptions.
- Do not use broad `except Exception` without re-raising or converting to a documented boundary error.
- Keep deterministic functions free of system time, environment lookups, and network calls.

## 31.2 TypeScript and web

- TypeScript strict mode.
- Generated or explicitly synchronized API contracts.
- Do not duplicate finance formulas in UI code.
- Format authoritative decimal strings for display without changing stored values.
- Expose source timestamp, snapshot, bundle, and status for important values.
- Accessibility is mandatory for primary workflows.
- Treat loading, stale, failed, superseded, and unauthorized states explicitly.
- Never hide evidence blockers behind decorative summary cards.
- Avoid implying that advisory outputs are approved decisions.

## 31.3 SQL and persistence

- Use explicit constraints for invariants where possible.
- Use foreign keys.
- Use uniqueness constraints for idempotency and publication.
- Use check constraints for valid states where practical.
- Avoid database triggers for complex domain logic unless justified and documented.
- Explicitly order canonical reads.
- Keep operational and analytics permissions separate.
- Immutable tables reject ordinary update/delete.
- Do not rely on ORM behavior alone for critical integrity.

## 31.4 Naming

Use domain-explicit names:

- `contractual_borrowing_base`, not `capacity`;
- `internal_risk_capacity`, not `adjusted_capacity`;
- `recommendation`, not `decision`;
- `final_decision`, not `approval_result`;
- `candidate_fact` and `approved_fact`, not generic `extracted_data`;
- `market_bundle_digest`, not `market_version` when the digest is meant;
- `superseded_by_id`, not `updated_record`.

Avoid unexplained abbreviations outside approved domain terms such as CBB, IRC, FX, EUDR, VaR, and ES.

## 31.5 Documentation

Every calculation module must document:

- purpose;
- inputs;
- outputs;
- units;
- formula;
- rounding;
- assumptions;
- edge cases;
- reason codes;
- versioning;
- reference tests.

Every stateful workflow must document:

- state machine;
- legal transitions;
- authorization;
- idempotency;
- concurrency;
- failure behavior;
- audit behavior.

## 31.6 Commit and PR expectations

A change summary should state:

- milestone/module;
- behavior changed;
- invariant preserved;
- migrations;
- tests run;
- remaining limitations.

Do not claim tests passed unless they were actually executed.

---

# 32. Work sequencing rules

Codex must not build later-layer convenience features before required lower-layer integrity.

Required order:

```text
domain language and invariants
→ canonical values and persistence
→ immutable snapshot
→ queue/outbox/publication
→ deterministic CBB
→ evidence controls
→ hedge/liquidity
→ scenarios and IRC
→ human governance
→ UI
→ climate/EUDR
→ credit signal
→ document intelligence
→ analytics copilot
→ agents
→ hardened reporting and release
```

Exceptions require an explicit task instruction.

A UI mock may precede backend completion only as a disposable design artifact and must not become the source of contract truth.

---

# 33. Decision records

Use concise architectural decision records under:

```text
docs/architecture/decisions/
```

Create an ADR when changing:

- persistence technology;
- canonicalization rules;
- bundle semantics;
- snapshot structure;
- queue guarantees;
- calculation authority;
- CBB or IRC separation;
- model-training policy;
- agent authority;
- analytics security;
- report source of truth;
- deployment shape.

An ADR may supersede an older ADR but does not silently erase history.

This master plan remains the system-level constitution. When an approved ADR changes it, update both the ADR and this document in the same change.

---

# 34. External reference standards

These references inform the implementation. They do not override pinned internal policy or calculation contracts.

- RFC 8785, JSON Canonicalization Scheme:  
  https://www.rfc-editor.org/rfc/rfc8785
- PostgreSQL transaction isolation:  
  https://www.postgresql.org/docs/current/transaction-iso.html
- PostgreSQL `SELECT`, including `SKIP LOCKED`:  
  https://www.postgresql.org/docs/current/sql-select.html
- ICE Coffee C futures/options product specifications:  
  https://www.ice.com/products/15/Coffee-C-Futures  
  https://www.ice.com/products/14/Coffee-C-Options
- European Commission EUDR overview:  
  https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en
- PCAF Global GHG Accounting and Reporting Standard:  
  https://carbonaccountingfinancials.com/standard
- NGFS climate scenario guidance:  
  https://www.ngfs.net/ngfs-scenarios-portal/
- NIST AI Risk Management Framework:  
  https://www.nist.gov/itl/ai-risk-management-framework
- SQLGlot documentation:  
  https://sqlglot.com/sqlglot.html
- OpenAI Codex overview and repository-instruction guidance:  
  https://openai.com/index/introducing-codex/
- OpenAI Codex execution-plan guidance:  
  https://cookbook.openai.com/articles/codex_exec_plans

External facts that can change must be imported into a versioned approved bundle or fixture before becoming part of an official calculation.

---

# 35. Final product statement

> **CanopyLedger is a reproducible decision operating system for coffee-backed trade finance. It converts evidence about inventory, receivables, market exposure, hedges, liquidity, borrower condition, climate risk, and traceability into deterministic risk calculations, a governed recommendation, and a human-approved lending decision.**
>
> **Mutable data is frozen before calculation. Authoritative values come only from versioned deterministic engines. Contractual Borrowing Base and Internal Risk Capacity remain separate. Models provide bounded advisory signals. Copilots read curated views. Agents orchestrate approved tools. Humans retain authority. Every official decision and report is replayable from immutable evidence, policy, market, legal-interpretation, and computation bundles.**
