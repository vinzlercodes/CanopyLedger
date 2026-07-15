"""M4B governed workspace read projections."""

import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app
from canopyledger.domain.money import Money
from canopyledger.governance.core import DecisionContext, GovernanceService, RecommendationClass

ANALYST = {"Authorization": "Bearer analyst-demo-token"}
APPROVER = {"Authorization": "Bearer approver-demo-token"}
NOW = datetime(2026, 7, 11, tzinfo=UTC)
SNAPSHOT_ID = "snp_0198a000-0000-7000-8000-000000000801"


def _context(snapshot_id: str) -> DecisionContext:
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


def _app(
    governance: GovernanceService | None = None, *, include_climate: bool = True
):
    return create_app(
        clock=lambda: NOW,
        governance_service=governance or GovernanceService(clock=lambda: NOW),
        decision_context_loader=_context,
        collateral_output_loader=lambda _: {
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
                        },
                        {
                            "lot_id": "lot-2",
                            "input_quantity": "25",
                            "input_quantity_unit": "metric_tonne",
                            "quantity": "25",
                            "quantity_unit": "metric_tonne",
                            "unit_conversion_table_version": "m1b-v1",
                            "gross_market_value": {"amount": "50000.00", "currency": "USD"},
                            "net_recovery_value": {"amount": "45000.00", "currency": "USD"},
                            "advanced_value": {"amount": "30000.00", "currency": "USD"},
                        },
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
        },
        hedge_output_loader=lambda _: {
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
        },
        climate_output_loader=_climate_output if include_climate else None,
        scenario_output_loader=lambda _: {
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
        },
    )


def _approval_queue(governance: GovernanceService) -> None:
    recommendation = governance.create_recommendation(
        context=_context(SNAPSHOT_ID),
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


def test_decision_pack_keeps_cbb_and_irc_separate_with_frozen_lineage() -> None:
    response = TestClient(_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["contractual_borrowing_base"] == {"amount": "100000.00", "currency": "USD"}
    assert payload["internal_risk_capacity"] == {"amount": "90000.00", "currency": "USD"}
    assert payload["cbb_output_digest"] == "sha256:" + "a" * 64
    assert payload["hedge_liquidity"]["stage"] == "hedge_liquidity"
    assert payload["scenario"]["stage"] == "scenario_capacity"
    assert "MARGIN_STRESS" in payload["blockers"]
    assert payload["climate_traceability"]["eudr_evidence_state"] == "review_required"


def test_decision_pack_is_fenced_when_climate_evidence_is_not_published() -> None:
    response = TestClient(_app(include_climate=False)).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack", headers=ANALYST
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "STAGE_PUBLICATION_FENCED"


def test_decision_pack_exposes_pending_recommendation_before_human_decision() -> None:
    governance = GovernanceService(clock=lambda: NOW)
    _approval_queue(governance)

    response = TestClient(_app(governance)).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["final_decision"] is None
    assert (
        payload["recommendation"]["recommendation_id"]
        == "rec_0198a000-0000-7000-8000-000000000801"
    )
    assert payload["recommendation"]["recommended_exposure_cap"] == {
        "amount": "85000.00",
        "currency": "USD",
    }


def test_collateral_read_projection_is_typed_paginated_and_retains_stage_lineage() -> None:
    response = TestClient(_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/collateral?section=inventory&limit=1", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot_id"] == SNAPSHOT_ID
    assert payload["section"] == "inventory"
    assert payload["page"] == {"limit": 1, "next_cursor": "1", "total_count": 2}
    assert payload["inventory_items"] == [
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
    ]
    assert payload["lineage"]["collateral_valuation_output_digest"] == "sha256:" + "1" * 64
    assert payload["lineage"]["eligibility_output_digest"] == "sha256:" + "2" * 64
    assert payload["reason_codes"] == ["INSURANCE_PENDING", "MARGIN_STRESS"]


def test_collateral_read_projection_uses_stable_cursor_for_each_authoritative_section() -> None:
    response = TestClient(_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/collateral?section=inventory&cursor=1&limit=1",
        headers=ANALYST,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["lot_id"] for item in payload["inventory_items"]] == ["lot-2"]
    assert payload["page"]["next_cursor"] is None


def test_hedge_lab_projection_is_typed_and_only_presents_published_stage_values() -> None:
    response = TestClient(_app()).get(f"/api/v1/snapshots/{SNAPSHOT_ID}/hedge-lab", headers=ANALYST)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" not in payload
    assert payload["exposure"]["net_price_exposure"] == "71019.428"
    assert payload["liquidity"]["total_liquidity_available"] == {
        "amount": "25000.00",
        "currency": "USD",
    }
    assert payload["futures_positions"][0]["pnl"] == {"amount": "1200.00", "currency": "USD"}
    assert payload["option_positions"][0]["delta"] == "-0.47"
    assert payload["stage_output_id"] == "out_hedge"
    assert payload["output_digest"] == "sha256:" + "b" * 64


def test_scenario_lab_projection_keeps_stressed_cbb_and_uncapped_irc_distinct() -> None:
    response = TestClient(_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/scenario-lab", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "scenario" not in payload
    assert payload["monte_carlo"]["expected_shortfall"] == {"amount": "18000.00", "currency": "USD"}
    assert payload["deterministic_scenarios"][0]["stressed_cbb"] == {
        "amount": "75000.00",
        "currency": "USD",
    }
    assert payload["internal_risk_capacity"]["uncapped_irc"] == {
        "amount": "68500.00",
        "currency": "USD",
    }
    assert payload["internal_risk_capacity"]["irc"] == {"amount": "68500.00", "currency": "USD"}
    assert payload["worst_scenario_families"] == [
        {"family": "price", "loss": {"amount": "27000.00", "currency": "USD"}}
    ]


def _climate_output(_: str) -> dict[str, object]:
    return {
            "stage_output_id": "out_climate",
            "snapshot_id": SNAPSHOT_ID,
            "stage": "climate_eudr",
            "stage_version": "1.0.0",
            "input_digests": ["sha256:" + "e" * 64],
            "legal_interpretation_bundle_digest": "sha256:" + "l" * 64,
            "policy_bundle_digest": "sha256:" + "p" * 64,
            "computation_bundle_digest": "sha256:" + "c" * 64,
            "reason_codes": ["TRACEABILITY_MISSING_LINK"],
            "completed_at": NOW.isoformat(),
            "output_digest": "sha256:" + "o" * 64,
            "result": {
                "eudr_evidence_state": "review_required",
                "legal_interpretation": {
                    "bundle_version": "legal-eudr-v1",
                    "production_cutoff": "2020-12-31",
                    "country_risk_reference_version": "country-risk-2026-q3",
                    "disclaimer": (
                        "Evidence readiness is an operational state, not a legal compliance "
                        "conclusion."
                    )
                },
                "traceability": {"lots": [], "origin_concentration": []},
                "climate_indicators": [],
                "climate_scenarios": [],
                "financed_emissions": {
                    "attribution_factor": "0.250000",
                    "scope_1": "0.250000",
                    "scope_2": "0.250000",
                    "scope_3": None,
                    "total_available": "1.0",
                    "data_quality_score": 2,
                    "source_period": "2025",
                    "estimation_method": "reported",
                    "methodology_version": "pcaf-fixture-v1",
                    "restatement_lineage": None,
                    "missing_data_warnings": ["SCOPE_3_UNAVAILABLE"],
                },
            },
    }


def test_climate_traceability_projection_preserves_lineage_without_a_legal_claim() -> None:
    app = create_app(climate_output_loader=_climate_output)

    response = TestClient(app).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/climate-traceability", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["eudr_evidence_state"] == "review_required"
    assert payload["legal_interpretation_bundle_digest"] == "sha256:" + "l" * 64
    assert "compliant" not in str(payload).lower()


def test_evidence_queue_exposes_candidate_review_context_only() -> None:
    client = TestClient(_app())
    document = client.post(
        "/api/v1/evidence/documents",
        headers=ANALYST,
        json={
            "filename": "receipt.pdf",
            "content_type": "application/pdf",
            "content_base64": "cGRm",
        },
    ).json()
    candidate = client.post(
        "/api/v1/evidence/candidate-facts",
        headers=ANALYST,
        json={
            "fact_type": "warehouse_receipt",
            "subject_id": "lot-1",
            "period": "2026-07",
            "value": {"quantity": "50"},
            "document_version_id": document["document_version_id"],
            "document_byte_digest": document["byte_digest"],
            "page_region": "page 1",
            "extraction_method": "human",
            "extractor_version": "1",
            "raw_value": "50 bags",
            "normalized_value": "50",
        },
    ).json()

    response = client.get("/api/v1/evidence/review-queue", headers=ANALYST)

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["candidate_fact_id"] == candidate["candidate_fact_id"]
    assert item["approval_state"] == "candidate"
    assert item["document_byte_digest"] == document["byte_digest"]


def test_evidence_document_rendition_is_bounded_and_original_bytes_require_authorization() -> None:
    client = TestClient(_app())
    content = b"Warehouse receipt\nLot KC-01\nQuantity 50 bags"
    document = client.post(
        "/api/v1/evidence/documents",
        headers=ANALYST,
        json={
            "filename": "receipt.txt",
            "content_type": "text/plain",
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    ).json()

    rendition = client.get(
        f"/api/v1/evidence/documents/{document['document_version_id']}/rendition",
        headers=ANALYST,
    )
    assert rendition.status_code == 200, rendition.text
    assert rendition.json() == {
        "document_version_id": document["document_version_id"],
        "filename": "receipt.txt",
        "content_type": "text/plain",
        "byte_digest": document["byte_digest"],
        "preview_status": "available",
        "preview_text": content.decode("utf-8"),
        "truncated": False,
    }

    unauthenticated = client.get(
        f"/api/v1/evidence/documents/{document['document_version_id']}/download"
    )
    assert unauthenticated.status_code == 401
    download = client.get(
        f"/api/v1/evidence/documents/{document['document_version_id']}/download",
        headers=ANALYST,
    )
    assert download.status_code == 200
    assert download.content == content
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"] == 'attachment; filename="receipt.txt"'
    assert download.headers["x-content-type-options"] == "nosniff"


def test_evidence_review_marks_the_active_approved_fact_for_safe_supersession() -> None:
    client = TestClient(_app())
    document = client.post(
        "/api/v1/evidence/documents",
        headers=ANALYST,
        json={
            "filename": "receipt.pdf",
            "content_type": "application/pdf",
            "content_base64": "cGRm",
        },
    ).json()
    approved_candidate = client.post(
        "/api/v1/evidence/candidate-facts",
        headers=ANALYST,
        json={
            "fact_type": "warehouse_receipt",
            "subject_id": "lot-2",
            "period": "2026-07",
            "value": {"quantity": "50"},
            "document_version_id": document["document_version_id"],
            "document_byte_digest": document["byte_digest"],
            "page_region": "page 1",
            "extraction_method": "human",
            "extractor_version": "1",
            "raw_value": "50 bags",
            "normalized_value": "50",
        },
    ).json()
    client.post(
        f"/api/v1/evidence/candidate-facts/{approved_candidate['candidate_fact_id']}/approve",
        headers=ANALYST,
    )
    correction = client.post(
        "/api/v1/evidence/candidate-facts",
        headers=ANALYST,
        json={
            "fact_type": "warehouse_receipt",
            "subject_id": "lot-2",
            "period": "2026-07",
            "value": {"quantity": "55"},
            "document_version_id": document["document_version_id"],
            "document_byte_digest": document["byte_digest"],
            "page_region": "page 1",
            "extraction_method": "human_correction",
            "extractor_version": "1",
            "raw_value": "55 bags",
            "normalized_value": "55",
        },
    ).json()

    response = client.get(
        f"/api/v1/evidence/candidate-facts/{correction['candidate_fact_id']}/review",
        headers=ANALYST,
    )

    assert response.status_code == 200, response.text
    assert response.json()["approval_history"][0]["is_active"] is True


def test_approval_queue_is_approver_only_and_returns_expiry_and_separation_context() -> None:
    governance = GovernanceService(clock=lambda: NOW)
    _approval_queue(governance)
    client = TestClient(_app(governance))

    forbidden = client.get("/api/v1/approval-requests", headers=ANALYST)
    assert forbidden.status_code == 403

    response = client.get("/api/v1/approval-requests", headers=APPROVER)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["approval_request_id"] == "arq_0198a000-0000-7000-8000-000000000801"
    assert item["author_id"] == "act_0198a000-0000-7000-8000-000000000001"
    assert item["expired"] is False
    assert item["self_approval_prohibited"] is True


def test_governance_timeline_is_snapshot_scoped_and_approver_only() -> None:
    governance = GovernanceService(clock=lambda: NOW)
    _approval_queue(governance)
    request = governance.list_approval_requests()[0]
    governance.approve(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000804",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000804",
        approval_request_id=request.resource_id,
        approver_id="act_0198a000-0000-7000-8000-000000000002",
        reason="Independent approval",
    )
    client = TestClient(_app(governance))

    assert (
        client.get(
            f"/api/v1/snapshots/{SNAPSHOT_ID}/governance-timeline", headers=ANALYST
        ).status_code
        == 403
    )
    response = client.get(f"/api/v1/snapshots/{SNAPSHOT_ID}/governance-timeline", headers=APPROVER)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [event["action"] for event in payload["items"]] == [
        "recommendation.created",
        "approval_request.created",
        "approval.approve",
        "final_decision.approved",
    ]
    assert payload["items"][-1]["actor_id"] == "act_0198a000-0000-7000-8000-000000000002"
    assert payload["items"][-1]["digest"].startswith("sha256:")


def test_override_detail_retains_dual_control_and_original_decision_lineage() -> None:
    governance = GovernanceService(clock=lambda: NOW)
    _approval_queue(governance)
    request = governance.list_approval_requests()[0]
    decision = governance.approve(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000801",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000801",
        approval_request_id=request.resource_id,
        approver_id="act_0198a000-0000-7000-8000-000000000002",
        reason="Independent approval",
    )
    override = governance.create_override_request(
        override_id="ovr_0198a000-0000-7000-8000-000000000801",
        original_decision_id=decision.resource_id,
        requester_id="act_0198a000-0000-7000-8000-000000000003",
        proposed_exposure_cap=Money(Decimal("65000"), "USD"),
        reason="Margin protection",
        policy_basis="Temporary liquidity covenant",
        expires_at=NOW + timedelta(days=1),
        requires_dual_control=True,
    )

    response = TestClient(_app(governance)).get(
        f"/api/v1/override-requests/{override.resource_id}", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["original_decision_id"] == decision.resource_id
    assert payload["proposed_exposure_cap"] == {"amount": "65000.00", "currency": "USD"}
    assert payload["requires_dual_control"] is True
    assert payload["approval_count"] == 0


def test_override_queue_is_snapshot_scoped_and_approver_only() -> None:
    governance = GovernanceService(clock=lambda: NOW)
    _approval_queue(governance)
    request = governance.list_approval_requests()[0]
    decision = governance.approve(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000802",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000802",
        approval_request_id=request.resource_id,
        approver_id="act_0198a000-0000-7000-8000-000000000002",
        reason="Independent approval",
    )
    governance.create_override_request(
        override_id="ovr_0198a000-0000-7000-8000-000000000802",
        original_decision_id=decision.resource_id,
        requester_id="act_0198a000-0000-7000-8000-000000000003",
        proposed_exposure_cap=Money(Decimal("65000"), "USD"),
        reason="Margin protection",
        policy_basis="Temporary liquidity covenant",
        expires_at=NOW + timedelta(days=1),
        requires_dual_control=True,
    )
    client = TestClient(_app(governance))

    assert (
        client.get(
            f"/api/v1/snapshots/{SNAPSHOT_ID}/override-requests", headers=ANALYST
        ).status_code
        == 403
    )
    response = client.get(f"/api/v1/snapshots/{SNAPSHOT_ID}/override-requests", headers=APPROVER)

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["override_id"] == "ovr_0198a000-0000-7000-8000-000000000802"
