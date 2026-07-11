"""PostgreSQL acceptance gate for frozen, fenced M3 S5 publication."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from test_m1b_postgres_pipeline import _freeze_snapshot, _pipeline_input

from canopyledger.api.app import create_postgres_app
from canopyledger.domain.money import Money
from canopyledger.domain.units import UnitConversionTable
from canopyledger.hedge.engine import (
    ExchangeContractSpecification,
    ExerciseStyle,
    FuturesPosition,
    HedgeLiquidityInput,
    PhysicalExposure,
)
from canopyledger.hedge.postgres import (
    HedgeLiquidityPersistenceError,
    PostgresHedgeLiquidityInputStore,
    PostgresHedgeLiquidityRunner,
)
from canopyledger.initial_domain.postgres import PostgresM1BPipelineRunner
from canopyledger.integrity.bundles import BundleType
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import pipeline_stage_output

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 11, 10, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def _hedge_input() -> HedgeLiquidityInput:
    specification = ExchangeContractSpecification(
        exchange="ICE",
        product_code="KC",
        contract_symbol="KC",
        contract_size=Decimal("37500"),
        contract_size_unit="lb",
        price_unit="US_CENTS_PER_LB",
        price_unit_factor=Decimal("0.01"),
        tick_size=Decimal("0.05"),
        currency="USD",
        exercise_style=ExerciseStyle.AMERICAN,
        settlement_rule="futures_delivery",
        calendar_version="ICE-2026-v1",
        delivery_months=("2026-09",),
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        source_document_digest="sha256:" + "a" * 64,
    )
    return HedgeLiquidityInput(
        assessment_id="hdl_0198a000-0000-7000-8000-000000000001",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        as_of=date(2026, 6, 21),
        cbb_output_digest="sha256:" + "c" * 64,
        market_bundle_digest="sha256:" + "d" * 64,
        policy_bundle_digest="sha256:" + "e" * 64,
        computation_bundle_digest="sha256:" + "f" * 64,
        exposure_unit="metric_tonne",
        unit_conversion_table=UnitConversionTable(
            version="coffee-units-v1",
            factors={("lb", "metric_tonne"): Decimal("0.00045359237")},
        ),
        physical_exposure=(PhysicalExposure("KC", "2026-09", Decimal("100"), "metric_tonne"),),
        purchase_commitments=(),
        sales_commitments=(),
        futures_positions=(
            FuturesPosition(
                contract_specification=specification,
                contracts=Decimal("-5"),
                delivery_month="2026-09",
                entry_futures_price=Decimal("180"),
                current_futures_price=Decimal("200"),
            ),
        ),
        option_positions=(),
        fx_exposure=Money(Decimal("1200"), "USD"),
        basis_exposure=Decimal("12"),
        available_cash=Money(Decimal("5000"), "EUR"),
        # The authoritative runner replaces this working-input placeholder with S4 CBB.
        undrawn_contractual_availability=Money(Decimal("3000"), "EUR"),
        one_day_futures_moves={"KC": Decimal("8")},
        multi_day_futures_moves={"KC": Decimal("25")},
        fx_rates_to_facility={"USD/EUR": Decimal("0.90")},
    )


def test_m3_publishes_only_a_frozen_input_after_s4(
    database_engine: Engine,
    database_url: str,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresHedgeLiquidityInputStore(database_engine)
    draft = _hedge_input()
    stored = input_store.publish(draft, created_by=ACTOR_ID, created_at=NOW)

    from canopyledger.application.integrity import IntegrityService

    snapshot_id, references = _freeze_snapshot(
        IntegrityService(
            integrity,
            clock=lambda: NOW,
            snapshot_input_validators={
                "hedge_liquidity_input": input_store.validate_snapshot_reference,
            },
        ),
        integrity,
        inputs=(
            SnapshotInputReference(
                resource_type="hedge_liquidity_input",
                resource_id=draft.assessment_id,
                digest=stored.digest,
            ),
        ),
        bundle_payloads={
            BundleType.MARKET: {"hedge_liquidity": draft.market_bundle_payload()},
            BundleType.POLICY: {"hedge_liquidity": draft.policy_bundle_payload()},
            BundleType.COMPUTATION: {"hedge_liquidity": draft.computation_bundle_payload()},
        },
    )
    m1b = PostgresM1BPipelineRunner(
        database_engine,
        integrity,
        clock=lambda: NOW,
    ).publish(_pipeline_input(snapshot_id, references), worker_id="m1b-worker")
    published = PostgresHedgeLiquidityRunner(
        database_engine,
        integrity,
        input_store,
        clock=lambda: NOW,
    ).publish(snapshot_id, draft.assessment_id, worker_id="hedge-worker")

    assert published.output_digest == published.stage_output.output_digest
    assert published.stage_output.result["assessment_digest"].startswith("sha256:")
    assert (
        published.stage_output.result["assessment"]["liquidity"]
        ["undrawn_contractual_availability"]
        == f"{m1b.certificate.contractual_availability.amount:.2f}"
    )
    with database_engine.connect() as connection:
        output_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.snapshot_id == snapshot_id)
        ).scalar_one()
    assert output_count == 5
    replay = integrity.load_replay_package(snapshot_id, {"python": "3.12"})
    assert (
        len([item for item in replay.artifacts if item.resource_type == "pipeline_stage_output"])
        == 5
    )
    stored_output = PostgresHedgeLiquidityRunner(
        database_engine,
        integrity,
        input_store,
        clock=lambda: NOW,
    ).load_published_output(snapshot_id)
    assert stored_output is not None
    assert (
        stored_output["result"]["assessment_digest"]
        == published.stage_output.result["assessment_digest"]
    )
    response = TestClient(
        create_postgres_app(database_url, clock=lambda: NOW)
    ).get(
        f"/api/v1/snapshots/{snapshot_id}/hedge-liquidity",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["output_digest"] == published.output_digest


def test_m3_rejects_input_not_pinned_to_the_snapshot(database_engine: Engine) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresHedgeLiquidityInputStore(database_engine)
    draft = _hedge_input()
    input_store.publish(draft, created_by=ACTOR_ID, created_at=NOW)

    from canopyledger.application.integrity import IntegrityService

    snapshot_id, references = _freeze_snapshot(
        IntegrityService(integrity, clock=lambda: NOW),
        integrity,
    )
    PostgresM1BPipelineRunner(
        database_engine,
        integrity,
        clock=lambda: NOW,
    ).publish(_pipeline_input(snapshot_id, references), worker_id="m1b-worker")
    with pytest.raises(HedgeLiquidityPersistenceError, match="does not pin"):
        PostgresHedgeLiquidityRunner(
            database_engine,
            integrity,
            input_store,
            clock=lambda: NOW,
        ).publish(snapshot_id, draft.assessment_id, worker_id="hedge-worker")


def test_m3_rejects_missing_m3_sections_in_pinned_bundles(database_engine: Engine) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresHedgeLiquidityInputStore(database_engine)
    draft = _hedge_input()
    stored = input_store.publish(draft, created_by=ACTOR_ID, created_at=NOW)

    from canopyledger.application.integrity import IntegrityService

    snapshot_id, references = _freeze_snapshot(
        IntegrityService(
            integrity,
            clock=lambda: NOW,
            snapshot_input_validators={
                "hedge_liquidity_input": input_store.validate_snapshot_reference,
            },
        ),
        integrity,
        inputs=(
            SnapshotInputReference(
                resource_type="hedge_liquidity_input",
                resource_id=draft.assessment_id,
                digest=stored.digest,
            ),
        ),
    )
    PostgresM1BPipelineRunner(
        database_engine,
        integrity,
        clock=lambda: NOW,
    ).publish(_pipeline_input(snapshot_id, references), worker_id="m1b-worker")

    with pytest.raises(HedgeLiquidityPersistenceError, match="does not contain"):
        PostgresHedgeLiquidityRunner(
            database_engine,
            integrity,
            input_store,
            clock=lambda: NOW,
        ).publish(snapshot_id, draft.assessment_id, worker_id="hedge-worker")


def test_freeze_rejects_unpublished_or_digest_mismatched_m3_input(
    database_engine: Engine,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresHedgeLiquidityInputStore(database_engine)
    draft = _hedge_input()
    input_store.publish(draft, created_by=ACTOR_ID, created_at=NOW)

    from canopyledger.application.integrity import IntegrityService

    with pytest.raises(HedgeLiquidityPersistenceError, match="digest-mismatched"):
        _freeze_snapshot(
            IntegrityService(
                integrity,
                clock=lambda: NOW,
                snapshot_input_validators={
                    "hedge_liquidity_input": input_store.validate_snapshot_reference,
                },
            ),
            integrity,
            inputs=(
                SnapshotInputReference(
                    resource_type="hedge_liquidity_input",
                    resource_id=draft.assessment_id,
                    digest="sha256:" + "0" * 64,
                ),
            ),
        )
