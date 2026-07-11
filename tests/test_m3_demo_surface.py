"""M3 typed hedge/liquidity demo surface tests."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from test_hedge_liquidity import _input

from canopyledger.api.app import create_app
from canopyledger.hedge.pipeline import build_hedge_liquidity_stage_output


def test_hedge_liquidity_demo_is_explicitly_non_authoritative_preview() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/hedge-liquidity/demo",
        headers={"Authorization": "Bearer analyst-demo-token"},
        json={
            "assessment_id": "hdl_0198a000-0000-7000-8000-000000000001",
            "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
            "as_of": "2026-06-21",
            "cbb_output_digest": "sha256:" + "a" * 64,
            "market_bundle_digest": "sha256:" + "b" * 64,
            "policy_bundle_digest": "sha256:" + "c" * 64,
            "computation_bundle_digest": "sha256:" + "d" * 64,
            "exposure_unit": "metric_tonne",
            "unit_conversion_factors": [
                {
                    "input_unit": "lb",
                    "output_unit": "metric_tonne",
                    "factor": "0.00045359237",
                }
            ],
            "physical_exposure": [
                {
                    "product_code": "KC",
                    "delivery_month": "2026-09",
                    "quantity": "100",
                    "quantity_unit": "metric_tonne",
                }
            ],
            "purchase_commitments": [],
            "sales_commitments": [],
            "futures_positions": [
                {
                    "contract_specification": {
                        "exchange": "ICE",
                        "product_code": "KC",
                        "contract_symbol": "KC",
                        "contract_size": "37500",
                        "contract_size_unit": "lb",
                        "price_unit": "US_CENTS_PER_LB",
                        "price_unit_factor": "0.01",
                        "tick_size": "0.05",
                        "currency": "USD",
                        "exercise_style": "american",
                        "settlement_rule": "futures_delivery",
                        "calendar_version": "ICE-2026-v1",
                        "delivery_months": ["2026-09"],
                        "effective_from": "2026-01-01",
                        "effective_to": "2026-12-31",
                        "source_document_digest": "sha256:" + "e" * 64,
                    },
                    "contracts": "-5",
                    "delivery_month": "2026-09",
                    "entry_futures_price": "180",
                    "current_futures_price": "200",
                }
            ],
            "option_positions": [],
            "fx_exposure": {"amount": "1200", "currency": "USD"},
            "basis_exposure": "12",
            "available_cash": {"amount": "5000", "currency": "USD"},
            "undrawn_contractual_availability": {"amount": "3000", "currency": "USD"},
            "one_day_futures_moves": {"KC": "8"},
            "multi_day_futures_moves": {"KC": "25"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authoritativeness"] == "preview"
    assert "output_digest" not in body
    assert "stage" not in body
    assert body["result"]["liquidity"]["margin_call_shortfall"] == "38875.00"
    assert body["reason_codes"] == [
        "HEDGE_REDUCES_PRICE_EXPOSURE",
        "MARGIN_LIQUIDITY_SHORTFALL",
    ]


def test_snapshot_hedge_liquidity_route_only_serves_published_stage_output() -> None:
    value = _input()
    output = build_hedge_liquidity_stage_output(
        value,
        stage_output_id="out_0198a000-0000-7000-8000-000000000001",
        started_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
        completed_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
    ).to_canonical_dict()
    app = create_app(
        hedge_output_loader=lambda snapshot_id: output if snapshot_id == value.snapshot_id else None
    )

    response = TestClient(app).get(
        f"/api/v1/snapshots/{value.snapshot_id}/hedge-liquidity",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "hedge_liquidity"
    assert response.json()["result"]["assessment_digest"].startswith("sha256:")
