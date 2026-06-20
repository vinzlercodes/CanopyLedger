# CanopyLedger Build Progress

**Canonical plan:** [CANOPYLEDGER_MASTER_PLAN.md](CANOPYLEDGER_MASTER_PLAN.md)
**Condensed implementation guide:** [MASTER_PLAN.md](MASTER_PLAN.md)
**Last updated:** 2026-06-21
**Current phase:** M0 normative foundation plus M1A/M1B vertical slice

## Status vocabulary

- `NOT_STARTED`: no implementation.
- `IN_PROGRESS`: active work; acceptance gate incomplete.
- `BLOCKED`: external decision/dependency prevents progress.
- `DONE`: acceptance gate passed with recorded evidence.

## Milestones

| Milestone | Status | Built | Remaining | Gate evidence |
|---|---|---|---|---|
| M0 Normative foundation | IN_PROGRESS | Plan; tracker; Python scaffold; CI; Apache-2.0 license; state-machine, invariant, resource, error, role, bundle, calculation, and acceptance-test contracts | Versioned OpenAPI artifact; database privilege implementation; OSS landscape evidence review; executable state-machine coverage | 47 tests plus lint/type gates pass; full M0 gate pending |
| M1A Integrity kernel | IN_PROGRESS | Canonical value profile; immutable snapshot manifest/digest; idempotency fingerprint/replay; fenced stage publication domain protocol; local immutable object store; facility/snapshot API slice | PostgreSQL schema and serializable freeze transaction; transactional output/outbox publication; inbox; crash/concurrency tests; TypeScript vectors/client; Level A/B replay harness | Pure-domain and in-memory API tests pass; persistence gate pending |
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

## Active work

1. Define PostgreSQL resource schema and Alembic baseline.
2. Implement short serializable snapshot-freeze transaction with outbox insertion.
3. Implement transactional fenced stage publication.
4. Export/version OpenAPI and generate the TypeScript client.
5. Expand M1B into receivables, persisted outputs, certificate JSON, and golden fixtures.

## Remaining work

All roadmap items not marked `DONE` remain required. Current API repositories, idempotency records,
pipeline stages, snapshots, and outbox are in-memory only. They are functional scaffolding, not the
required durable implementation. Detailed requirements live in `CANOPYLEDGER_MASTER_PLAN.md` and
contract files.

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

## Decision/change log

| Date | Decision | Effect |
|---|---|---|
| 2026-06-21 | Backend-first modular monolith | Python integrity/domain kernel precedes UI |
| 2026-06-21 | No foundation-model training | Only M6 small CPU statistical fitting allowed |
| 2026-06-21 | Independent CBB and IRC | Decision compares uncapped values |
| 2026-06-21 | M1 split into M1A/M1B | Integrity semantics verified before finance formulas |

## Maintenance rules

- Update this file in the same commit as milestone-status changes.
- Record exact test/lint/build commands and results.
- Never mark `DONE` based only on code presence.
- Record blockers immediately.
- Amend `CANOPYLEDGER_MASTER_PLAN.md` through decision-log entry; never silently drift requirements.
