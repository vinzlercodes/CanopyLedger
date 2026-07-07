"""PostgreSQL persistence gate for M1B initial-domain pipeline publication."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select

from canopyledger.application.integrity import (
    CreateFacilityCommand,
    FreezeFacilityCommand,
    IntegrityService,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
)
from canopyledger.initial_domain.postgres import PostgresM1BPipelineRunner
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.snapshot import BundleReference
from canopyledger.market.snapshot import FxRate, MarketSnapshot, PriceObservation
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import pipeline_stage, pipeline_stage_output

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 6, 10, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def test_m1b_pipeline_publishes_four_stage_outputs_for_frozen_snapshot(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    service = IntegrityService(store, clock=lambda: NOW)
    snapshot_id, references = _freeze_snapshot(service, store)
    pipeline_input = _pipeline_input(snapshot_id, references)

    result = PostgresM1BPipelineRunner(
        database_engine,
        store,
        clock=lambda: NOW,
    ).publish(pipeline_input, worker_id="m1b-worker")

    assert result.run_id.startswith("run_")
    assert len(result.stage_output_ids) == 4
    with database_engine.connect() as connection:
        output_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.snapshot_id == snapshot_id)
        ).scalar_one()
        succeeded_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage)
            .where(
                pipeline_stage.c.pipeline_run_id == result.run_id,
                pipeline_stage.c.status == "SUCCEEDED",
            )
        ).scalar_one()
    replay = store.load_replay_package(snapshot_id, {"python": "3.12"})
    persisted_output_artifacts = [
        artifact
        for artifact in replay.artifacts
        if artifact.resource_type == "pipeline_stage_output"
    ]
    assert output_count == succeeded_count == 4
    assert len(persisted_output_artifacts) == 4
    assert result.certificate.output_digest.startswith("sha256:")


def _freeze_snapshot(
    service: IntegrityService,
    store: PostgresIntegrityStore,
) -> tuple[str, dict[BundleType, BundleReference]]:
    created = service.create_facility(
        CreateFacilityCommand(
            actor_id=ACTOR_ID,
            idempotency_key=new_resource_id("key"),
            legal_name="M1B Pipeline Coffee BV",
            currency="EUR",
            facility_commitment="500000.00",
            correlation_id=new_resource_id("cor"),
        )
    )
    facility_body = json.loads(created.body)
    references = {}
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
        references[bundle_type] = bundle.reference
    frozen = service.freeze_facility(
        FreezeFacilityCommand(
            actor_id=ACTOR_ID,
            facility_id=facility_body["id"],
            idempotency_key=new_resource_id("key"),
            if_match=created.headers["ETag"],
            as_of=NOW,
            market_bundle=references[BundleType.MARKET],
            policy_bundle=references[BundleType.POLICY],
            legal_interpretation_bundle=references[BundleType.LEGAL_INTERPRETATION],
            computation_bundle=references[BundleType.COMPUTATION],
            inputs=(),
            correlation_id=new_resource_id("cor"),
        )
    )
    return json.loads(frozen.body)["snapshot_id"], references


def _pipeline_input(
    snapshot_id: str,
    references: dict[BundleType, BundleReference],
) -> M1BPipelineInput:
    return M1BPipelineInput(
        snapshot_id=snapshot_id,
        facility_id="fac_0198a000-0000-7000-8000-000000000001",
        certificate_id="cbb_0198a000-0000-7000-8000-000000000001",
        facility_limit=Money(Decimal("500000.00"), "EUR"),
        current_principal=Money(Decimal("20000.00"), "EUR"),
        lc_exposure=Money(Decimal("5000.00"), "EUR"),
        other_contractual_usage=Money(Decimal("10000.00"), "EUR"),
        market_snapshot=MarketSnapshot(
            snapshot_id="mkt_0198a000-0000-7000-8000-000000000001",
            as_of="2026-06-21T17:00:00.000000Z",
            prices=(
                PriceObservation(
                    symbol="KC",
                    price=Decimal("5871.42"),
                    unit="USD_PER_MT",
                    observed_at="2026-06-21T16:55:00.000000Z",
                    source="synthetic-fixture",
                ),
            ),
            fx_rates=(
                FxRate(
                    pair="EUR/USD",
                    rate=Decimal("0.918"),
                    observed_at="2026-06-21T16:55:00.000000Z",
                    source="synthetic-fixture",
                ),
            ),
        ),
        inventory_lots=(
            InventoryLotInput(
                lot_id="lot_0198a000-0000-7000-8000-000000000001",
                quantity=Decimal("18.4"),
                quantity_unit="metric_tonne",
                benchmark_symbol="KC",
                physical_differential_usd_per_mt=Decimal("185.00"),
                selling_cost_usd_per_mt=Decimal("142.00"),
                liquidation_cost=Money(Decimal("5200.00"), "EUR"),
                advance_rate=Decimal("0.65"),
                reason_codes=("WAREHOUSE_RECEIPT_APPROVED",),
            ),
        ),
        receivables=(
            ReceivableInput(
                receivable_id="rec_0198a000-0000-7000-8000-000000000001",
                obligor_id="obl_1",
                invoice_amount=Money(Decimal("125000.00"), "USD"),
                credit_note_amount=Money(Decimal("2500.00"), "USD"),
                fx_pair="EUR/USD",
                age_days=45,
                advance_rate=Decimal("0.80"),
                max_age_days=90,
                delivery_evidence_approved=True,
            ),
        ),
        reserves=(ReserveInput("documentation", Money(Decimal("12485.62"), "EUR")),),
        market_bundle_digest=references[BundleType.MARKET].digest,
        policy_bundle_digest=references[BundleType.POLICY].digest,
        computation_bundle_digest=references[BundleType.COMPUTATION].digest,
    )
