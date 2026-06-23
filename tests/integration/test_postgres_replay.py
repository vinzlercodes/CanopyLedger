"""PostgreSQL replay package and audit-evidence acceptance tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select, text

from canopyledger.application.integrity import (
    CreateFacilityCommand,
    FreezeFacilityCommand,
    IntegrityService,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.replay import ReplayStatus
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import audit_event

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 6, 22, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"
ENVIRONMENT = {"git_commit": "test", "python": "3.12", "timezone": "UTC"}


def seed_snapshot(engine: Engine) -> tuple[IntegrityService, str, str]:
    store = PostgresIntegrityStore(engine)
    service = IntegrityService(store, clock=lambda: NOW)
    created = service.create_facility(
        CreateFacilityCommand(
            ACTOR_ID,
            new_resource_id("key"),
            "Replay Test Coffee BV",
            "EUR",
            "1000.00",
            new_resource_id("cor"),
        )
    )
    facility_id = json.loads(created.body)["id"]
    references = []
    market_id = ""
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
        if bundle_type is BundleType.MARKET:
            market_id = resource_id
    frozen = service.freeze_facility(
        FreezeFacilityCommand(
            ACTOR_ID,
            facility_id,
            new_resource_id("key"),
            created.headers["ETag"],
            NOW,
            references[0],
            references[1],
            references[2],
            references[3],
            (
                SnapshotInputReference(
                    resource_type="approved_fact",
                    resource_id=new_resource_id("fct"),
                    digest=f"sha256:{'a' * 64}",
                ),
            ),
            new_resource_id("cor"),
        )
    )
    return service, json.loads(frozen.body)["snapshot_id"], market_id


def test_database_package_matches_and_appends_audit(database_engine: Engine) -> None:
    service, snapshot_id, _ = seed_snapshot(database_engine)
    result = service.verify_snapshot_replay(
        snapshot_id=snapshot_id,
        declared_environment=ENVIRONMENT,
        current_environment=ENVIRONMENT,
        actor_id=ACTOR_ID,
        correlation_id=new_resource_id("cor"),
    )
    assert result.level_a is ReplayStatus.MATCH
    assert result.level_b is ReplayStatus.MATCH
    assert len(result.artifacts) == 6
    with database_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(audit_event)
            .where(
                audit_event.c.action == "snapshot.replay.verify",
                audit_event.c.resource_id == snapshot_id,
            )
        ).scalar_one()
    assert count == 1


def test_privileged_snapshot_input_reference_corruption_is_detected(
    database_engine: Engine,
) -> None:
    service, snapshot_id, _ = seed_snapshot(database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE canopyledger.snapshot_input_reference "
                "DISABLE TRIGGER snapshot_input_reference_immutable"
            )
        )
        connection.execute(
            text(
                "UPDATE canopyledger.snapshot_input_reference SET digest = :digest "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {"digest": f"sha256:{'b' * 64}", "snapshot_id": snapshot_id},
        )
        connection.execute(
            text(
                "ALTER TABLE canopyledger.snapshot_input_reference "
                "ENABLE TRIGGER snapshot_input_reference_immutable"
            )
        )
    result = service.verify_snapshot_replay(
        snapshot_id=snapshot_id,
        declared_environment=ENVIRONMENT,
        current_environment=ENVIRONMENT,
        actor_id=ACTOR_ID,
        correlation_id=new_resource_id("cor"),
    )
    assert result.level_a is ReplayStatus.MISMATCH
    assert result.level_b is ReplayStatus.MISMATCH
    assert any(
        issue.code == "DIGEST_MISMATCH"
        and issue.resource_type == "facility_snapshot_reconstructed"
        for issue in result.issues
    )


def test_privileged_corruption_is_detected_and_mismatch_is_audited(
    database_engine: Engine,
) -> None:
    service, snapshot_id, market_id = seed_snapshot(database_engine)
    with database_engine.begin() as connection:
        connection.execute(text("ALTER TABLE canopyledger.bundle DISABLE TRIGGER bundle_immutable"))
        connection.execute(
            text(
                "UPDATE canopyledger.bundle SET canonical_payload = :payload "
                "WHERE resource_id = :resource_id"
            ),
            {"payload": b'{"corrupt":true}', "resource_id": market_id},
        )
        connection.execute(text("ALTER TABLE canopyledger.bundle ENABLE TRIGGER bundle_immutable"))
    result = service.verify_snapshot_replay(
        snapshot_id=snapshot_id,
        declared_environment=ENVIRONMENT,
        current_environment=ENVIRONMENT,
        actor_id=ACTOR_ID,
        correlation_id=new_resource_id("cor"),
    )
    assert result.level_a is ReplayStatus.MISMATCH
    assert result.level_b is ReplayStatus.MISMATCH
    assert "DIGEST_MISMATCH" in {issue.code for issue in result.issues}
    with database_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(audit_event)
            .where(
                audit_event.c.action == "snapshot.replay.verify",
                audit_event.c.resource_id == snapshot_id,
            )
        ).scalar_one()
    assert count == 1
