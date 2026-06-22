"""PostgreSQL leased-queue, inbox, and fenced-publication acceptance tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import Engine, func, insert, select

from canopyledger.application.integrity import (
    CreateFacilityCommand,
    FreezeFacilityCommand,
    InboxDigestConflict,
    IntegrityService,
    OutputSchemaRejected,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.pipeline import FencedPublication
from canopyledger.integrity.snapshot import BundleReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    audit_event,
    inbox_receipt,
    outbox_message,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_attempt,
    pipeline_stage_output,
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 6, 22, 9, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"
INPUT_DIGEST = f"sha256:{'4' * 64}"


def build_service(
    store: PostgresIntegrityStore,
    *,
    accept_output: bool = True,
) -> IntegrityService:
    return IntegrityService(
        store,
        clock=lambda: NOW,
        output_schema_validators={
            "test-stage-v1": lambda value: accept_output and value == {"status": "verified"}
        },
    )


def seed_stages(engine: Engine, count: int = 1) -> tuple[str, ...]:
    store = PostgresIntegrityStore(engine)
    service = build_service(store)
    facility = service.create_facility(
        CreateFacilityCommand(
            actor_id=ACTOR_ID,
            idempotency_key=new_resource_id("key"),
            legal_name="Pipeline Test Coffee BV",
            currency="EUR",
            facility_commitment="1000000.00",
            correlation_id=new_resource_id("cor"),
        )
    )
    facility_body = json.loads(facility.body)
    references: list[BundleReference] = []
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
            payload={"resource_id": resource_id},
            created_by=ACTOR_ID,
            created_at=NOW,
        )
        store.publish_bundle(bundle)
        references.append(bundle.reference)
    freeze = service.freeze_facility(
        FreezeFacilityCommand(
            actor_id=ACTOR_ID,
            facility_id=facility_body["id"],
            idempotency_key=new_resource_id("key"),
            if_match=facility.headers["ETag"],
            as_of=NOW,
            market_bundle=references[0],
            policy_bundle=references[1],
            legal_interpretation_bundle=references[2],
            computation_bundle=references[3],
            inputs=(),
            correlation_id=new_resource_id("cor"),
        )
    )
    snapshot_id = json.loads(freeze.body)["snapshot_id"]
    run_id = new_resource_id("run")
    stage_ids = tuple(new_resource_id("stg") for _ in range(count))
    with engine.begin() as connection:
        connection.execute(
            insert(pipeline_run).values(
                resource_id=run_id,
                snapshot_id=snapshot_id,
                run_key=run_id,
                input_digest=INPUT_DIGEST,
                created_at=NOW,
            )
        )
        for position, stage_id in enumerate(stage_ids):
            connection.execute(
                insert(pipeline_stage).values(
                    resource_id=stage_id,
                    pipeline_run_id=run_id,
                    stage_definition_id=f"test-stage-{position}",
                    status="PENDING",
                    input_digest=INPUT_DIGEST,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    return stage_ids


def test_concurrent_claims_skip_locked_and_claim_distinct_stages(
    database_engine: Engine,
) -> None:
    expected = set(seed_stages(database_engine, 2))
    service = build_service(PostgresIntegrityStore(database_engine))
    start = Barrier(2)

    def claim(worker: str) -> tuple[str, int]:
        start.wait()
        lease = service.claim_stage(
            worker_id=worker,
            now=NOW,
            lease_duration=timedelta(seconds=30),
            maximum_lease_lifetime=timedelta(minutes=5),
        )
        assert lease is not None
        return lease.stage_id, lease.epoch

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = tuple(executor.map(claim, ("worker-a", "worker-b")))
    assert {item[0] for item in claimed} == expected
    assert {item[1] for item in claimed} == {1}


def test_expired_reclaim_increments_epoch_and_fences_stale_worker(
    database_engine: Engine,
) -> None:
    (stage_id,) = seed_stages(database_engine)
    service = build_service(PostgresIntegrityStore(database_engine))
    first = service.claim_stage(
        worker_id="worker-a",
        now=NOW,
        lease_duration=timedelta(seconds=30),
        maximum_lease_lifetime=timedelta(minutes=5),
    )
    assert first is not None and first.stage_id == stage_id
    heartbeat = service.heartbeat(
        stage_id=stage_id,
        worker_id="worker-a",
        epoch=1,
        now=NOW + timedelta(seconds=20),
        lease_duration=timedelta(minutes=10),
    )
    assert heartbeat.lease_expires_at == heartbeat.maximum_lease_expires_at
    assert (
        service.claim_stage(
            worker_id="worker-b",
            now=NOW + timedelta(seconds=1),
            lease_duration=timedelta(seconds=30),
            maximum_lease_lifetime=timedelta(minutes=5),
        )
        is None
    )
    second = None
    for _ in range(20):
        candidate = service.claim_stage(
            worker_id="worker-b",
            now=NOW + timedelta(seconds=301),
            lease_duration=timedelta(seconds=30),
            maximum_lease_lifetime=timedelta(minutes=5),
        )
        if candidate is None or candidate.stage_id == stage_id:
            second = candidate
            break
    assert second is not None and second.stage_id == stage_id and second.epoch == 2
    with pytest.raises(FencedPublication):
        service.heartbeat(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=1,
            now=NOW + timedelta(seconds=302),
            lease_duration=timedelta(seconds=30),
        )
    with pytest.raises(FencedPublication):
        service.publish_stage(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=1,
            input_digest=INPUT_DIGEST,
            output_schema_version="test-stage-v1",
            output={"status": "verified"},
            now=NOW + timedelta(seconds=302),
        )


def test_publication_is_fenced_validated_and_atomic(database_engine: Engine) -> None:
    (stage_id,) = seed_stages(database_engine)
    service = build_service(PostgresIntegrityStore(database_engine))
    lease = service.claim_stage(
        worker_id="worker-a",
        now=NOW,
        lease_duration=timedelta(seconds=30),
        maximum_lease_lifetime=timedelta(minutes=5),
    )
    assert lease is not None
    with pytest.raises(FencedPublication, match="input digest"):
        service.publish_stage(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=lease.epoch,
            input_digest=f"sha256:{'5' * 64}",
            output_schema_version="test-stage-v1",
            output={"status": "verified"},
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(OutputSchemaRejected):
        service.publish_stage(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=lease.epoch,
            input_digest=INPUT_DIGEST,
            output_schema_version="unknown-v1",
            output={"status": "verified"},
            now=NOW + timedelta(seconds=1),
        )
    published = service.publish_stage(
        stage_id=stage_id,
        worker_id="worker-a",
        epoch=lease.epoch,
        input_digest=INPUT_DIGEST,
        output_schema_version="test-stage-v1",
        output={"status": "verified"},
        now=NOW + timedelta(seconds=1),
    )
    with database_engine.connect() as connection:
        output_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.pipeline_stage_id == stage_id)
        ).scalar_one()
        stage = (
            connection.execute(
                select(pipeline_stage).where(pipeline_stage.c.resource_id == stage_id)
            )
            .mappings()
            .one()
        )
        outbox_count = connection.execute(
            select(func.count())
            .select_from(outbox_message)
            .where(outbox_message.c.message_key == published.publication_key)
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count())
            .select_from(audit_event)
            .where(audit_event.c.resource_id == published.output_id)
        ).scalar_one()
    assert stage["status"] == "SUCCEEDED"
    assert output_count == 1
    assert (outbox_count, audit_count) == (1, 1)
    with pytest.raises(FencedPublication, match="RUNNING"):
        service.publish_stage(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=lease.epoch,
            input_digest=INPUT_DIGEST,
            output_schema_version="test-stage-v1",
            output={"status": "verified"},
            now=NOW + timedelta(seconds=2),
        )


def test_inbox_deduplicates_exact_redelivery_and_rejects_changed_digest(
    database_engine: Engine,
) -> None:
    service = build_service(PostgresIntegrityStore(database_engine))
    message_id = new_resource_id("msg")
    digest = f"sha256:{'6' * 64}"
    first = service.record_inbox(
        consumer="pipeline-worker",
        message_id=message_id,
        message_digest=digest,
        outcome=b'{"accepted":true}',
        now=NOW,
    )
    replay = service.record_inbox(
        consumer="pipeline-worker",
        message_id=message_id,
        message_digest=digest,
        outcome=b"ignored-redelivery-value",
        now=NOW + timedelta(seconds=1),
    )
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.outcome == first.outcome
    with pytest.raises(InboxDigestConflict):
        service.record_inbox(
            consumer="pipeline-worker",
            message_id=message_id,
            message_digest=f"sha256:{'7' * 64}",
            outcome=b"changed",
            now=NOW + timedelta(seconds=2),
        )
    with database_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(inbox_receipt)
            .where(inbox_receipt.c.message_id == message_id)
        ).scalar_one()
    assert count == 1


def test_publication_crash_rolls_back_output_stage_attempt_outbox_and_audit(
    database_engine: Engine,
) -> None:
    (stage_id,) = seed_stages(database_engine)
    normal_service = build_service(PostgresIntegrityStore(database_engine))
    lease = normal_service.claim_stage(
        worker_id="worker-a",
        now=NOW,
        lease_duration=timedelta(seconds=30),
        maximum_lease_lifetime=timedelta(minutes=5),
    )
    assert lease is not None

    def fail_before_commit() -> None:
        raise RuntimeError("injected publication crash")

    crashing_service = build_service(
        PostgresIntegrityStore(
            database_engine,
            before_serializable_commit=fail_before_commit,
        )
    )
    with pytest.raises(RuntimeError, match="publication crash"):
        crashing_service.publish_stage(
            stage_id=stage_id,
            worker_id="worker-a",
            epoch=lease.epoch,
            input_digest=INPUT_DIGEST,
            output_schema_version="test-stage-v1",
            output={"status": "verified"},
            now=NOW + timedelta(seconds=1),
        )

    with database_engine.connect() as connection:
        output_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.pipeline_stage_id == stage_id)
        ).scalar_one()
        stage = (
            connection.execute(
                select(pipeline_stage).where(pipeline_stage.c.resource_id == stage_id)
            )
            .mappings()
            .one()
        )
        attempt = (
            connection.execute(
                select(pipeline_stage_attempt).where(
                    pipeline_stage_attempt.c.resource_id == lease.attempt_id
                )
            )
            .mappings()
            .one()
        )
        downstream_count = connection.execute(
            select(func.count())
            .select_from(outbox_message)
            .where(
                outbox_message.c.topic == "pipeline.stage.published",
                outbox_message.c.message_key.like(f"{stage_id}:%"),
            )
        ).scalar_one()
    assert output_count == downstream_count == 0
    assert stage["status"] == "RUNNING"
    assert attempt["finished_at"] is None

    result = normal_service.publish_stage(
        stage_id=stage_id,
        worker_id="worker-a",
        epoch=lease.epoch,
        input_digest=INPUT_DIGEST,
        output_schema_version="test-stage-v1",
        output={"status": "verified"},
        now=NOW + timedelta(seconds=2),
    )
    assert result.output_digest.startswith("sha256:")
