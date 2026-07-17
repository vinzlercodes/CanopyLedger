"""PostgreSQL acceptance for immutable M9 governed-agent runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from canopyledger.agents.core import (
    AgentRole,
    AgentRunner,
    DeterministicReplayPlanner,
    Principal,
    default_capability_registry,
)
from canopyledger.agents.postgres import PostgresAgentRunStore
from canopyledger.application.integrity import (
    CreateFacilityCommand,
    FreezeFacilityCommand,
    IntegrityService,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000009"


def test_agent_runs_are_append_only_idempotent_and_reload_after_restart(
    database_engine: Engine,
) -> None:
    facility_id, snapshot_id = _seed_snapshot(database_engine)
    store = PostgresAgentRunStore(database_engine)
    runner = AgentRunner(
        registry=default_capability_registry(),
        planner=DeterministicReplayPlanner(),
        store=store,
        clock=lambda: NOW,
        tools={
            "snapshot.read": lambda value: {
                "snapshot_id": value["snapshot_id"],
                "state": "FROZEN",
            }
        },
    )
    run_id = new_resource_id("agr")
    run = runner.run(
        run_id=run_id,
        principal=Principal(actor_id=ACTOR_ID, roles=("analyst",)),
        role=AgentRole.FACILITY_ORCHESTRATOR,
        facility_id=facility_id,
        snapshot_id=snapshot_id,
        goal="Review the frozen snapshot.",
    )

    reloaded = PostgresAgentRunStore(database_engine).get(run_id)
    assert reloaded == run
    assert store.save(run) == run
    assert store.list_for_snapshot(snapshot_id) == (run,)

    with pytest.raises(
        DBAPIError, match="immutable resource agent_run cannot be UPDATE"
    ), database_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE canopyledger.agent_run SET status = 'tampered' "
                "WHERE resource_id = :resource_id"
            ),
            {"resource_id": run_id},
        )


def _seed_snapshot(engine: Engine) -> tuple[str, str]:
    integrity = PostgresIntegrityStore(engine)
    service = IntegrityService(integrity, clock=lambda: NOW)
    created = service.create_facility(
        CreateFacilityCommand(
            actor_id=ACTOR_ID,
            idempotency_key=new_resource_id("key"),
            legal_name="M9 Agent Test Coffee BV",
            currency="EUR",
            facility_commitment="1000.00",
            correlation_id=new_resource_id("cor"),
        )
    )
    facility_id = json.loads(created.body)["id"]
    bundles = []
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
        integrity.publish_bundle(bundle)
        bundles.append(bundle.reference)
    market, policy, legal, computation = bundles
    frozen = service.freeze_facility(
        FreezeFacilityCommand(
            actor_id=ACTOR_ID,
            facility_id=facility_id,
            idempotency_key=new_resource_id("key"),
            if_match=created.headers["ETag"],
            as_of=NOW,
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
    )
    return facility_id, json.loads(frozen.body)["snapshot_id"]
