# M1A Integrity Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the complete M1A integrity contract durable and executable: immutable bundle-pinned
snapshots, transactional idempotency/outbox/inbox, PostgreSQL lease fencing and publication,
cross-runtime canonical parity, replay verification, audit history, and generated TypeScript API
client.

**Architecture:** Keep canonical and integrity rules as pure Python/TypeScript contracts. Put
transaction-sized behavior in application services and use SQLAlchemy Core PostgreSQL adapters with
explicit isolation, locking, constraints, and immutable-table triggers. FastAPI and the replay CLI
depend on those services; Alembic owns the schema.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLAlchemy Core 2, psycopg 3, Alembic, PostgreSQL
17, pytest/Hypothesis, TypeScript, Node test runner, and a pinned OpenAPI TypeScript generator.

---

## File map

New production files:

- `alembic.ini`: Alembic configuration.
- `migrations/env.py`: metadata and database URL wiring.
- `migrations/script.py.mako`: deterministic revision template.
- `migrations/versions/20260621_01_m1a_integrity_kernel.py`: complete M1A schema, grants, and
  immutability functions/triggers.
- `src/canopyledger/integrity/bundles.py`: bundle type, canonical payload, and digest contracts.
- `src/canopyledger/integrity/replay.py`: pure replay verification result and digest checks.
- `src/canopyledger/application/__init__.py`: application package boundary.
- `src/canopyledger/application/models.py`: command/result records shared by services and adapters.
- `src/canopyledger/application/ports.py`: integrity store protocol and transaction callbacks.
- `src/canopyledger/application/integrity.py`: facility, bundle, freeze, queue, inbox, publication,
  and replay services.
- `src/canopyledger/persistence/__init__.py`: persistence package boundary.
- `src/canopyledger/persistence/schema.py`: SQLAlchemy Core metadata and table definitions.
- `src/canopyledger/persistence/postgres.py`: PostgreSQL integrity store implementation.
- `src/canopyledger/cli/__init__.py`: CLI package boundary.
- `src/canopyledger/cli/replay.py`: `canopyledger-replay` entry point.
- `canonical-vectors/v1.json`: shared positive and rejection vectors.
- `typescript/src/canonical.ts`: TypeScript Canonical Value Profile v1.
- `typescript/test/canonical.test.ts`: shared-vector Node tests.
- `typescript/generated/`: checked-in OpenAPI client.
- `scripts/check_typescript_client.py`: temporary regeneration and byte-drift check.

New test files:

- `tests/test_shared_canonical_vectors.py`
- `tests/test_bundles.py`
- `tests/test_replay.py`
- `tests/integration/conftest.py`
- `tests/integration/test_m1a_schema.py`
- `tests/integration/test_postgres_idempotency.py`
- `tests/integration/test_postgres_freeze.py`
- `tests/integration/test_postgres_pipeline.py`
- `tests/integration/test_postgres_replay.py`
- `tests/integration/test_api_postgres.py`

Existing files changed:

- `pyproject.toml`, `uv.lock`: psycopg, entry point, and test markers.
- `src/canopyledger/integrity/snapshot.py`: legal-interpretation bundle and manifest alignment.
- `src/canopyledger/api/app.py`: injected integrity service and durable production factory.
- `src/canopyledger/api/openapi.py`, `docs/api/openapi-v1.json`: updated contract.
- `tests/test_snapshot_manifest.py`, `tests/test_api.py`, `tests/test_openapi_contract.py`: required
  legal bundle and adapter-aware API tests.
- `docs/contracts/errors.md`: deterministic in-progress and infrastructure errors.
- `database/bootstrap/roles.sql`: table-specific role grants remain migration-owned.
- `.github/workflows/ci.yml`, `Makefile`: PostgreSQL M1A and TypeScript gates.
- `.gitignore`: Node build/cache exclusions while keeping generated client tracked.
- `PROGRESS.md`: exact built scope and fresh verification evidence.

### Task 1: Establish the PostgreSQL migration and test harness

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260621_01_m1a_integrity_kernel.py`
- Create: `src/canopyledger/persistence/__init__.py`
- Create: `src/canopyledger/persistence/schema.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_m1a_schema.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `Makefile`

- [ ] **Step 1: Add the failing schema contract test**

Create a PostgreSQL-marked test that upgrades an empty disposable database and asserts the exact M1A
tables, primary/unique/foreign-key constraints, immutable triggers, and role grants. Its core table
assertion is:

```python
EXPECTED_TABLES = {
    "facility_working_state",
    "bundle",
    "facility_snapshot",
    "snapshot_input_reference",
    "idempotency_record",
    "idempotency_tombstone",
    "outbox_message",
    "inbox_receipt",
    "pipeline_run",
    "pipeline_stage",
    "pipeline_stage_attempt",
    "pipeline_stage_output",
    "audit_event",
}

def test_m1a_migration_creates_complete_resource_schema(connection: Connection) -> None:
    rows = connection.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'canopyledger'")
    )
    assert {row.tablename for row in rows} == EXPECTED_TABLES
```

- [ ] **Step 2: Run the schema test and verify RED**

Run:

```bash
DATABASE_URL=postgresql+psycopg://postgres:canopyledger-test@localhost:5432/canopyledger \
  uv run pytest tests/integration/test_m1a_schema.py -q
```

Expected: FAIL because the revision and tables do not exist.

- [ ] **Step 3: Add the driver, metadata, Alembic environment, and baseline revision**

Add `psycopg[binary]>=3.2,<4` to runtime dependencies and register the marker:

```toml
[tool.pytest.ini_options]
markers = ["postgres: requires a disposable PostgreSQL database"]
```

Define every table in `persistence/schema.py` with named constraints. In the revision, create the
tables from that metadata, then add PostgreSQL partial indexes, the immutable-row trigger function,
triggers for bundles/snapshots/inputs/outputs/audit events, and role-specific grants. Mutable outbox
delivery columns are not covered by the immutable trigger; message identity and payload are guarded
by a dedicated trigger.

- [ ] **Step 4: Run migration upgrade/downgrade and verify GREEN**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_m1a_schema.py -q
uv run alembic downgrade base
uv run alembic upgrade head
```

Expected: all commands exit 0 and the schema test passes.

- [ ] **Step 5: Extend CI and Make targets**

Add `test-m1a-postgres`, `migrate`, and `migrate-check` targets. Extend the PostgreSQL CI job to run
bootstrap, upgrade, and all `tests/integration` tests with the SQLAlchemy URL.

- [ ] **Step 6: Commit the schema slice**

```bash
git add pyproject.toml uv.lock alembic.ini migrations src/canopyledger/persistence \
  tests/integration .github/workflows/ci.yml Makefile
git commit -m "feat(m1a): add durable integrity resource schema"
```

### Task 2: Complete canonical and snapshot contracts across Python and TypeScript

**Files:**
- Create: `canonical-vectors/v1.json`
- Create: `typescript/package.json`
- Create: `typescript/tsconfig.json`
- Create: `typescript/src/canonical.ts`
- Create: `typescript/test/canonical.test.ts`
- Create: `tests/test_shared_canonical_vectors.py`
- Modify: `src/canopyledger/integrity/canonical.py`
- Modify: `src/canopyledger/integrity/snapshot.py`
- Modify: `tests/test_canonical_profile.py`
- Modify: `tests/test_snapshot_manifest.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add shared vectors and failing Python/TypeScript tests**

Vectors include nested key ordering, NFC normalization, fixed decimal strings, integer preservation,
UTC microseconds, ordered arrays, declared sets, domain-separated digest, and rejection of floats,
negative zero, exponent decimals, naïve timestamps, duplicate set identities, and missing sort keys.
Both runtimes assert the vector's UTF-8 text and digest exactly.

Add the legal-bundle manifest expectation:

```python
manifest = SnapshotManifest(
    snapshot_id=SNAPSHOT_ID,
    facility_id=FACILITY_ID,
    facility_working_version=7,
    as_of=AS_OF,
    market_bundle=MARKET,
    policy_bundle=POLICY,
    legal_interpretation_bundle=LEGAL,
    computation_bundle=COMPUTATION,
    inputs=(),
)
assert b'"legal_interpretation_bundle"' in manifest.canonical_bytes
```

- [ ] **Step 2: Verify RED in both runtimes**

```bash
uv run pytest tests/test_shared_canonical_vectors.py tests/test_snapshot_manifest.py -q
npm --prefix typescript test
```

Expected: Python fails on the missing legal bundle/shared corpus and Node fails on the missing
implementation.

- [ ] **Step 3: Implement minimal cross-runtime canonical behavior**

Use tagged vector input values so JSON does not coerce decimals or timestamps into JavaScript
numbers. TypeScript exposes:

```typescript
export type CanonicalValue = null | boolean | bigint | string | CanonicalValue[] |
  { readonly [key: string]: CanonicalValue };

export function canonicalJson(value: CanonicalValue, rules: readonly SetRule[] = []): string;
export function domainDigest(artifactType: string, version: bigint, bytes: Uint8Array): string;
```

Add `legal_interpretation_bundle` to `SnapshotManifest`, canonical bytes, API models, and all fixtures.

- [ ] **Step 4: Verify GREEN and parity**

```bash
uv run pytest tests/test_canonical_profile.py tests/test_shared_canonical_vectors.py \
  tests/test_snapshot_manifest.py -q
npm --prefix typescript test
```

Expected: both suites pass every shared vector.

- [ ] **Step 5: Commit canonical parity**

```bash
git add canonical-vectors typescript src/canopyledger/integrity/canonical.py \
  src/canopyledger/integrity/snapshot.py tests .gitignore
git commit -m "feat(m1a): enforce cross-runtime canonical parity"
```

### Task 3: Implement immutable bundle publication

**Files:**
- Create: `src/canopyledger/integrity/bundles.py`
- Create: `tests/test_bundles.py`
- Modify: `src/canopyledger/persistence/postgres.py`
- Create: `tests/integration/test_postgres_bundles.py`

- [ ] **Step 1: Write failing bundle contract and database immutability tests**

Test all four bundle types, digest calculation, idempotent same-content publication, same-ID/different-
content rejection, SQL `UPDATE` denial, and SQL `DELETE` denial. The domain API is:

```python
bundle = VersionBundle.build(
    resource_id=BUNDLE_ID,
    bundle_type=BundleType.POLICY,
    schema_version="1.0",
    payload={"advance_rate": "0.80"},
    created_by=ACTOR_ID,
    created_at=NOW,
)
assert bundle.digest == domain_digest("policy_bundle", 1, bundle.canonical_bytes)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_bundles.py tests/integration/test_postgres_bundles.py -q
```

Expected: FAIL because bundle contracts/store do not exist.

- [ ] **Step 3: Implement bundle contracts and PostgreSQL publication**

`VersionBundle` is frozen and validates resource prefix, type-specific domain separator, aware
creation time, canonical payload, and digest. `PostgresIntegrityStore.publish_bundle` uses one insert;
on conflict it returns the existing identical bundle or raises `ImmutableBundleConflict`.

- [ ] **Step 4: Verify GREEN**

```bash
uv run pytest tests/test_bundles.py tests/integration/test_postgres_bundles.py -q
```

- [ ] **Step 5: Commit bundle registry**

```bash
git add src/canopyledger/integrity/bundles.py src/canopyledger/persistence/postgres.py \
  tests/test_bundles.py tests/integration/test_postgres_bundles.py
git commit -m "feat(m1a): add immutable bundle registry"
```

### Task 4: Make facility commands and idempotency transactional

**Files:**
- Create: `src/canopyledger/application/__init__.py`
- Create: `src/canopyledger/application/models.py`
- Create: `src/canopyledger/application/ports.py`
- Create: `src/canopyledger/application/integrity.py`
- Modify: `src/canopyledger/persistence/postgres.py`
- Create: `tests/integration/test_postgres_idempotency.py`
- Modify: `docs/contracts/errors.md`

- [ ] **Step 1: Write failing transaction and replay tests**

Cover create/update persistence, version compare-and-set, same request replay byte-for-byte, changed
fingerprint conflict, actor/operation namespace isolation, deterministic in-progress response,
rollback after command failure, seven-year expiry, and permanent tombstone rejection.

The service result retains exact wire data:

```python
@dataclass(frozen=True)
class CommandResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    replayed: bool = False
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/integration/test_postgres_idempotency.py -q
```

- [ ] **Step 3: Implement the unit-of-work callback and idempotency state machine**

`execute_idempotent(scope, fingerprint, now, callback)` opens one transaction, locks/creates the
scope, and runs the callback only for a newly owned `PENDING` record. It stores exact status,
selected headers, and bytes before commit. PostgreSQL unique constraints arbitrate concurrent first
use. Expiry moves the scope to a tombstone in one transaction.

- [ ] **Step 4: Verify GREEN including forced rollback**

```bash
uv run pytest tests/test_idempotency.py tests/integration/test_postgres_idempotency.py -q
```

- [ ] **Step 5: Commit transactional command handling**

```bash
git add src/canopyledger/application src/canopyledger/persistence/postgres.py \
  tests/integration/test_postgres_idempotency.py docs/contracts/errors.md
git commit -m "feat(m1a): persist transactional command idempotency"
```

### Task 5: Implement serializable snapshot freeze and outbox publication

**Files:**
- Modify: `src/canopyledger/application/integrity.py`
- Modify: `src/canopyledger/persistence/postgres.py`
- Create: `tests/integration/test_postgres_freeze.py`

- [ ] **Step 1: Write failing freeze acceptance tests**

Tests create all four bundles and a facility, then cover successful copied-state freeze, all pinned
references, one outbox/audit row, stale `If-Match`, missing/mismatched bundle digest, duplicate input,
concurrent freeze race, identical idempotent replay, changed request conflict, and no partial rows
after an injected failure.

Add a retry seam and force SQLSTATE `40001` on the first attempt:

```python
attempts = 0
def observe_attempt(number: int) -> None:
    nonlocal attempts
    attempts = number
    if number == 1:
        raise SerializationFailureForTest()

result = service.freeze(command, observe_attempt=observe_attempt)
assert attempts == 2
assert result.status == 201
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/integration/test_postgres_freeze.py -q
```

- [ ] **Step 3: Implement whole-transaction serializable retry**

The retry wrapper creates a fresh connection/transaction for each attempt with
`isolation_level="SERIALIZABLE"`, retries only SQLSTATE `40001` using bounded attempts, and never
reuses loaded state. The transaction locks the facility, verifies expected version, loads all four
bundles by ID/digest, constructs the manifest, inserts snapshot/input rows, one deterministic
pipeline-start outbox row, one audit row, and the completed idempotency response.

- [ ] **Step 4: Run concurrency/crash/retry tests and verify GREEN**

```bash
uv run pytest tests/integration/test_postgres_freeze.py -q
```

- [ ] **Step 5: Commit freeze transaction**

```bash
git add src/canopyledger/application/integrity.py src/canopyledger/persistence/postgres.py \
  tests/integration/test_postgres_freeze.py
git commit -m "feat(m1a): freeze snapshots in serializable transaction"
```

### Task 6: Implement leased jobs, inbox deduplication, and fenced immutable publication

**Files:**
- Modify: `src/canopyledger/application/models.py`
- Modify: `src/canopyledger/application/integrity.py`
- Modify: `src/canopyledger/persistence/postgres.py`
- Create: `tests/integration/test_postgres_pipeline.py`

- [ ] **Step 1: Write failing queue and publication tests**

Cover `SKIP LOCKED` concurrent claims, monotonic epochs, active-lease conflict, expired reclaim,
bounded heartbeat, maximum lease lifetime, stale epoch/worker rejection, expired lease rejection,
input digest mismatch, output schema rejection, one unique output, duplicate event suppression,
crash before commit, redelivery after commit, downstream outbox, and audit insertion.

The main service contracts are:

```python
lease = service.claim_stage(worker_id="worker-a", now=NOW, lease_duration=timedelta(seconds=30))
service.heartbeat(stage_id=lease.stage_id, worker_id="worker-a", epoch=lease.epoch, now=LATER)
published = service.publish_stage(
    stage_id=lease.stage_id,
    worker_id="worker-a",
    epoch=lease.epoch,
    input_digest=INPUT_DIGEST,
    output_schema_version="test-stage-v1",
    output={"status": "verified"},
    now=PUBLISH_TIME,
)
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_stage_fencing.py tests/integration/test_postgres_pipeline.py -q
```

- [ ] **Step 3: Implement claim/heartbeat/inbox/publication transactions**

Claim uses a CTE selecting one eligible row `FOR UPDATE SKIP LOCKED`, increments epoch, and inserts
an attempt. Heartbeat is one guarded update. Inbox uses `INSERT ... ON CONFLICT DO NOTHING` and
stores deterministic outcome. Publication locks the stage, validates every fence and digest, inserts
the immutable output, closes stage/attempt, and inserts downstream outbox/audit rows atomically.

- [ ] **Step 4: Verify GREEN and crash behavior**

```bash
uv run pytest tests/test_stage_fencing.py tests/integration/test_postgres_pipeline.py -q
```

- [ ] **Step 5: Commit pipeline integrity**

```bash
git add src/canopyledger/application src/canopyledger/persistence/postgres.py \
  tests/integration/test_postgres_pipeline.py
git commit -m "feat(m1a): enforce fenced immutable stage publication"
```

### Task 7: Add replay verification and audit evidence

**Files:**
- Create: `src/canopyledger/integrity/replay.py`
- Create: `src/canopyledger/cli/__init__.py`
- Create: `src/canopyledger/cli/replay.py`
- Modify: `src/canopyledger/application/integrity.py`
- Modify: `src/canopyledger/persistence/postgres.py`
- Modify: `pyproject.toml`
- Create: `tests/test_replay.py`
- Create: `tests/integration/test_postgres_replay.py`

- [ ] **Step 1: Write failing replay tests**

Test exact snapshot/bundle/input/output verification, deterministic issue ordering, Level A envelope
match/mismatch, Level B exact semantic match, nonzero CLI exit on mismatch, deliberate digest
corruption detection performed through a privileged test transaction, and append-only audit rows.

```python
result = verify_replay(package, current_environment=environment)
assert result.level_a is ReplayStatus.MATCH
assert result.level_b is ReplayStatus.MATCH
assert result.issues == ()
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_replay.py tests/integration/test_postgres_replay.py -q
```

- [ ] **Step 3: Implement pure verification, package loading, and CLI**

Register:

```toml
[project.scripts]
canopyledger-replay = "canopyledger.cli.replay:main"
```

The CLI prints canonical JSON containing snapshot ID, stored/recomputed digests, Level A/B status,
and sorted typed issues. It returns 0 only when required verification levels match.

- [ ] **Step 4: Verify GREEN**

```bash
uv run pytest tests/test_replay.py tests/integration/test_postgres_replay.py -q
uv run canopyledger-replay --help
```

- [ ] **Step 5: Commit replay and audit verification**

```bash
git add src/canopyledger/integrity/replay.py src/canopyledger/cli \
  src/canopyledger/application/integrity.py src/canopyledger/persistence/postgres.py \
  pyproject.toml uv.lock tests/test_replay.py tests/integration/test_postgres_replay.py
git commit -m "feat(m1a): add semantic replay verifier"
```

### Task 8: Wire durable services into FastAPI

**Files:**
- Modify: `src/canopyledger/api/app.py`
- Modify: `src/canopyledger/api/openapi.py`
- Modify: `tests/test_api.py`
- Create: `tests/integration/test_api_postgres.py`
- Modify: `tests/test_openapi_contract.py`
- Modify: `docs/api/openapi-v1.json`

- [ ] **Step 1: Add failing injected-service and durable API tests**

Keep `create_app()` isolated for unit tests by injecting an `IntegrityService` port. Add
`create_postgres_app(database_url)` for production wiring. Durable tests restart the app between
requests and prove facilities, idempotent responses, snapshots, and manifests remain available.
Require `legal_interpretation_bundle` in `FreezeFacility` and its response.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_api.py tests/integration/test_api_postgres.py \
  tests/test_openapi_contract.py -q
```

- [ ] **Step 3: Refactor handlers to call the service boundary**

Handlers retain authentication, Pydantic validation, headers, Problem Details mapping, and response
translation. They do not create IDs, read tables, append outbox lists, or call the system clock for
canonical fields. Map application exceptions to existing typed error codes.

- [ ] **Step 4: Export OpenAPI and verify GREEN**

```bash
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
uv run pytest tests/test_api.py tests/integration/test_api_postgres.py \
  tests/test_openapi_contract.py -q
```

- [ ] **Step 5: Commit durable API wiring**

```bash
git add src/canopyledger/api tests/test_api.py tests/integration/test_api_postgres.py \
  tests/test_openapi_contract.py docs/api/openapi-v1.json
git commit -m "feat(m1a): expose durable integrity services through API"
```

### Task 9: Generate and drift-check the TypeScript API client

**Files:**
- Modify: `typescript/package.json`
- Create: `typescript/openapi-ts.config.ts`
- Create: `typescript/generated/`
- Create: `scripts/check_typescript_client.py`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add a failing generated-client drift test**

The check script copies configuration to a temporary directory, runs the pinned generator against
`docs/api/openapi-v1.json`, normalizes only generator-declared nondeterministic metadata, and compares
every generated relative path and byte sequence with `typescript/generated`.

- [ ] **Step 2: Verify RED**

```bash
npm --prefix typescript run client:check
```

Expected: FAIL because generated output is absent.

- [ ] **Step 3: Pin the generator and generate the client**

Commit `package-lock.json`. Generate typed operations for health, facility create/read/update, freeze,
and snapshot manifest retrieval. No generated source is manually edited.

- [ ] **Step 4: Verify GREEN and TypeScript compile**

```bash
npm --prefix typescript test
npm --prefix typescript run typecheck
npm --prefix typescript run client:check
```

- [ ] **Step 5: Commit generated client**

```bash
git add typescript scripts/check_typescript_client.py Makefile .github/workflows/ci.yml
git commit -m "feat(m1a): generate TypeScript API client"
```

### Task 10: Run the complete M1A gate and update progress

**Files:**
- Modify: `PROGRESS.md`
- Modify: `README.md`

- [ ] **Step 1: Run GitNexus change detection before documentation or commit**

```text
gitnexus_detect_changes({repo: "CanopyLedger", scope: "all"})
```

Review every changed symbol and affected execution flow. Run additional context/impact analysis if a
changed flow is outside M1A.

- [ ] **Step 2: Run all non-database verification**

```bash
uv run ruff check .
uv run mypy
uv run python scripts/export_openapi.py --check
uv run pytest -m "not postgres" -q
npm --prefix typescript test
npm --prefix typescript run typecheck
npm --prefix typescript run client:check
uv build
```

- [ ] **Step 3: Run all PostgreSQL acceptance evidence**

Against a fresh PostgreSQL 17 database:

```bash
bash tests/integration/test_database_roles.sh
uv run alembic upgrade head
uv run pytest -m postgres -q
```

Expected coverage explicitly includes concurrent freeze, serialization retry, crash replay, lease
fencing, duplicate inbox events, bundle/snapshot/output immutability, and semantic replay.

- [ ] **Step 4: Audit every M1A deliverable against executable evidence**

Create a requirement-to-test checklist from the master-plan deliverables and required tests. Do not
mark the milestone complete if any item has missing, indirect, or partial evidence.

- [ ] **Step 5: Update progress and usage documentation**

Record built inventory, remaining scope, exact commands/results, architectural decisions, and
blockers. Set M1A to `DONE` only if Step 4 proves every deliverable and gate. Add migration, database,
TypeScript, and replay commands to `README.md`.

- [ ] **Step 6: Re-run documentation-sensitive checks and detect final changes**

```bash
uv run ruff check .
uv run mypy
uv run python scripts/export_openapi.py --check
uv run pytest -q
```

Then run `gitnexus_detect_changes({repo: "CanopyLedger", scope: "all"})` again.

- [ ] **Step 7: Commit verified milestone evidence**

```bash
git add PROGRESS.md README.md
git commit -m "docs(m1a): record integrity kernel completion evidence"
```
