"""Canonical M10 PostgreSQL/PostGIS local-demo seed.

Unlike :mod:`canopyledger.demo.workspace`, this module executes the governed
pipeline.  It creates only synthetic reference data, freezes its input
lineage, publishes the M1B/M3/M4A/M5/M6 outputs, records an independently
approved final decision, and writes the immutable report package consumed by
the live API and web application.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from canopyledger.application.evidence import EvidenceService
from canopyledger.application.integrity import (
    CreateFacilityCommand,
    FreezeFacilityCommand,
    IntegrityService,
)
from canopyledger.climate.engine import (
    ClimateEudrInput,
    ClimateIndicator,
    ClimateScenario,
    FinancedEmissionsInput,
)
from canopyledger.climate.eudr import (
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceNodeType,
    LegalInterpretationPolicy,
    TraceabilityLot,
)
from canopyledger.climate.geometry import GeographicPoint
from canopyledger.climate.postgres import (
    PostgresClimateEudrInputStore,
    PostgresClimateEudrRunner,
)
from canopyledger.credit.engine import CreditFeatureObservation, build_reference_bundle
from canopyledger.credit.postgres import (
    PostgresCreditEarlyWarningInputStore,
    PostgresCreditEarlyWarningRunner,
)
from canopyledger.domain.money import Money
from canopyledger.domain.units import UnitConversionTable
from canopyledger.governance.core import RecommendationClass
from canopyledger.governance.postgres import PostgresGovernanceService
from canopyledger.hedge.engine import (
    ExchangeContractSpecification,
    ExerciseStyle,
    FuturesPosition,
    HedgeLiquidityInput,
    PhysicalExposure,
)
from canopyledger.hedge.postgres import (
    PostgresHedgeLiquidityInputStore,
    PostgresHedgeLiquidityRunner,
)
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
)
from canopyledger.initial_domain.postgres import PostgresM1BPipelineRunner
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import BundleReference, SnapshotInputReference
from canopyledger.market.snapshot import FxRate, MarketSnapshot, PriceObservation
from canopyledger.persistence.postgres import PostgresEvidenceStore, PostgresIntegrityStore
from canopyledger.reporting.core import ReportCompileInput, ReportModelCompiler, ReportPackageKind
from canopyledger.reporting.postgres import PostgresReportService
from canopyledger.reporting.service import reference_renderer_manifest, reference_report_renderer
from canopyledger.scenario.engine import IrcPolicy, ScenarioCapacityInput, ScenarioDefinition
from canopyledger.scenario.postgres import (
    PostgresScenarioCapacityInputStore,
    PostgresScenarioCapacityRunner,
)

DEMO_NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
ANALYST_ID = "act_0198a000-0000-7000-8000-000000000001"
APPROVER_ID = "apr_0198a000-0000-7000-8000-000000000001"


@dataclass(frozen=True)
class SeededDemoWorkspace:
    """Stable identifiers and digests emitted by the canonical demo command."""

    facility_id: str
    snapshot_id: str
    decision_id: str
    report_id: str
    report_model_digest: str
    artifact_digests: dict[str, str]


class _DemoIds:
    """Use deterministic, collision-free resource IDs for reproducible demo artifacts."""

    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(lambda: 9000)

    def __call__(self, prefix: str) -> str:
        self._counts[prefix] += 1
        return f"{prefix}_0198a000-0000-7000-8000-{self._counts[prefix]:012d}"


def seed_demo_workspace(engine: Engine) -> SeededDemoWorkspace:
    """Seed one complete synthetic, immutable reportable workspace into an empty database.

    This deliberately fails if the database has not been migrated or already
    contains conflicting records. Use a fresh disposable database for every
    canonical walkthrough; immutable resources intentionally prevent a second
    pipeline execution from silently replacing the first package.
    """
    ids = _DemoIds()
    integrity_store = PostgresIntegrityStore(engine)
    hedge_store = PostgresHedgeLiquidityInputStore(engine)
    scenario_store = PostgresScenarioCapacityInputStore(engine)
    climate_store = PostgresClimateEudrInputStore(engine)
    credit_store = PostgresCreditEarlyWarningInputStore(engine)
    evidence = EvidenceService(
        store=PostgresEvidenceStore(engine), clock=lambda: DEMO_NOW, id_factory=ids
    )
    approved_facts = _seed_approved_evidence(evidence)
    climate_draft = _climate_input(approved_facts)
    hedge_draft = _hedge_input()
    scenario_draft = _scenario_input()
    credit_bundle = build_reference_bundle()

    hedge_reference = hedge_store.publish(hedge_draft, created_by=ANALYST_ID, created_at=DEMO_NOW)
    scenario_reference = scenario_store.publish(
        scenario_draft, created_by=ANALYST_ID, created_at=DEMO_NOW
    )
    climate_reference = climate_store.publish(
        climate_draft, created_by=ANALYST_ID, created_at=DEMO_NOW
    )
    credit_reference = credit_store.publish(
        resource_id="cei_0198a000-0000-7000-8000-000000009601",
        bundle=credit_bundle,
        observation=CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000009601",
            as_of=DEMO_NOW,
            observed_at=DEMO_NOW,
            values={
                "liquidity_ratio": Decimal("1.1"),
                "receivable_days": Decimal("58"),
                "margin_coverage_ratio": Decimal("1.0"),
                "payment_delay_days": Decimal("11"),
            },
        ),
        created_by=ANALYST_ID,
        created_at=DEMO_NOW,
    )
    service = IntegrityService(
        integrity_store,
        clock=lambda: DEMO_NOW,
        id_factory=ids,
        snapshot_input_validators={
            "hedge_liquidity_input": hedge_store.validate_snapshot_reference,
            "scenario_capacity_input": scenario_store.validate_snapshot_reference,
            "climate_eudr_input": climate_store.validate_snapshot_reference,
            "credit_early_warning_input": credit_store.validate_snapshot_reference,
        },
    )
    facility_id, snapshot_id, bundles = _freeze_snapshot(
        service,
        integrity_store,
        ids,
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
            SnapshotInputReference(
                resource_type="climate_eudr_input",
                resource_id=climate_draft.assessment_id,
                digest=climate_reference.digest,
            ),
            SnapshotInputReference(
                resource_type="credit_early_warning_input",
                resource_id=credit_reference.resource_id,
                digest=credit_reference.digest,
            ),
            *(
                SnapshotInputReference(
                    resource_type="approved_fact",
                    resource_id=item.fact_id,
                    digest=item.digest,
                )
                for item in approved_facts
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
                "climate_eudr": {
                    "evidence_freshness_days": climate_draft.legal_policy.evidence_freshness_days,
                    "country_risk_reference_version": (
                        climate_draft.legal_policy.country_risk_reference_version
                    ),
                },
            },
            BundleType.LEGAL_INTERPRETATION: {
                "climate_eudr": climate_draft.legal_policy.to_canonical_dict()
            },
            BundleType.COMPUTATION: {
                "hedge_liquidity": hedge_draft.computation_bundle_payload(),
                "scenario_capacity": scenario_draft.computation_bundle_payload(),
                "climate_eudr": {
                    "geometry_validation_version": "1.0.0",
                    "financed_emissions_methodology_version": (
                        climate_draft.financed_emissions.methodology_version
                    ),
                },
                "credit_early_warning": {"model_bundle_digest": credit_bundle.digest},
            },
        },
    )
    m1b = PostgresM1BPipelineRunner(
        engine, integrity_store, clock=lambda: DEMO_NOW, id_factory=ids
    ).publish(_pipeline_input(snapshot_id, facility_id, bundles), worker_id="demo-m1b-worker")
    hedge = PostgresHedgeLiquidityRunner(
        engine, integrity_store, hedge_store, clock=lambda: DEMO_NOW, id_factory=ids
    ).publish(snapshot_id, hedge_draft.assessment_id, worker_id="demo-hedge-worker")
    PostgresScenarioCapacityRunner(
        engine, integrity_store, scenario_store, clock=lambda: DEMO_NOW, id_factory=ids
    ).publish(
        replace(
            scenario_draft,
            snapshot_id=snapshot_id,
            cbb_output_digest=m1b.output_digests[-1],
            hedge_liquidity_output_digest=hedge.output_digest,
            market_bundle_digest=bundles[BundleType.MARKET].digest,
            policy_bundle_digest=bundles[BundleType.POLICY].digest,
            computation_bundle_digest=bundles[BundleType.COMPUTATION].digest,
        ),
        worker_id="demo-scenario-worker",
    )
    PostgresClimateEudrRunner(
        engine, integrity_store, climate_store, clock=lambda: DEMO_NOW, id_factory=ids
    ).publish(snapshot_id, climate_draft.assessment_id, worker_id="demo-climate-worker")
    PostgresCreditEarlyWarningRunner(
        engine, integrity_store, credit_store, clock=lambda: DEMO_NOW, id_factory=ids
    ).publish(snapshot_id, credit_reference.resource_id, worker_id="demo-credit-worker")

    governance = PostgresGovernanceService(engine, clock=lambda: DEMO_NOW)
    recommendation_id = "rec_0198a000-0000-7000-8000-000000009901"
    approval_request_id = "arq_0198a000-0000-7000-8000-000000009901"
    decision_id = "fdc_0198a000-0000-7000-8000-000000009901"
    governance.execute(
        lambda service: service.create_recommendation(
            context=governance.load_authoritative_context(snapshot_id),
            recommendation_id=recommendation_id,
            author_id=ANALYST_ID,
            requested_amount=Money(Decimal("15000.00"), "EUR"),
            recommendation_class=RecommendationClass.APPROVE_WITH_CONDITIONS,
            conditions=("Synthetic demo: retain approved warehouse evidence.",),
            reason_codes=("SYNTHETIC_DEMO",),
            expires_at=DEMO_NOW + timedelta(days=30),
        )
    )
    governance.execute(
        lambda service: service.create_approval_request(
            approval_request_id=approval_request_id,
            recommendation_id=recommendation_id,
            requested_by=ANALYST_ID,
            expires_at=DEMO_NOW + timedelta(days=30),
        )
    )
    decision = governance.execute(
        lambda service: service.approve(
            approval_action_id="apa_0198a000-0000-7000-8000-000000009901",
            final_decision_id=decision_id,
            approval_request_id=approval_request_id,
            approver_id=APPROVER_ID,
            reason="Synthetic independent approval for the canonical M10 demo package.",
        )
    )
    report_id = "rpt_0198a000-0000-7000-8000-000000009901"
    package = _generate_report(
        engine=engine,
        integrity_store=integrity_store,
        governance=governance,
        snapshot_id=snapshot_id,
        decision=decision,
        report_id=report_id,
    )
    return SeededDemoWorkspace(
        facility_id=facility_id,
        snapshot_id=snapshot_id,
        decision_id=decision_id,
        report_id=report_id,
        report_model_digest=package.report_model.digest,
        artifact_digests={artifact.format.value: artifact.digest for artifact in package.artifacts},
    )


def create_postgres_demo_app() -> Any:
    """Expose the seeded PostgreSQL service as an uvicorn factory.

    ``scripts/run_demo.py`` owns migration and seeding before it starts this
    factory.  Keeping the factory read-only avoids a web-server restart ever
    re-running the analytical pipeline or mutating the report package.
    """
    from canopyledger.api.app import create_postgres_app

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the canonical demo API")
    return create_postgres_app(database_url, clock=lambda: DEMO_NOW)


@dataclass(frozen=True)
class _ApprovedEvidence:
    fact_id: str
    digest: str
    document_id: str
    document_digest: str


def _seed_approved_evidence(evidence: EvidenceService) -> tuple[_ApprovedEvidence, ...]:
    records = []
    for node_type in EvidenceNodeType:
        document = evidence.upload_document(
            filename=f"synthetic-{node_type.value}.txt",
            content_type="text/plain",
            content=(f"Synthetic M10 reference evidence: {node_type.value}\\n").encode(),
            actor_id=ANALYST_ID,
        )
        candidate = evidence.create_candidate_fact(
            fact_type=f"eudr_{node_type.value.lower()}",
            subject_id="lot_0198a000-0000-7000-8000-000000009501",
            period="2026-07",
            value={"node_type": node_type.value, "fixture": "synthetic"},
            document_version_id=document.resource_id,
            document_byte_digest=document.byte_digest,
            page_region="line 1",
            extraction_method="human",
            extractor_version="m10-demo-v1",
            raw_value=node_type.value,
            normalized_value=node_type.value,
        )
        approved = evidence.approve_candidate_fact(candidate.fact_id, reviewer_id=APPROVER_ID)
        records.append(
            _ApprovedEvidence(
                fact_id=approved.fact_id,
                digest=evidence.active_approved_fact_digest(approved.fact_id),
                document_id=document.resource_id,
                document_digest=document.byte_digest,
            )
        )
    return tuple(records)


def _freeze_snapshot(
    service: IntegrityService,
    store: PostgresIntegrityStore,
    ids: _DemoIds,
    *,
    inputs: tuple[SnapshotInputReference, ...],
    bundle_payloads: dict[BundleType, dict[str, object]],
) -> tuple[str, str, dict[BundleType, BundleReference]]:
    created = service.create_facility(
        CreateFacilityCommand(
            actor_id=ANALYST_ID,
            idempotency_key=ids("key"),
            legal_name="Synthetic M10 Coffee Trading BV",
            currency="EUR",
            facility_commitment="500000.00",
            correlation_id=ids("cor"),
        )
    )
    facility = json.loads(created.body)
    references: dict[BundleType, BundleReference] = {}
    for bundle_type, prefix in (
        (BundleType.MARKET, "mkt"),
        (BundleType.POLICY, "pol"),
        (BundleType.LEGAL_INTERPRETATION, "leg"),
        (BundleType.COMPUTATION, "cmp"),
    ):
        resource_id = ids(prefix)
        bundle = VersionBundle.build(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version="1.0",
            payload={"resource_id": resource_id, **bundle_payloads.get(bundle_type, {})},
            created_by=ANALYST_ID,
            created_at=DEMO_NOW,
        )
        store.publish_bundle(bundle)
        references[bundle_type] = bundle.reference
    frozen = service.freeze_facility(
        FreezeFacilityCommand(
            actor_id=ANALYST_ID,
            facility_id=str(facility["id"]),
            idempotency_key=ids("key"),
            if_match=created.headers["ETag"],
            as_of=DEMO_NOW,
            market_bundle=references[BundleType.MARKET],
            policy_bundle=references[BundleType.POLICY],
            legal_interpretation_bundle=references[BundleType.LEGAL_INTERPRETATION],
            computation_bundle=references[BundleType.COMPUTATION],
            inputs=inputs,
            correlation_id=ids("cor"),
        )
    )
    snapshot = json.loads(frozen.body)
    return str(facility["id"]), str(snapshot["snapshot_id"]), references


def _pipeline_input(
    snapshot_id: str, facility_id: str, references: dict[BundleType, BundleReference]
) -> M1BPipelineInput:
    return M1BPipelineInput(
        snapshot_id=snapshot_id,
        facility_id=facility_id,
        certificate_id="cbb_0198a000-0000-7000-8000-000000009901",
        facility_limit=Money(Decimal("500000.00"), "EUR"),
        current_principal=Money(Decimal("20000.00"), "EUR"),
        lc_exposure=Money(Decimal("5000.00"), "EUR"),
        other_contractual_usage=Money(Decimal("10000.00"), "EUR"),
        market_snapshot=MarketSnapshot(
            snapshot_id="mkt_0198a000-0000-7000-8000-000000009901",
            as_of="2026-06-21T17:00:00.000000Z",
            prices=(
                PriceObservation(
                    symbol="KC",
                    price=Decimal("5871.42"),
                    unit="USD_PER_MT",
                    observed_at="2026-06-21T16:55:00.000000Z",
                    source="synthetic-reference",
                ),
            ),
            fx_rates=(
                FxRate(
                    pair="EUR/USD",
                    rate=Decimal("0.918"),
                    observed_at="2026-06-21T16:55:00.000000Z",
                    source="synthetic-reference",
                ),
            ),
        ),
        inventory_lots=(
            InventoryLotInput(
                lot_id="lot_0198a000-0000-7000-8000-000000009501",
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
                receivable_id="rec_0198a000-0000-7000-8000-000000009501",
                obligor_id="obl_demo",
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
        assessment_id="hdl_0198a000-0000-7000-8000-000000009501",
        snapshot_id="snp_0198a000-0000-7000-8000-000000009501",
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
        physical_exposure=(PhysicalExposure("KC", "2026-09", Decimal("110"), "metric_tonne"),),
        purchase_commitments=(),
        sales_commitments=(),
        futures_positions=(
            FuturesPosition(
                specification,
                Decimal("-5"),
                "2026-09",
                Decimal("180"),
                Decimal("200"),
            ),
        ),
        option_positions=(),
        fx_exposure=Money(Decimal("1200"), "USD"),
        basis_exposure=Decimal("12"),
        available_cash=Money(Decimal("5000"), "EUR"),
        undrawn_contractual_availability=Money(Decimal("3000"), "EUR"),
        one_day_futures_moves={"KC": Decimal("8")},
        multi_day_futures_moves={"KC": Decimal("25")},
        fx_rates_to_facility={"USD/EUR": Decimal("0.90")},
    )


def _scenario_input() -> ScenarioCapacityInput:
    return ScenarioCapacityInput(
        assessment_id="scn_0198a000-0000-7000-8000-000000009501",
        snapshot_id="snp_0198a000-0000-7000-8000-000000009501",
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        market_bundle_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
        computation_bundle_digest="sha256:" + "e" * 64,
        scenario_version="coffee-scenarios-v1",
        prng_family="python-mt19937-v1",
        seed=77,
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


def _climate_input(approved: tuple[_ApprovedEvidence, ...]) -> ClimateEudrInput:
    nodes = tuple(
        EvidenceGraphNode(
            node_id=node_type.value,
            node_type=node_type,
            approved_fact_id=fact.fact_id,
            approved_fact_digest=fact.digest,
            document_version_id=fact.document_id,
            document_byte_digest=fact.document_digest,
        )
        for node_type, fact in zip(EvidenceNodeType, approved, strict=True)
    )
    graph = EvidenceGraph(
        nodes=nodes,
        edges=tuple(
            EvidenceGraphEdge(nodes[index].node_id, nodes[index + 1].node_id)
            for index in range(len(nodes) - 1)
        ),
    )
    return ClimateEudrInput(
        assessment_id="clm_0198a000-0000-7000-8000-000000009501",
        snapshot_id="snp_0198a000-0000-7000-8000-000000009501",
        legal_interpretation_bundle_digest="sha256:" + "b" * 64,
        policy_bundle_digest="sha256:" + "c" * 64,
        computation_bundle_digest="sha256:" + "d" * 64,
        legal_policy=LegalInterpretationPolicy(
            bundle_version="legal-eudr-v1",
            production_cutoff=date(2020, 12, 31),
            evidence_freshness_days=90,
            country_risk_reference_version="country-risk-2026-q3",
        ),
        traceability_lots=(
            TraceabilityLot(
                lot_id="lot_0198a000-0000-7000-8000-000000009501",
                origin_country="BR",
                geometry=GeographicPoint(Decimal("-47.8825"), Decimal("-15.7942")),
                production_date=date(2020, 12, 31),
                country_risk_reference="country-risk-2026-q3",
                evidence_document_digest=approved[0].document_digest,
                evidence_recorded_at=datetime(2026, 6, 20, tzinfo=UTC),
                graph=graph,
            ),
        ),
        climate_indicators=(
            ClimateIndicator(
                "BR",
                "drought_index",
                Decimal("0.62"),
                "index",
                date(2026, 6, 30),
                "fixture-climate-provider",
                "sha256:" + "e" * 64,
            ),
        ),
        climate_scenarios=(
            ClimateScenario(
                "drought-stress",
                "physical_risk",
                Decimal("-0.12"),
                Decimal("-0.04"),
                7,
                Decimal("1250.00"),
                "USD",
            ),
        ),
        financed_emissions=FinancedEmissionsInput(
            borrower_scope_1=Decimal("120.0"),
            borrower_scope_2=Decimal("80.0"),
            borrower_scope_3=Decimal("300.0"),
            attribution_numerator=Decimal("2.5"),
            attribution_denominator=Decimal("10.0"),
            methodology_version="pcaf-fixture-v1",
            data_quality_score=2,
            source_period="2025",
            estimation_method="reported",
            restatement_lineage="emissions-restatement-2026-01",
        ),
    )


def _generate_report(
    *,
    engine: Engine,
    integrity_store: PostgresIntegrityStore,
    governance: PostgresGovernanceService,
    snapshot_id: str,
    decision: Any,
    report_id: str,
) -> Any:
    snapshot_response = integrity_store.get_snapshot_manifest(snapshot_id)
    if snapshot_response is None:
        raise RuntimeError("canonical demo snapshot was not persisted")
    snapshot = {
        **snapshot_response.manifest.model_dump(mode="json"),
        "digest": snapshot_response.manifest.digest,
    }
    context = governance.load_authoritative_context(snapshot_id)
    recommendation = governance.get_recommendation(decision.recommendation_id)
    hedge = PostgresHedgeLiquidityRunner(
        engine,
        integrity_store,
        PostgresHedgeLiquidityInputStore(engine),
        clock=lambda: DEMO_NOW,
    ).load_published_output(snapshot_id)
    scenario = PostgresScenarioCapacityRunner(
        engine,
        integrity_store,
        PostgresScenarioCapacityInputStore(engine),
        clock=lambda: DEMO_NOW,
    ).load_published_output(snapshot_id)
    climate = PostgresClimateEudrRunner(
        engine,
        integrity_store,
        PostgresClimateEudrInputStore(engine),
        clock=lambda: DEMO_NOW,
    ).load_published_output(snapshot_id)
    credit = PostgresCreditEarlyWarningRunner(
        engine,
        integrity_store,
        PostgresCreditEarlyWarningInputStore(engine),
        clock=lambda: DEMO_NOW,
    ).load_published_output(snapshot_id)
    collateral = governance.load_collateral_view(snapshot_id)
    if collateral is None or hedge is None or scenario is None or climate is None or credit is None:
        raise RuntimeError("canonical demo report sources were not fully published")
    renderer = reference_renderer_manifest()
    source = ReportCompileInput(
        report_id=report_id,
        package_kind=ReportPackageKind.CURRENT_OFFICIAL,
        decision={
            "resource_id": decision.resource_id,
            "snapshot_id": decision.snapshot_id,
            "status": decision.status.value,
            "superseded_by": decision.superseded_by,
            "digest": decision.digest,
        },
        snapshot=snapshot,
        decision_pack={
            "contractual_borrowing_base": _money(context.cbb),
            "contractual_availability": _money(context.contractual_availability),
            "internal_risk_capacity": _money(context.internal_risk_capacity),
            "recommendation": {
                "recommended_incremental_draw": _money(recommendation.recommended_incremental_draw)
            },
            "final_decision": {
                "resource_id": decision.resource_id,
                "status": decision.status.value,
                "digest": decision.digest,
            },
        },
        stage_outputs={
            "collateral": {
                "output_digest": domain_digest(
                    "report_source", 1, canonical_json_bytes(collateral)
                ),
                "result": collateral,
            },
            "hedge": hedge,
            "scenario": scenario,
            "climate": climate,
            "credit": credit,
        },
        template_version="committee-pack-v1",
        renderer_manifest={
            "renderer": str(renderer["renderer_version"]),
            "font_digest": str(renderer["font_digest"]),
            "locale": str(renderer["locale"]),
            "timezone": str(renderer["timezone"]),
        },
        created_at=DEMO_NOW,
    )
    return PostgresReportService(
        engine, compiler=ReportModelCompiler(), renderer=reference_report_renderer()
    ).generate(source)


def _money(value: Money) -> dict[str, str]:
    return {"amount": f"{value.quantized().amount:.2f}", "currency": value.currency}
