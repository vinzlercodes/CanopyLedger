"""Serializable PostgreSQL snapshot-freeze acceptance tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import Engine, func, select

from canopyledger.application.integrity import (
    BundleReferenceRejected,
    CreateFacilityCommand,
    FreezeFacilityCommand,
    IntegrityService,
    SnapshotAlreadyFrozen,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.snapshot import BundleReference, SnapshotInputReference
from canopyledger.persistence.postgres import (
    PostgresIntegrityStore,
    RetryableSerializationConflict,
)
from canopyledger.persistence.schema import (
    audit_event,
    facility_snapshot,
    idempotency_record,
    outbox_message,
    snapshot_input_reference,
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 6, 21, 12, tzinfo=UTC)
AS_OF = NOW - timedelta(hours=1)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def build_service(store: PostgresIntegrityStore) -> IntegrityService:
    return IntegrityService(store, clock=lambda: NOW)


def create_facility(service: IntegrityService) -> tuple[str, str]:
    result = service.create_facility(
        CreateFacilityCommand(
            actor_id=ACTOR_ID,
            idempotency_key=new_resource_id("key"),
            legal_name="Freeze Test Coffee BV",
            currency="EUR",
            facility_commitment="2500000.00",
            correlation_id=new_resource_id("cor"),
        )
    )
    return json.loads(result.body)["id"], result.headers["ETag"]


def publish_required_bundles(
    store: PostgresIntegrityStore,
) -> tuple[BundleReference, BundleReference, BundleReference, BundleReference]:
    references = []
    for bundle_type, prefix in (
        (BundleType.MARKET, "mkt"),
        (BundleType.POLICY, "pol"),
        (BundleType.LEGAL_INTERPRETATION, "leg"),
        (BundleType.COMPUTATION, "cmp"),
    ):
        resource_id = new_resource_id(prefix)
        bundle = VersionBundle.build(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version="1.0",
            payload={"name": bundle_type.value.lower(), "resource_id": resource_id},
            created_by=ACTOR_ID,
            created_at=NOW,
        )
        store.publish_bundle(bundle)
        references.append(bundle.reference)
    return tuple(references)  # type: ignore[return-value]


def freeze_command(
    facility_id: str,
    etag: str,
    references: tuple[BundleReference, BundleReference, BundleReference, BundleReference],
    *,
    idempotency_key: str | None = None,
) -> FreezeFacilityCommand:
    market, policy, legal, computation = references
    return FreezeFacilityCommand(
        actor_id=ACTOR_ID,
        facility_id=facility_id,
        idempotency_key=idempotency_key or new_resource_id("key"),
        if_match=etag,
        as_of=AS_OF,
        market_bundle=market,
        policy_bundle=policy,
        legal_interpretation_bundle=legal,
        computation_bundle=computation,
        inputs=(
            SnapshotInputReference(
                resource_type="approved_fact",
                resource_id=new_resource_id("fct"),
                digest=f"sha256:{'a' * 64}",
            ),
        ),
        correlation_id=new_resource_id("cor"),
    )


def test_freeze_copies_state_and_atomically_publishes_manifest_outbox_and_audit(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    service = build_service(store)
    facility_id, etag = create_facility(service)
    references = publish_required_bundles(store)

    result = service.freeze_facility(freeze_command(facility_id, etag, references))
    representation = json.loads(result.body)
    snapshot_id = representation["snapshot_id"]

    assert result.status == 201
    assert representation["schema_version"] == "1.0"
    assert representation["created_at"] == "2026-06-21T12:00:00.000000Z"
    assert representation["created_by"] == ACTOR_ID
    assert representation["legal_interpretation_bundle"] == {
        "resource_id": references[2].resource_id,
        "digest": references[2].digest,
    }

    with database_engine.connect() as connection:
        snapshot = (
            connection.execute(
                select(facility_snapshot).where(facility_snapshot.c.resource_id == snapshot_id)
            )
            .mappings()
            .one()
        )
        input_count = connection.execute(
            select(func.count())
            .select_from(snapshot_input_reference)
            .where(snapshot_input_reference.c.snapshot_id == snapshot_id)
        ).scalar_one()
        outbox_count = connection.execute(
            select(func.count())
            .select_from(outbox_message)
            .where(outbox_message.c.message_key == f"{facility_id}:1")
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count())
            .select_from(audit_event)
            .where(
                audit_event.c.resource_id == snapshot_id,
                audit_event.c.action == "snapshot.freeze",
            )
        ).scalar_one()
    assert snapshot["legal_name"] == "Freeze Test Coffee BV"
    assert snapshot["facility_commitment"] == "2500000.00"
    expected_manifest = dict(representation)
    del expected_manifest["digest"]
    assert json.loads(snapshot["canonical_manifest"]) == expected_manifest
    assert input_count == 1
    assert outbox_count == 1
    assert audit_count == 1


def test_freeze_rejects_bundle_reference_of_wrong_type(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    service = build_service(store)
    facility_id, etag = create_facility(service)
    references = publish_required_bundles(store)
    command = freeze_command(facility_id, etag, references)
    invalid = FreezeFacilityCommand(
        **{
            **command.__dict__,
            "market_bundle": references[1],
            "idempotency_key": new_resource_id("key"),
        }
    )
    with pytest.raises(BundleReferenceRejected, match="MARKET"):
        service.freeze_facility(invalid)


def test_serialization_failure_retries_entire_freeze_transaction(database_engine: Engine) -> None:
    attempts: list[int] = []

    def fail_first_attempt(attempt: int) -> None:
        attempts.append(attempt)
        if attempt == 1:
            raise RetryableSerializationConflict("injected SQLSTATE 40001")

    setup_store = PostgresIntegrityStore(database_engine)
    setup_service = build_service(setup_store)
    facility_id, etag = create_facility(setup_service)
    references = publish_required_bundles(setup_store)
    retrying_service = build_service(
        PostgresIntegrityStore(database_engine, serializable_attempt_hook=fail_first_attempt)
    )

    result = retrying_service.freeze_facility(freeze_command(facility_id, etag, references))
    assert result.status == 201
    assert attempts == [1, 2]


def test_failure_before_commit_leaves_no_snapshot_outbox_audit_or_idempotency(
    database_engine: Engine,
) -> None:
    setup_store = PostgresIntegrityStore(database_engine)
    setup_service = build_service(setup_store)
    facility_id, etag = create_facility(setup_service)
    references = publish_required_bundles(setup_store)
    command = freeze_command(facility_id, etag, references)

    def fail_before_commit() -> None:
        raise RuntimeError("injected process crash before commit")

    crashing_service = build_service(
        PostgresIntegrityStore(database_engine, before_serializable_commit=fail_before_commit)
    )
    with pytest.raises(RuntimeError, match="process crash before commit"):
        crashing_service.freeze_facility(command)

    with database_engine.connect() as connection:
        snapshot_count = connection.execute(
            select(func.count())
            .select_from(facility_snapshot)
            .where(facility_snapshot.c.facility_id == facility_id)
        ).scalar_one()
        outbox_count = connection.execute(
            select(func.count())
            .select_from(outbox_message)
            .where(outbox_message.c.topic == "pipeline.start")
            .where(outbox_message.c.message_key == f"{facility_id}:1")
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count())
            .select_from(audit_event)
            .where(audit_event.c.action == "snapshot.freeze")
            .where(audit_event.c.metadata["facility_id"].as_string() == facility_id)
        ).scalar_one()
        idempotency_count = connection.execute(
            select(func.count())
            .select_from(idempotency_record)
            .where(idempotency_record.c.idempotency_key == command.idempotency_key)
        ).scalar_one()
    assert (snapshot_count, outbox_count, audit_count, idempotency_count) == (0, 0, 0, 0)


def test_concurrent_freeze_creates_one_snapshot_and_deterministic_loser(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    service = build_service(store)
    facility_id, etag = create_facility(service)
    references = publish_required_bundles(store)
    commands = (
        freeze_command(facility_id, etag, references),
        freeze_command(facility_id, etag, references),
    )
    start = Barrier(2)

    def invoke(command: FreezeFacilityCommand) -> str:
        start.wait()
        try:
            service.freeze_facility(command)
        except SnapshotAlreadyFrozen:
            return "already-frozen"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(invoke, commands))

    assert sorted(outcomes) == ["already-frozen", "created"]
    with database_engine.connect() as connection:
        snapshot_count = connection.execute(
            select(func.count())
            .select_from(facility_snapshot)
            .where(facility_snapshot.c.facility_id == facility_id)
        ).scalar_one()
    assert snapshot_count == 1
