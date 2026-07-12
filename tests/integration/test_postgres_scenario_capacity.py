"""PostgreSQL acceptance gate for frozen, fenced M4A scenario capacity."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from test_m1b_postgres_pipeline import _freeze_snapshot, _pipeline_input
from test_postgres_hedge_liquidity import ACTOR_ID, _hedge_input

from canopyledger.api.app import create_postgres_app
from canopyledger.application.integrity import IntegrityService
from canopyledger.domain.money import Money
from canopyledger.hedge.postgres import (
    PostgresHedgeLiquidityInputStore,
    PostgresHedgeLiquidityRunner,
)
from canopyledger.initial_domain.postgres import PostgresM1BPipelineRunner
from canopyledger.integrity.bundles import BundleType
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    internal_risk_capacity_assessment,
    pipeline_stage_output,
)
from canopyledger.scenario.engine import IrcPolicy, ScenarioCapacityInput, ScenarioDefinition
from canopyledger.scenario.postgres import (
    PostgresScenarioCapacityInputStore,
    PostgresScenarioCapacityRunner,
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)


def _scenario_input() -> ScenarioCapacityInput:
    return ScenarioCapacityInput(
        assessment_id="scn_0198a000-0000-7000-8000-000000000001",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        market_bundle_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
        computation_bundle_digest="sha256:" + "e" * 64,
        scenario_version="coffee-scenarios-v1",
        prng_family="python-mt19937-v1",
        seed=41,
        path_count=500,
        time_steps=5,
        thread_count=1,
        confidence_level=Decimal("0.95"),
        quantization_scale=Decimal("0.01"),
        correlation=Decimal("0.35"),
        cbb=Money(Decimal("100000"), "EUR"),
        facility_commitment=Money(Decimal("120000"), "EUR"),
        outstanding_exposure=Money(Decimal("85000"), "EUR"),
        base_margin_call=Money(Decimal("15000"), "EUR"),
        available_liquidity=Money(Decimal("12000"), "EUR"),
        price_volatility=Decimal("0.12"),
        margin_volatility=Decimal("0.30"),
        scenarios=(
            ScenarioDefinition(
                "price-decline",
                "price_decline",
                Decimal("-0.20"),
                Decimal("0.05"),
                Decimal("1"),
                Decimal("0"),
            ),
            ScenarioDefinition(
                "rally-margin",
                "supply_rally",
                Decimal("0.10"),
                Decimal("0"),
                Decimal("2"),
                Decimal("0"),
            ),
        ),
        irc_policy=IrcPolicy(
            tail_loss_multiplier=Decimal("1.1"),
            liquidity_multiplier=Decimal("1"),
            counterparty_buffer=Decimal("3000"),
            climate_evidence_buffer=Decimal("1500"),
        ),
    )


def test_m4a_publishes_frozen_scenario_and_separate_irc_after_s5(
    database_engine: Engine,
    database_url: str,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    hedge_store = PostgresHedgeLiquidityInputStore(database_engine)
    scenario_store = PostgresScenarioCapacityInputStore(database_engine)
    hedge_draft = _hedge_input()
    scenario_draft = _scenario_input()
    hedge_reference = hedge_store.publish(hedge_draft, created_by=ACTOR_ID, created_at=NOW)
    scenario_reference = scenario_store.publish(scenario_draft, created_by=ACTOR_ID, created_at=NOW)

    snapshot_id, references = _freeze_snapshot(
        IntegrityService(
            integrity,
            clock=lambda: NOW,
            snapshot_input_validators={
                "hedge_liquidity_input": hedge_store.validate_snapshot_reference,
                "scenario_capacity_input": scenario_store.validate_snapshot_reference,
            },
        ),
        integrity,
        inputs=(
            SnapshotInputReference(
                resource_type="hedge_liquidity_input",
                resource_id=hedge_draft.assessment_id,
                digest=hedge_reference.digest,
            ),
            SnapshotInputReference(
                resource_type="scenario_capacity_input",
                resource_id=scenario_draft.assessment_id,
                digest=scenario_reference.digest,
            ),
        ),
        bundle_payloads={
            BundleType.MARKET: {
                "hedge_liquidity": hedge_draft.market_bundle_payload(),
                "scenario_capacity": scenario_draft.market_bundle_payload(),
            },
            BundleType.POLICY: {
                "hedge_liquidity": hedge_draft.policy_bundle_payload(),
                "scenario_capacity": scenario_draft.policy_bundle_payload(),
            },
            BundleType.COMPUTATION: {
                "hedge_liquidity": hedge_draft.computation_bundle_payload(),
                "scenario_capacity": scenario_draft.computation_bundle_payload(),
            },
        },
    )
    m1b = PostgresM1BPipelineRunner(database_engine, integrity, clock=lambda: NOW).publish(
        _pipeline_input(snapshot_id, references), worker_id="m1b-worker"
    )
    hedge = PostgresHedgeLiquidityRunner(
        database_engine, integrity, hedge_store, clock=lambda: NOW
    ).publish(snapshot_id, hedge_draft.assessment_id, worker_id="hedge-worker")
    value = replace(
        scenario_draft,
        snapshot_id=snapshot_id,
        cbb_output_digest=m1b.output_digests[-1],
        hedge_liquidity_output_digest=hedge.output_digest,
        market_bundle_digest=references[BundleType.MARKET].digest,
        policy_bundle_digest=references[BundleType.POLICY].digest,
        computation_bundle_digest=references[BundleType.COMPUTATION].digest,
    )

    published = PostgresScenarioCapacityRunner(
        database_engine, integrity, scenario_store, clock=lambda: NOW
    ).publish(value, worker_id="scenario-worker")

    assert published.output_digest.startswith("sha256:")
    assert Decimal(published.internal_risk_capacity["irc"]) <= Decimal(
        published.internal_risk_capacity["cbb"]
    )
    assert published.internal_risk_capacity["cbb"] == (
        f"{m1b.certificate.assessment.contractual_borrowing_base.amount:.2f}"
    )
    with database_engine.connect() as connection:
        stage_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.snapshot_id == snapshot_id)
        ).scalar_one()
        irc_count = connection.execute(
            select(func.count())
            .select_from(internal_risk_capacity_assessment)
            .where(internal_risk_capacity_assessment.c.snapshot_id == snapshot_id)
        ).scalar_one()
    assert stage_count == 6
    assert irc_count == 1
    replay = integrity.load_replay_package(snapshot_id, {"python": "3.12"})
    assert (
        len([item for item in replay.artifacts if item.resource_type == "pipeline_stage_output"])
        == 6
    )
    response = TestClient(create_postgres_app(database_url, clock=lambda: NOW)).get(
        f"/api/v1/snapshots/{snapshot_id}/irc",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["output_digest"] == published.output_digest
