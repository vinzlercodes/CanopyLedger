# CanopyLedger Build Progress

**Canonical plan:** [CANOPYLEDGER_MASTER_PLAN.md](CANOPYLEDGER_MASTER_PLAN.md)
**Condensed implementation guide:** [MASTER_PLAN.md](MASTER_PLAN.md)
**Last updated:** 2026-06-22
**Current phase:** M1A/M1B vertical slice; M0 complete

## Status vocabulary

- `NOT_STARTED`: no implementation.
- `IN_PROGRESS`: active work; acceptance gate incomplete.
- `BLOCKED`: external decision/dependency prevents progress.
- `DONE`: acceptance gate passed with recorded evidence.

## Milestones

| Milestone | Status | Built | Remaining | Gate evidence |
|---|---|---|---|---|
| M0 Normative foundation | DONE | Approved normative contracts; executable state machine; versioned OpenAPI; PostgreSQL capability roles; OSS landscape review; scaffold, CI, and Apache-2.0 license | - | 66 tests, OpenAPI drift check, PostgreSQL 17 privilege integration, lint, type, and build gates pass; no material research contradiction |
| M1A Integrity kernel | IN_PROGRESS | Canonical value profile with Python/TypeScript parity vectors; immutable bundles and snapshot manifests; durable idempotency; PostgreSQL resource schema; serializable facility freeze with state copy, four bundle pins, snapshot inputs, audit, and outbox in one transaction; fenced stage publication domain protocol; local immutable object store; facility/snapshot API slice | Transactional fenced output/outbox publication; inbox; durable HTTP wiring; generated TypeScript client; Level A/B replay harness; final M1A gate | 86 Python tests, 20 clean-database PostgreSQL tests, 14 TypeScript parity tests, Ruff, and mypy pass; milestone gate remains open |
| M1B Initial domain pipeline | IN_PROGRESS | Money value object; inventory valuation; eligibility contribution; contractual reserves; contractual CBB | Receivables; persisted stage outputs; pipeline orchestration/API; certificate JSON; expanded golden/property fixtures | Initial deterministic formula tests pass; milestone gate pending |
| M2 Evidence controls | NOT_STARTED | - | Entire milestone | Pending |
| M3 Hedge and liquidity | NOT_STARTED | - | Entire milestone | Pending |
| M4A Scenario capacity | NOT_STARTED | - | Entire milestone | Pending |
| M4B Decision governance | NOT_STARTED | - | Entire milestone | Pending |
| M5 EUDR and climate | NOT_STARTED | - | Entire milestone | Pending |
| M6 Credit early warning | NOT_STARTED | - | Entire milestone | Pending |
| M7 Document intelligence | NOT_STARTED | - | Entire milestone | Pending |
| M8 Analytics Copilot | NOT_STARTED | - | Entire milestone | Pending |
| M9 Governed agents | NOT_STARTED | - | Entire milestone | Pending |
| M10 Reports and OSS release | NOT_STARTED | - | Entire milestone | Pending |

## Built inventory

| Date | Area | Artifact | Verification |
|---|---|---|---|
| 2026-06-21 | Governance | `CANOPYLEDGER_MASTER_PLAN.md`, `MASTER_PLAN.md`, `PROGRESS.md`, contract catalogue | Full plan is canonical; condensed guide is subordinate; milestone gates remain open until all evidence exists |
| 2026-06-21 | OSS foundation | Apache-2.0 `LICENSE`, README, contribution/security policies, CI, pre-commit, Sonar config | Ruff and mypy pass; CI workflow present |
| 2026-06-21 | Canonicalization | Decimal, timestamp, Unicode, ordered-array, schema-set, integer, and domain-digest contracts | Unit vectors pass |
| 2026-06-21 | Snapshot integrity | Frozen manifest, pinned bundle/input references, canonical bytes, digest | Unit tests pass |
| 2026-06-21 | Command safety | Idempotency scope/fingerprint/replay/conflict/tombstone behavior | Unit and API tests pass |
| 2026-06-21 | Pipeline safety | Lease epochs, stale-worker fencing, immutable single output | Pure-domain tests pass; database transaction absent |
| 2026-06-21 | Object storage | Local content-addressed adapter, digest verification, atomic publish, immutable keys, traversal rejection | 9 contract tests pass |
| 2026-06-21 | Finance kernel | Inventory valuation, eligibility contribution, reserves, contractual CBB | Deterministic formula tests pass |
| 2026-06-21 | HTTP API | Health; facility create/read/update; snapshot freeze/read; bearer demo actor; strong ETag; Problem Details; idempotent replay | In-memory adapter tests pass; not durable |
| 2026-06-21 | M0 contracts | Executable decision-cycle transitions; typed OpenAPI 3.1 artifact; PostgreSQL role/schema bootstrap | Exhaustive transition, API contract, artifact drift, and PostgreSQL privilege tests pass |
| 2026-06-21 | OSS evidence | Fineract, Strata, QuantLib, OpenLineage, Evidently, and FireFly review | No project contradicts or replaces snapshot, CBB/IRC, calculation-authority, or human-approval boundaries |
| 2026-06-22 | M1A durable schema | Alembic resource baseline for facilities, immutable bundles/snapshots/inputs, idempotency/tombstones, pipeline queue/output, outbox/inbox, and audit | PostgreSQL 17 schema, immutability, outbox-content guard, and least-privilege integration tests pass |
| 2026-06-22 | Cross-runtime canonicalization | Shared versioned vectors and TypeScript canonical JSON, decimal, timestamp, and domain-digest implementation | 14 identical accept/reject vectors pass in Python and TypeScript |
| 2026-06-22 | Durable command safety | Transactional PostgreSQL idempotency with actor/operation/resource scope, replay, conflict, pending, rollback, retention, and permanent tombstones | 8 PostgreSQL command/idempotency behaviors pass, including concurrent same-key execution |
| 2026-06-22 | Serializable snapshot freeze | Facility state copy; four typed bundle digest pins; immutable manifest metadata; snapshot inputs; audit and pipeline-start outbox; bounded SQLSTATE 40001 retry | 5 PostgreSQL acceptance behaviors pass: success, wrong-type rejection, retry, injected crash rollback, and concurrent one-freeze invariant |

## Active work

1. Implement transactional queue claim, inbox deduplication, and fenced stage/output/outbox publication.
2. Implement Level A and Level B replay/audit verification.
3. Wire durable M1A services into the HTTP API.
4. Generate and verify the TypeScript client from the versioned OpenAPI artifact.
5. Run the complete M1A gate and then continue M1B receivables, orchestration, and certificates.

## Remaining work

All roadmap items not marked `DONE` remain required. The PostgreSQL integrity adapter now provides
durable bundles, command idempotency, and serializable snapshot freeze, but the HTTP application is
still wired to in-memory repositories. Pipeline queue/output publication, inbox processing, replay,
and the generated client remain incomplete. Detailed requirements live in
`CANOPYLEDGER_MASTER_PLAN.md` and contract files.

## Blockers

None.

## Verification log

| Date | Command | Result | Scope |
|---|---|---|---|
| 2026-06-21 | `uv run ruff check .` | PASS | 17 source files plus repository Python files |
| 2026-06-21 | `uv run mypy` | PASS | Strict typing, 17 source files |
| 2026-06-21 | `uv run pytest -q` | PASS, 38 tests | Canonicalization, snapshots, finance, idempotency, fencing, API |
| 2026-06-21 | `uv run pytest tests/test_object_store.py -q` | PASS, 9 tests | Object-store contract |
| 2026-06-21 | `uv run ruff check src/canopyledger/integrity/object_store.py tests/test_object_store.py` | PASS | Object-store implementation |
| 2026-06-21 | `uv run mypy` | PASS | Strict typing after object-store addition |
| 2026-06-21 | `uv run ruff check . && uv run mypy && uv run pytest -q` | PASS, 47 tests | Full repository gate after first M1 slice |
| 2026-06-21 | `uv build` | PASS | Source distribution and Python wheel |
| 2026-06-21 | `.venv-system/bin/ruff check . && .venv-system/bin/mypy && .venv-system/bin/pytest -q && .venv-system/bin/python -m pip check` | PASS, 47 tests, no broken requirements | Homebrew system Python 3.14.5 environment |
| 2026-06-21 | `uv run python scripts/export_openapi.py --check` | PASS | Checked-in OpenAPI 3.1 artifact matches deterministic application generation |
| 2026-06-21 | `bash tests/integration/test_database_roles.sh` against PostgreSQL 17 | PASS | Idempotent role bootstrap, ownership, fixed search paths, reader isolation, denied writes/DDL/temp access |
| 2026-06-21 | `uv run ruff check . && uv run mypy && uv run python scripts/export_openapi.py --check && uv run pytest -q && uv build` | PASS, 66 tests, sdist and wheel built | Full non-database M0 completion gate |
| 2026-06-22 | `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src` | PASS, 86 tests plus 19 expected database skips | Full Python regression, lint, typing, and deterministic OpenAPI drift gate after serializable freeze |
| 2026-06-22 | `DATABASE_URL=... .venv/bin/pytest tests/integration -q` on fresh PostgreSQL 17 database | PASS, 20 tests | Schema controls, immutable bundles, durable idempotency, serializable freeze, retry, rollback, and concurrency |
| 2026-06-22 | `npm test` in `typescript/` | PASS, 14 tests | Cross-runtime canonical accept/reject parity vectors |

## Decision/change log

| Date | Decision | Effect |
|---|---|---|
| 2026-06-21 | Backend-first modular monolith | Python integrity/domain kernel precedes UI |
| 2026-06-21 | No foundation-model training | Only M6 small CPU statistical fitting allowed |
| 2026-06-21 | Independent CBB and IRC | Decision compares uncapped values |
| 2026-06-21 | M1 split into M1A/M1B | Integrity semantics verified before finance formulas |
| 2026-06-21 | M0 completion follows tracker-defined gaps | Existing master plan and contract catalogue remain authoritative; persistence tables and TypeScript client remain M1A |
| 2026-06-22 | Freeze creation time is distinct from business `as_of` | Snapshot canonical manifest records schema version, actor, and creation timestamp without conflating reproducibility inputs with publication metadata |
| 2026-06-22 | Freeze retries the entire short transaction at `SERIALIZABLE` | SQLSTATE 40001 retries cannot publish partial snapshot, audit, outbox, or idempotency state; one facility working version can be frozen only once |

## Maintenance rules

- Update this file in the same commit as milestone-status changes.
- Record exact test/lint/build commands and results.
- Never mark `DONE` based only on code presence.
- Record blockers immediately.
- Amend `CANOPYLEDGER_MASTER_PLAN.md` through decision-log entry; never silently drift requirements.
