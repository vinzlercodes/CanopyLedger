# M1A Integrity Kernel Design

## Status and authority

This design implements M1A from `CANOPYLEDGER_MASTER_PLAN.md`. The master plan and the contracts
under `docs/contracts/` remain authoritative. This document selects implementation boundaries and
does not weaken or redefine snapshot immutability, bundle pinning, idempotency, fenced publication,
auditability, or reproducibility.

The generated TypeScript API client listed as remaining M1A work in `PROGRESS.md` is in scope.

## Outcome

A facility working aggregate can be durably created and versioned, frozen once into an immutable
content-addressed snapshot, dispatched through an outbox, and replayed and verified. Pipeline work
can be claimed at least once while only the current lease epoch can publish one immutable output.
Duplicate commands and events are deterministic. Python and TypeScript produce identical canonical
bytes and digests.

## Architecture

M1A uses a modular monolith with three boundary types:

1. Pure integrity contracts define canonicalization, snapshot manifests, idempotency fingerprints,
   lease rules, and replay verification without importing FastAPI or SQLAlchemy.
2. Application services define transaction-sized operations: facility commands, snapshot freeze,
   bundle publication, queue claim/heartbeat/publication, inbox consumption, and replay.
3. PostgreSQL adapters use SQLAlchemy Core and explicit transactions. Alembic owns schema changes.
   FastAPI and the CLI call application services rather than accessing tables directly.

SQLAlchemy Core is preferred to ORM lifecycle hooks because M1A depends on visible isolation levels,
row locks, unique constraints, compare-and-set updates, and atomic multi-table publication.

## Module boundaries

- `integrity/canonical.py`: normative Python Canonical Value Profile v1.
- `integrity/snapshot.py`: immutable snapshot and pinned-reference value contracts.
- `integrity/idempotency.py`: fingerprint and replay value contracts.
- `integrity/pipeline.py`: lease/fencing value contracts.
- `integrity/bundles.py`: immutable bundle types and canonical payload validation.
- `integrity/replay.py`: environment-independent digest and semantic replay verification.
- `application/ports.py`: transaction and repository protocols used by services.
- `application/facilities.py`: working aggregate create/update operations.
- `application/freeze.py`: short retryable serializable freeze transaction.
- `application/pipeline.py`: claim, heartbeat, inbox, and immutable publication services.
- `persistence/schema.py`: SQLAlchemy Core table metadata.
- `persistence/postgres.py`: engine/session setup and PostgreSQL repository implementations.
- `api/app.py`: HTTP translation and dependency wiring only.
- `cli/replay.py`: replay command and machine-readable verification result.

No financial calculation is moved into M1A. Existing M1B formula modules remain independent.

## Persistent resource model

The `canopyledger` schema contains:

- `facility_working_state`: mutable legal name, currency, commitment, integer version, and audit
  timestamps. Updates compare the expected version and increment it exactly once.
- `bundle`: immutable typed canonical payload, schema version, digest, creator, and creation time for
  market, policy, legal-interpretation, and computation bundles.
- `facility_snapshot`: immutable copied working values, source working version, as-of time, all four
  pinned bundle IDs/digests, canonical manifest bytes, and snapshot digest.
- `snapshot_input_reference`: ordered immutable references copied into a snapshot.
- `idempotency_record`: scope, request fingerprint, state, original response status/headers/body,
  created/completed timestamps, and retention time.
- `idempotency_tombstone`: permanent scope reservation after active response expiry.
- `outbox_message`: immutable message identity/payload plus mutable delivery bookkeeping.
- `inbox_receipt`: consumer and message identity with first-seen timestamp; the pair is unique.
- `pipeline_run`, `pipeline_stage`, and `pipeline_stage_attempt`: deterministic run/stage keys,
  status, lease owner, monotonic epoch, expiry, heartbeat and retry history.
- `pipeline_stage_output`: unique publication key, input digest, output digest, canonical payload,
  snapshot and computation-bundle references, and publishing attempt/epoch.
- `audit_event`: append-only actor, action, resource, correlation, causation, before/after digests,
  structured metadata, and occurred-at time.

Immutable tables reject `UPDATE` and `DELETE` through database triggers. Foreign keys prevent bundle
deletion while referenced; triggers deny deletion even before references exist. Application roles
receive only the table privileges needed by the role matrix. Database time supplies operational
timestamps; business times remain explicit inputs.

## Canonical data and hashing

Canonical JSON follows the master plan profile: NFC strings, fixed-point decimal strings with
declared scale, UTC timestamps with six fractional digits, integer-only JSON numbers, no floats,
schema-declared set ordering, and stable object-key ordering. Uploaded bytes remain byte-exact.

Digests use `SHA256("canopyledger:<artifact-type>:v<version>\\0" || canonical_bytes)` and retain
the `sha256:` textual prefix. Snapshot manifests pin market, policy, legal-interpretation, and
computation bundles. Their canonical payload excludes the derived snapshot digest.

A checked-in JSON vector corpus is the single cross-runtime conformance source. Python pytest and a
Node test runner consume the same file and compare canonical UTF-8 bytes, successful digests, and
declared rejection cases. The TypeScript implementation does not use JavaScript `number` for
authoritative decimals.

## Command idempotency

The idempotency scope is actor, operation, resource namespace, and key. The fingerprint contains the
canonical method, normalized path, schema version, selected normalized headers, canonical defaulted
body, and file digests where applicable.

Within the same database transaction as the command:

1. Insert a `PENDING` idempotency record or lock the existing scope.
2. Reject tombstoned reuse or a different fingerprint with `IDEMPOTENCY_KEY_REUSED`.
3. Replay the original completed status, selected headers, and body for the same fingerprint.
4. Return deterministic `IDEMPOTENCY_IN_PROGRESS` for an unexpired `PENDING` owner.
5. Execute the command and finalize the stored response atomically.

A transaction rollback removes both the command effect and an uncommitted idempotency claim.
Seven-year active retention transitions to durable tombstones; a key never silently gains new
meaning.

## Serializable snapshot freeze

Freeze is one short `SERIALIZABLE` transaction retried from the beginning for SQLSTATE `40001`:

1. Acquire or replay the idempotency scope.
2. Lock the facility row and verify the strong `If-Match` version.
3. Validate facility values and snapshot inputs.
4. Resolve and validate all four immutable bundles by both ID and digest.
5. Construct copied immutable snapshot values and canonical manifest bytes.
6. Insert the snapshot and ordered input references.
7. Insert the deterministic pipeline-start outbox message.
8. Insert the append-only audit event.
9. Finalize the stored idempotent HTTP response and commit.

A unique `(facility_id, working_version)` constraint makes a concurrent freeze race deterministic.
No extraction, network access, calculation, rendering, model call, or worker wait occurs inside the
transaction.

## Queue, inbox, and publication

Claim selects an eligible stage with `FOR UPDATE SKIP LOCKED`, changes it to `RUNNING`, increments
`lease_epoch`, records a new attempt, and assigns a bounded expiry. Heartbeats are compare-and-set
updates on stage, worker, epoch, and a live lease; they cannot exceed the configured maximum lease
lifetime.

Consumers first insert a unique inbox receipt. A duplicate returns the stored consumption outcome
without repeating the side effect.

Publication is one transaction that locks the stage and verifies `RUNNING`, current worker and
epoch, unexpired lease, unchanged run inputs, versioned output schema, and calculated digests. It
then inserts the uniquely keyed immutable output, marks the stage succeeded, closes the attempt,
inserts downstream outbox messages, and appends an audit event. A stale worker may finish local
computation but receives `STAGE_PUBLICATION_FENCED` and cannot publish.

If a process crashes before commit, none of the publication is visible. If it crashes after commit,
redelivery observes the inbox/unique publication records and returns the original result.

## Replay and verification

The replay CLI accepts a snapshot ID and database URL. It loads only immutable snapshot state,
verifies every referenced bundle/input digest, reconstructs canonical manifest bytes, and compares
the snapshot digest. It also verifies published stage input/output digests and unique publication
keys.

Level A reports whether the recorded runtime envelope exactly matches the current environment.
Level B reconstructs supported canonical artifacts and requires exact decimal strings, reason codes,
categorical values, published quantization, and canonical JSON. M1A has no floating-point financial
engine, so its semantic replay gate is exact. Output is deterministic JSON and a nonzero exit status
indicates any mismatch.

## API and TypeScript client

The application factory accepts injected services. Production wiring uses PostgreSQL; tests may use
an explicit in-memory adapter for narrow HTTP contract tests. Durable integration tests exercise the
same API against PostgreSQL.

OpenAPI remains deterministically exported and drift-tested. A pinned generator creates a checked-in
TypeScript client. A check command regenerates into a temporary directory and compares bytes, so CI
detects stale client output.

## Errors and audit

Database and domain failures map to the existing Problem Details contract. M1A adds documented
codes for in-progress idempotency and unavailable/retry-exhausted infrastructure while preserving
the required `409`, `412`, `422`, and `503` classifications.

Every successful mutation and rejected integrity-sensitive transition records actor, operation,
resource, trace/correlation identity, reason where applicable, and relevant digests. Audit rows are
append-only and cannot be written by analytics/reporting roles.

## Test strategy and gates

All behavior changes follow red-green-refactor. PostgreSQL tests run against a disposable database
and prove behavior rather than merely inspecting DDL.

M1A evidence includes:

- shared positive and rejection canonical vectors in Python and TypeScript;
- concurrent freeze with one immutable snapshot/outbox result and deterministic loser behavior;
- forced serialization failure followed by whole-transaction retry;
- identical-command replay and changed-fingerprint conflict;
- crash before/after commit for command and stage publication;
- stale and expired lease publication rejection;
- duplicate inbox event suppression;
- bundle update and deletion denial under application and migration-owner paths;
- immutable snapshot/output update and deletion denial;
- replay success plus deliberate digest-corruption detection;
- deterministic OpenAPI and TypeScript client drift checks;
- role privilege, lint, type-check, full pytest, package build, and PostgreSQL integration gates.

M1A is not marked `DONE` until these commands run successfully and `PROGRESS.md` records their exact
results.

## Migration and compatibility

The existing in-memory implementation has no durable user data and requires no data migration.
Existing public API shapes remain stable except where the authoritative contract requires the
legal-interpretation bundle. OpenAPI and the generated client change together. Existing M1B tests
continue to run but do not count as M1A evidence.

## Out of scope

- M1B inventory/receivables persistence and authoritative financial pipeline stages.
- Evidence approval workflows beyond the M1A snapshot-reference integrity needed for freezing.
- External queue brokers, cloud object stores, report rendering, models, agents, or UI work.
- Relaxing any master-plan invariant to accommodate the current in-memory API.
