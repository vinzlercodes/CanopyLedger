# CanopyLedger Build Progress

**Canonical plan:** [CANOPYLEDGER_MASTER_PLAN.md](CANOPYLEDGER_MASTER_PLAN.md)
**Condensed implementation guide:** [MASTER_PLAN.md](MASTER_PLAN.md)
**Last updated:** 2026-07-07
**Current phase:** M2 Evidence controls; M0, M1A, and M1B complete

## Status vocabulary

- `NOT_STARTED`: no implementation.
- `IN_PROGRESS`: active work; acceptance gate incomplete.
- `BLOCKED`: external decision/dependency prevents progress.
- `DONE`: acceptance gate passed with recorded evidence.

## Milestones

| Milestone | Status | Built | Remaining | Gate evidence |
|---|---|---|---|---|
| M0 Normative foundation | DONE | Approved normative contracts; executable state machine; versioned OpenAPI; PostgreSQL capability roles; OSS landscape review; scaffold, CI, and Apache-2.0 license | - | 66 tests, OpenAPI drift check, PostgreSQL 17 privilege integration, lint, type, and build gates pass; no material research contradiction |
| M1A Integrity kernel | DONE | Canonical value profile with Python/TypeScript parity vectors; immutable bundles and snapshot manifests; durable idempotency; PostgreSQL resource schema; serializable facility freeze; leased `SKIP LOCKED` stage queue; bounded heartbeats and monotonic fencing epochs; inbox deduplication; atomic immutable output/outbox/audit publication; local immutable object store; durable facility/snapshot API wiring; generated TypeScript API client with drift check; pure Level A/B replay verifier and CLI; PostgreSQL replay package/audit path with reconstructed-manifest input-reference drift detection | - | Final gate passes: Ruff, mypy, OpenAPI drift, non-PostgreSQL pytest, TypeScript tests/typecheck/client drift, package build, Alembic upgrade/check, and 29 clean-database PostgreSQL tests |
| M1B Initial domain pipeline | DONE | Money value object; versioned quantity normalization; market snapshot resource; inventory valuation; receivables valuation; inventory and receivables eligibility contribution; contractual reserves; contractual CBB; contractual availability; deterministic CBB certificate JSON; pure S1-S4 stage graph with lineage/digests; persisted M1B stage-output publication over frozen PostgreSQL snapshots; CLI/API demo surface; typed pipeline demo API; full synthetic-facility golden fixture; fixed-input monotonic and invalid-number guard tests | - | Final gate passes: focused M1B formula/unit/currency/rounding/ineligibility/reserve/monotonic/duplicate/numeric tests, full Ruff, mypy, OpenAPI drift, non-PostgreSQL pytest, TypeScript client/type/test, package build, and fresh-database PostgreSQL marker |
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
| 2026-06-22 | Fenced pipeline publication | Concurrent `SKIP LOCKED` claims, monotonic epochs, capped heartbeat, expired reclaim, immutable output, inbox replay, and atomic downstream outbox/audit | 5 PostgreSQL pipeline acceptance tests plus 3 pure fencing tests pass, including stale worker and injected crash rollback/retry |
| 2026-06-23 | Replay verifier | Deterministic Level A environment and Level B semantic replay result model; replay CLI; application replay audit service; PostgreSQL replay package loader for snapshot manifest, reconstructed manifest, bundles, and stage outputs | Pure replay, CLI, static, PostgreSQL replay, and full clean-database integration gates pass |
| 2026-06-23 | Durable API wiring | FastAPI production factory backed by PostgreSQL `IntegrityService`; persistent facility create/read, idempotent replay, freeze, and snapshot-manifest read across app restarts | Focused API/OpenAPI tests pass; full clean-database PostgreSQL integration gate passes |
| 2026-06-23 | Generated TypeScript API client | Deterministic client generator/check script; checked-in generated `CanopyLedgerClient`; CI and Make client drift gates | Client check, TypeScript typecheck, and TypeScript tests pass |
| 2026-06-23 | M1A completion gate | Complete integrity kernel across schema, canonical parity, bundles, idempotency, serializable freeze, queue/inbox/publication, replay/audit, durable API, and TypeScript client | Final non-database, TypeScript, build, Alembic, and PostgreSQL marker gates pass |
| 2026-07-06 | M1B receivables and certificate slice | Versioned unit normalization; deterministic receivable valuation and eligibility; CBB certificate JSON with contractual availability, output digest, and duplicate-collateral prevention; `canopyledger-cbb-demo`; typed `/api/v1/cbb-certificates/demo` | Focused M1B domain and demo tests pass; OpenAPI artifact regenerated |
| 2026-07-06 | M1B pure stage graph and pipeline demo | Market snapshot resource with digest; pure S1-S4 M1B stage outputs with input digests, bundle digests, reason codes, and deterministic output digests; typed `/api/v1/m1b/pipeline/demo` returning stage outputs and certificate | Focused M1B pipeline tests pass; full non-database Python, TypeScript, OpenAPI, lint, type, and build gates pass |
| 2026-07-06 | M1B PostgreSQL publication | `PostgresM1BPipelineRunner` creates a run for a frozen snapshot, publishes four M1B stage outputs through existing fenced immutable publication, and makes outputs replay-package-visible | Focused M1B PostgreSQL test passes on `canopyledger_m1b_verify`; full PostgreSQL marker gate passes on `canopyledger_m1b_full` |
| 2026-07-07 | M1B completion gate | Full synthetic-facility golden fixture, pipeline-level unit normalization, same-currency receivable handling, monotonic reserve/usage/advance-rate/aging properties, and invalid-number guards | Focused M1B gate passes with 14 tests; full static, Python, TypeScript, build, and PostgreSQL gates pass |

## Active work

1. Begin M2 Evidence controls.

## Remaining work

All roadmap items not marked `DONE` remain required. M1A durable integrity and M1B initial domain
pipeline are complete. Next required scope is M2 Evidence controls. Detailed requirements live in
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
| 2026-06-22 | `DATABASE_URL=... .venv/bin/pytest tests/integration -q` on Task 6 verification database | PASS, 25 tests | Complete schema, bundle, idempotency, freeze, queue, inbox, fencing, publication, crash, and concurrency regression |
| 2026-06-22 | `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/python scripts/export_openapi.py --check` | PASS, 86 tests plus 24 expected database skips | Full non-database and static regression after fenced publication |
| 2026-06-23 | `.venv/bin/pytest tests/test_replay.py tests/test_replay_cli.py -q` | PASS, 4 tests | Pure Level A/B replay verifier and replay CLI contract |
| 2026-06-23 | `.venv/bin/ruff check src/canopyledger/integrity/replay.py src/canopyledger/cli/replay.py src/canopyledger/application/integrity.py src/canopyledger/application/ports.py src/canopyledger/persistence/postgres.py tests/test_replay.py tests/test_replay_cli.py tests/integration/test_postgres_replay.py` | PASS | Focused replay implementation, service, adapter, CLI, and tests |
| 2026-06-23 | `.venv/bin/mypy src/canopyledger/integrity/replay.py src/canopyledger/application/integrity.py src/canopyledger/application/ports.py src/canopyledger/persistence/postgres.py` | PASS | Focused replay typing |
| 2026-06-23 | `.venv/bin/pytest -q` | PASS, 90 tests plus 27 expected database skips | Full non-database Python regression after replay verifier changes |
| 2026-06-23 | `.venv/bin/python -m canopyledger.cli.replay --help` | PASS | Replay CLI entry-point help |
| 2026-06-23 | `.venv/bin/ruff check .` | PASS | Full repository Ruff check after replay verifier changes |
| 2026-06-23 | `.venv/bin/mypy src` | PASS | Full strict typing after replay verifier changes |
| 2026-06-23 | `.venv/bin/python scripts/export_openapi.py --check` | PASS | Deterministic OpenAPI artifact unchanged by replay work |
| 2026-06-23 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_task7_verify .venv/bin/pytest tests/integration/test_postgres_replay.py -q` | PASS, 3 tests | PostgreSQL replay package/audit success, bundle corruption detection, and reconstructed snapshot-input drift detection |
| 2026-06-23 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_task7_full .venv/bin/pytest tests/integration -q` | PASS, 28 tests | Full clean-database PostgreSQL integration regression after role bootstrap |
| 2026-06-23 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_task8_api .venv/bin/pytest tests/test_api.py tests/integration/test_api_postgres.py tests/test_openapi_contract.py -q` | PASS, 13 tests | Durable API wiring across app restarts plus API/OpenAPI contract regression |
| 2026-06-23 | `.venv/bin/pytest -q` | PASS, 90 tests plus 28 expected database skips | Full non-database Python regression after durable API wiring |
| 2026-06-23 | `.venv/bin/ruff check .` | PASS | Full repository Ruff check after durable API wiring |
| 2026-06-23 | `.venv/bin/mypy src` | PASS | Full strict typing after durable API wiring |
| 2026-06-23 | `.venv/bin/python scripts/export_openapi.py --check` | PASS | Deterministic OpenAPI artifact unchanged by durable API wiring |
| 2026-06-23 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_task8_full .venv/bin/pytest tests/integration -q` | PASS, 29 tests | Full clean-database PostgreSQL integration regression after durable API wiring |
| 2026-06-23 | `npm --prefix typescript run client:check` | PASS | Generated TypeScript API client matches OpenAPI artifact |
| 2026-06-23 | `npm --prefix typescript run typecheck` | PASS | TypeScript canonical and generated API client compile |
| 2026-06-23 | `npm --prefix typescript test` | PASS, 14 tests | TypeScript canonical parity tests after generated client addition |
| 2026-06-23 | `.venv/bin/ruff check scripts/check_typescript_client.py` | PASS | Client generator/check script lint |
| 2026-06-23 | `.venv/bin/ruff check .` | PASS | Final M1A full repository Ruff gate |
| 2026-06-23 | `.venv/bin/mypy` | PASS | Final M1A strict typing gate |
| 2026-06-23 | `.venv/bin/python scripts/export_openapi.py --check` | PASS | Final M1A OpenAPI drift gate |
| 2026-06-23 | `.venv/bin/pytest -m "not postgres" -q` | PASS, 89 tests, 29 deselected | Final M1A non-PostgreSQL pytest gate |
| 2026-06-23 | `npm --prefix typescript run typecheck && npm --prefix typescript run client:check` | PASS | Final M1A TypeScript typecheck and generated-client drift gate |
| 2026-06-23 | `npm --prefix typescript test` | PASS, 14 tests | Final M1A TypeScript test gate |
| 2026-06-23 | `uv build` | PASS | Final M1A source distribution and wheel build |
| 2026-06-23 | PostgreSQL role bootstrap via PostgreSQL 17 `psql`, twice on `canopyledger_m1a_final2` | PASS | Final M1A idempotent capability-role/schema bootstrap equivalent to `tests/integration/test_database_roles.sh` setup |
| 2026-06-23 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_m1a_final2 uv run alembic upgrade head && ... uv run alembic check && ... .venv/bin/pytest -m postgres -q` | PASS, 29 tests, 89 deselected | Final M1A PostgreSQL marker gate including durable API and replay tests |
| 2026-06-23 | `.venv/bin/pytest -q` | PASS, 90 tests plus 28 expected database skips | Final M1A full local pytest gate without `DATABASE_URL` |
| 2026-06-26 | `PATH=/private/tmp/canopyledger-psql-wrapper:$PATH DATABASE_URL=postgresql://postgres:canopyledger-test@localhost:55432/canopyledger_ci_pr_fix bash tests/integration/test_database_roles.sh` | PASS | CI database-role remediation on disposable PostgreSQL 17 database; role probe tables are removed before schema drift checks |
| 2026-06-26 | `DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_ci_pr_fix uv run alembic upgrade head && ... uv run alembic check` | PASS | Alembic reports no new upgrade operations after role-probe cleanup |
| 2026-07-06 | `uv run pytest tests/test_m1b_domain_pipeline.py tests/test_m1b_demo_surface.py -q` | PASS, 7 tests | Focused M1B unit normalization, receivables, CBB certificate, duplicate prevention, CLI, typed API demo |
| 2026-07-06 | `uv run ruff check src/canopyledger/api/app.py src/canopyledger/cli/cbb_demo.py src/canopyledger/borrowing_base/certificate.py src/canopyledger/receivables src/canopyledger/domain/units.py tests/test_m1b_domain_pipeline.py tests/test_m1b_demo_surface.py` | PASS | Focused M1B lint |
| 2026-07-06 | `uv run ruff check .` | PASS | Full repository lint after M1B receivables/certificate slice |
| 2026-07-06 | `uv run mypy` | PASS | Strict typing after M1B receivables/certificate slice |
| 2026-07-06 | `uv run python scripts/export_openapi.py --check` | PASS | Checked-in OpenAPI artifact includes M1B demo endpoint |
| 2026-07-06 | `uv run pytest -q` | PASS, 98 tests plus 28 expected PostgreSQL skips | Full non-database Python regression after M1B receivables/certificate slice |
| 2026-07-06 | `npm --prefix typescript run client:check` | PASS | Generated TypeScript API client matches updated OpenAPI artifact |
| 2026-07-06 | `npm --prefix typescript run typecheck` | PASS | TypeScript generated client and canonical contracts compile |
| 2026-07-06 | `npm --prefix typescript test` | PASS, 14 tests | TypeScript canonical parity tests after client regeneration |
| 2026-07-06 | `uv build` | PASS | Source distribution and wheel build after M1B receivables/certificate slice |
| 2026-07-06 | `uv run pytest tests/test_m1b_initial_pipeline.py tests/test_m1b_demo_surface.py -q` | PASS, 7 tests | Focused M1B market snapshot, S1-S4 stage graph, stage-output digest stability, typed pipeline API demo, certificate demo, and CLI |
| 2026-07-06 | `uv run ruff check .` | PASS | Full repository lint after M1B stage graph/API demo |
| 2026-07-06 | `uv run mypy` | PASS | Strict typing after M1B stage graph/API demo |
| 2026-07-06 | `uv run python scripts/export_openapi.py --check` | PASS | Checked-in OpenAPI artifact includes typed M1B pipeline demo endpoint |
| 2026-07-06 | `uv run pytest -q` | PASS, 102 tests plus 28 expected PostgreSQL skips | Full non-database Python regression after M1B stage graph/API demo |
| 2026-07-06 | `npm --prefix typescript run client:check` | PASS | Generated TypeScript API client matches updated OpenAPI artifact after M1B pipeline route |
| 2026-07-06 | `npm --prefix typescript run typecheck` | PASS | TypeScript generated client and canonical contracts compile after M1B pipeline route |
| 2026-07-06 | `npm --prefix typescript test` | PASS, 14 tests | TypeScript canonical parity tests after M1B pipeline client regeneration |
| 2026-07-06 | `uv build` | PASS | Source distribution and wheel build after M1B stage graph/API demo |
| 2026-07-06 | `env DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_m1b_verify uv run pytest tests/integration/test_m1b_postgres_pipeline.py -q` | PASS, 1 test | M1B PostgreSQL run/stage/output publication and replay-package visibility on fresh database |
| 2026-07-06 | `env DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_m1b_full uv run pytest -m postgres -q` | PASS, 30 tests, 102 deselected | Full PostgreSQL marker regression including M1B publication |
| 2026-07-06 | `uv run pytest -q` | PASS, 103 tests plus 29 expected PostgreSQL skips | Full non-database Python regression after M1B PostgreSQL runner |
| 2026-07-06 | `uv run ruff check .` | PASS | Full repository lint after M1B PostgreSQL runner |
| 2026-07-06 | `uv run mypy` | PASS | Strict typing after M1B PostgreSQL runner |
| 2026-07-06 | `uv run python scripts/export_openapi.py --check` | PASS | OpenAPI unchanged after M1B PostgreSQL runner |
| 2026-07-06 | `npm --prefix typescript run client:check` | PASS | Generated TypeScript API client unchanged after M1B PostgreSQL runner |
| 2026-07-06 | `npm --prefix typescript run typecheck` | PASS | TypeScript generated client and canonical contracts compile after M1B PostgreSQL runner |
| 2026-07-06 | `npm --prefix typescript test` | PASS, 14 tests | TypeScript canonical parity tests after M1B PostgreSQL runner |
| 2026-07-06 | `uv build` | PASS | Source distribution and wheel build after M1B PostgreSQL runner |
| 2026-07-07 | `uv run pytest tests/test_m1b_initial_pipeline.py tests/test_m1b_golden_fixture.py tests/test_m1b_domain_pipeline.py -q` | PASS, 14 tests | Focused M1B formula golden, unit normalization, currency normalization, rounding, reason-code, reserve, monotonic, duplicate-collateral, and invalid-number guard coverage |
| 2026-07-07 | `uv run ruff check .` | PASS | Final M1B full repository Ruff gate |
| 2026-07-07 | `uv run mypy` | PASS | Final M1B strict typing gate |
| 2026-07-07 | `uv run python scripts/export_openapi.py --check` | PASS | Final M1B checked-in OpenAPI drift gate |
| 2026-07-07 | `uv run pytest -q` | PASS, 108 tests plus 29 expected PostgreSQL skips | Final M1B full local pytest gate without `DATABASE_URL` |
| 2026-07-07 | `npm --prefix typescript run client:check` | PASS | Final M1B generated TypeScript API client drift gate |
| 2026-07-07 | `npm --prefix typescript run typecheck` | PASS | Final M1B TypeScript compile gate |
| 2026-07-07 | `npm --prefix typescript test` | PASS, 14 tests | Final M1B TypeScript canonical parity tests |
| 2026-07-07 | `uv build` | PASS | Final M1B source distribution and wheel build |
| 2026-07-07 | `env DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:55432/canopyledger_m1b_final_audit uv run pytest -m postgres -q` | PASS, 30 tests, 107 deselected | Final M1B fresh-database PostgreSQL marker gate |

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
| 2026-06-22 | Worker authority is a live worker/epoch/input tuple | Heartbeats cannot exceed the attempt maximum; stale or expired workers cannot publish; output, stage/attempt completion, downstream outbox, and audit commit together |
| 2026-06-26 | CodeQL CI runs without SARIF upload until repository code scanning is enabled | SAST gate can execute queries in CI without failing on disabled GitHub code scanning repository settings |

## Maintenance rules

- Update this file in the same commit as milestone-status changes.
- Record exact test/lint/build commands and results.
- Never mark `DONE` based only on code presence.
- Record blockers immediately.
- Amend `CANOPYLEDGER_MASTER_PLAN.md` through decision-log entry; never silently drift requirements.
