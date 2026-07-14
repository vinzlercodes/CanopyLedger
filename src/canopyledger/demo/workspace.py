"""Seeded FastAPI reference workspace for local UI verification.

This factory intentionally uses frozen, synthetic projections. It exists so a
developer can exercise the real FastAPI routes and Next.js client together;
it is not a calculation pipeline or production deployment factory.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI

from canopyledger.api.app import FacilityRecord, create_app
from canopyledger.application.evidence import EvidenceService, InMemoryEvidenceStore
from canopyledger.domain.money import Money
from canopyledger.governance.core import DecisionContext, GovernanceService, RecommendationClass
from canopyledger.integrity.snapshot import BundleReference, SnapshotManifest

FACILITY_ID = "fac_0198a000-0000-7000-8000-000000000801"
SNAPSHOT_ID = "snp_0198a000-0000-7000-8000-000000000801"
NOW = datetime(2026, 7, 11, tzinfo=UTC)


def create_demo_app() -> FastAPI:
    """Return an in-memory API with one immutable, synthetic workspace snapshot."""
    governance = GovernanceService(clock=lambda: NOW)
    evidence = _seed_evidence()
    _seed_approval_request(governance)
    return create_app(
        clock=lambda: NOW,
        evidence_service=evidence,
        governance_service=governance,
        decision_context_loader=_decision_context,
        collateral_output_loader=_collateral_output,
        hedge_output_loader=_hedge_output,
        scenario_output_loader=_scenario_output,
        initial_facilities=(
            FacilityRecord(
                resource_id=FACILITY_ID,
                legal_name="Fixture Coffee Trader",
                currency="USD",
                facility_commitment="120000.00",
                version=1,
            ),
        ),
        initial_snapshots=(_snapshot_manifest(),),
    )


def _seed_evidence() -> EvidenceService:
    evidence = EvidenceService(
        store=InMemoryEvidenceStore(),
        clock=lambda: NOW,
        id_factory=_fixture_resource_id,
    )
    document = evidence.upload_document(
        filename="warehouse-receipt.txt",
        content_type="text/plain",
        content=b"Warehouse receipt\\nLot KC-01\\nQuantity 50 metric tonnes",
        actor_id="act_0198a000-0000-7000-8000-000000000001",
    )
    evidence.create_candidate_fact(
        fact_type="warehouse_receipt",
        subject_id="lot-1",
        period="2026-07",
        value={"quantity": "50", "unit": "metric_tonne"},
        document_version_id=document.resource_id,
        document_byte_digest=document.byte_digest,
        page_region="text lines 1-3",
        extraction_method="human",
        extractor_version="fixture-v1",
        raw_value="50 metric tonnes",
        normalized_value="50",
    )
    return evidence


def _fixture_resource_id(prefix: str) -> str:
    return f"{prefix}_0198a000-0000-7000-8000-000000000801"


def _snapshot_manifest() -> SnapshotManifest:
    return SnapshotManifest(
        snapshot_id=SNAPSHOT_ID,
        facility_id=FACILITY_ID,
        facility_working_version=1,
        schema_version="1.0",
        as_of=NOW,
        market_bundle=_bundle("mkt", "a"),
        policy_bundle=_bundle("pol", "b"),
        legal_interpretation_bundle=_bundle("leg", "c"),
        computation_bundle=_bundle("cmp", "d"),
        inputs=(),
        created_by="act_0198a000-0000-7000-8000-000000000001",
        created_at=NOW,
    )


def _bundle(prefix: str, character: str) -> BundleReference:
    return BundleReference(
        resource_id=f"{prefix}_0198a000-0000-7000-8000-000000000801",
        digest="sha256:" + character * 64,
    )


def _decision_context(snapshot_id: str) -> DecisionContext:
    if snapshot_id != SNAPSHOT_ID:
        raise ValueError("seeded decision context is unavailable")
    return DecisionContext(
        snapshot_id=snapshot_id,
        cbb=Money(Decimal("100000"), "USD"),
        contractual_availability=Money(Decimal("75000"), "USD"),
        internal_risk_capacity=Money(Decimal("90000"), "USD"),
        liquidity_cap=Money(Decimal("95000"), "USD"),
        facility_commitment=Money(Decimal("120000"), "USD"),
        policy_caps=(Money(Decimal("85000"), "USD"),),
        outstanding_exposure=Money(Decimal("20000"), "USD"),
        approved_unfunded_exposure=Money(Decimal("5000"), "USD"),
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        irc_output_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
    )


def _collateral_output(snapshot_id: str) -> dict[str, object] | None:
    if snapshot_id != SNAPSHOT_ID:
        return None
    return {
        "collateral_valuation": {
            "stage_output_id": "out_collateral",
            "snapshot_id": SNAPSHOT_ID,
            "stage": "collateral_valuation",
            "stage_version": "m1b-1",
            "input_digests": ["sha256:" + "e" * 64],
            "policy_bundle_digest": "sha256:" + "d" * 64,
            "computation_bundle_digest": "sha256:" + "f" * 64,
            "reason_codes": ["MARGIN_STRESS"],
            "output_digest": "sha256:" + "1" * 64,
            "result": {
                "inventory": [
                    {
                        "lot_id": "lot-1",
                        "input_quantity": "50",
                        "input_quantity_unit": "metric_tonne",
                        "quantity": "50",
                        "quantity_unit": "metric_tonne",
                        "unit_conversion_table_version": "m1b-v1",
                        "gross_market_value": {"amount": "100000.00", "currency": "USD"},
                        "net_recovery_value": {"amount": "90000.00", "currency": "USD"},
                        "advanced_value": {"amount": "70000.00", "currency": "USD"},
                    }
                ],
                "receivables": [
                    {
                        "receivable_id": "recv-1",
                        "open_amount": {"amount": "15000.00", "currency": "USD"},
                        "facility_value": {"amount": "15000.00", "currency": "USD"},
                        "advanced_value": {"amount": "12000.00", "currency": "USD"},
                        "reason_codes": ["INSURANCE_PENDING"],
                    }
                ],
            },
        },
        "eligibility_and_reserves": {
            "stage_output_id": "out_eligibility",
            "snapshot_id": SNAPSHOT_ID,
            "stage": "eligibility_and_reserves",
            "stage_version": "m1b-1",
            "input_digests": ["sha256:" + "1" * 64],
            "policy_bundle_digest": "sha256:" + "d" * 64,
            "computation_bundle_digest": "sha256:" + "f" * 64,
            "reason_codes": ["INSURANCE_PENDING"],
            "output_digest": "sha256:" + "2" * 64,
            "result": {
                "contributions": [
                    {
                        "source_type": "inventory",
                        "source_id": "lot-1",
                        "amount": {"amount": "70000.00", "currency": "USD"},
                    },
                    {
                        "source_type": "receivable",
                        "source_id": "recv-1",
                        "amount": {"amount": "12000.00", "currency": "USD"},
                    },
                ],
                "reserves": [
                    {
                        "reserve_type": "insurance",
                        "amount": {"amount": "5000.00", "currency": "USD"},
                    }
                ],
            },
        },
    }


def _hedge_output(snapshot_id: str) -> dict[str, object] | None:
    if snapshot_id != SNAPSHOT_ID:
        return None
    return {
        "stage_output_id": "out_hedge",
        "snapshot_id": SNAPSHOT_ID,
        "stage": "hedge_liquidity",
        "stage_version": "s5-1",
        "output_digest": "sha256:" + "b" * 64,
        "reason_codes": ["MARGIN_STRESS"],
        "completed_at": NOW.isoformat(),
        "result": {
            "contract_specifications": [
                {
                    "exchange": "ICE",
                    "product_code": "KC",
                    "contract_symbol": "KC",
                    "contract_size": "37500",
                    "contract_size_unit": "pound",
                    "contract_size_in_exposure_unit": "17009.714",
                    "exposure_unit": "kilogram",
                    "price_unit": "usd_per_pound",
                    "price_unit_factor": "0.01",
                    "tick_size": "0.05",
                    "currency": "USD",
                    "exercise_style": "european",
                    "settlement_rule": "futures_delivery",
                    "calendar_version": "2026.1",
                    "delivery_months": ["2026-09"],
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-12-31",
                    "source_document_digest": "sha256:" + "e" * 64,
                }
            ],
            "futures_positions": [
                {
                    "product_code": "KC",
                    "delivery_month": "2026-09",
                    "contracts": "2",
                    "delta_exposure": "34019.428",
                    "pnl": "1200.00",
                }
            ],
            "option_positions": [
                {
                    "product_code": "KC",
                    "delivery_month": "2026-12",
                    "option_type": "put",
                    "contracts": "1",
                    "black76_reference_price": "2.100000",
                    "authoritative_price": "2.100000",
                    "delta_exposure": "-8000.000",
                    "value": "700.00",
                    "pnl": "-100.00",
                    "delta": "-0.47",
                    "gamma": "0.02",
                    "vega": "0.03",
                    "theta": "-0.01",
                    "rho": "0.01",
                }
            ],
            "exposure": {
                "exposure_unit": "kilogram",
                "gross_physical_exposure": "50000",
                "purchase_commitment_exposure": "10000",
                "sales_commitment_exposure": "5000",
                "net_physical_exposure": "45000",
                "futures_exposure": "34019.428",
                "option_delta_equivalent": "-8000.000",
                "net_price_exposure": "71019.428",
                "hedge_ratio": "0.58",
                "under_hedge_amount": "71019.428",
                "over_hedge_amount": "0",
                "fx_exposure": "500.00",
                "fx_exposure_currency": "USD",
                "fx_exposure_source_amount": "500.00",
                "fx_exposure_source_currency": "USD",
                "basis_exposure": "125.00",
                "delivery_month_mismatch": [
                    {
                        "delivery_month": "2026-09",
                        "physical_exposure": "50000",
                        "hedge_delta_exposure": "34019.428",
                        "net_price_exposure": "84019.428",
                    }
                ],
                "concentration_by_month": [
                    {"delivery_month": "2026-09", "physical_concentration": "1.000000"}
                ],
            },
            "valuation": {
                "futures_pnl": "1200.00",
                "option_value": "700.00",
                "option_pnl": "-100.00",
                "currency": "USD",
                "aggregate_greeks": {
                    "delta": "-0.47",
                    "gamma": "0.02",
                    "vega": "0.03",
                    "theta": "-0.01",
                    "rho": "0.01",
                },
            },
            "liquidity": {
                "currency": "USD",
                "available_cash": "10000.00",
                "undrawn_contractual_availability": "15000.00",
                "total_liquidity_available": "25000.00",
                "one_day_margin_stress": "5000.00",
                "multi_day_margin_stress": "10000.00",
                "timing_mismatch": "0.00",
                "margin_call_shortfall": "0.00",
                "liquidity_coverage_ratio": "2.50",
                "required_liquidity_reserve": "10000.00",
                "required_liquidity_coverage_ratio": "1.00",
            },
        },
    }


def _scenario_output(snapshot_id: str) -> dict[str, object] | None:
    if snapshot_id != SNAPSHOT_ID:
        return None
    return {
        "stage_output_id": "out_scenario",
        "snapshot_id": SNAPSHOT_ID,
        "stage": "scenario_capacity",
        "stage_version": "s6-1",
        "output_digest": "sha256:" + "c" * 64,
        "reason_codes": ["IRC_POLICY_CAP_BINDS"],
        "completed_at": NOW.isoformat(),
        "scenario": {
            "currency": "USD",
            "scenario_version": "2026.07",
            "monte_carlo": {
                "prng_family": "MT19937",
                "seed_derivation": "snapshot digest",
                "distribution_assumption": "normal",
                "regime_mixture": [{"name": "base", "weight": "1.000000"}],
                "seed": 7,
                "path_count": 1000,
                "time_steps": 10,
                "thread_count": 1,
                "confidence_level": "0.99",
                "correlation": "0.40",
                "correlation_matrix": [["1", "0.40"], ["0.40", "1"]],
                "value_at_risk": "15000.00",
                "expected_shortfall": "18000.00",
                "cbb_deficiency_probability": "0.10",
                "margin_liquidity_shortfall_probability": "0.05",
                "expected_collateral_shortfall": "3000.00",
                "expected_margin_liquidity_shortfall": "2000.00",
                "threshold_stability": {
                    "lower_confidence_level": "0.98",
                    "upper_confidence_level": "0.995",
                    "lower_value_at_risk": "13000.00",
                    "upper_value_at_risk": "17000.00",
                    "band_width": "4000.00",
                },
                "tail_contribution_by_factor": {
                    "collateral_price": "0.75",
                    "margin_liquidity": "0.25",
                },
                "hedge_effectiveness_distribution": {
                    "minimum": "0.4",
                    "median": "0.7",
                    "p95": "0.9",
                    "maximum": "1.0",
                },
            },
            "deterministic_scenarios": [
                {
                    "scenario_id": "stress-price",
                    "family": "price",
                    "stressed_cbb": "75000.00",
                    "cbb_deficiency": "0.00",
                    "margin_liquidity_shortfall": "2000.00",
                    "loss": "27000.00",
                }
            ],
            "worst_scenario_families": [{"family": "price", "loss": "27000.00"}],
            "internal_risk_capacity": {
                "risk_buffer": "10000.00",
                "tail_loss_buffer": "18000.00",
                "liquidity_buffer": "2000.00",
                "counterparty_buffer": "1000.00",
                "climate_evidence_buffer": "500.00",
                "uncapped_irc": "68500.00",
                "irc": "68500.00",
                "cbb": "100000.00",
                "facility_commitment": "120000.00",
            },
        },
        "internal_risk_capacity": {"amount": "68500.00", "currency": "USD"},
    }


def _seed_approval_request(governance: GovernanceService) -> None:
    recommendation = governance.create_recommendation(
        context=_decision_context(SNAPSHOT_ID),
        recommendation_id="rec_0198a000-0000-7000-8000-000000000801",
        author_id="act_0198a000-0000-7000-8000-000000000001",
        requested_amount=Money(Decimal("70000"), "USD"),
        recommendation_class=RecommendationClass.APPROVE_WITH_CONDITIONS,
        conditions=("VERIFY_INSURANCE",),
        reason_codes=("IRC_POLICY_CAP_BINDS",),
        expires_at=NOW + timedelta(days=1),
    )
    governance.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000801",
        recommendation_id=recommendation.resource_id,
        requested_by=recommendation.author_id,
        expires_at=NOW + timedelta(days=1),
    )
