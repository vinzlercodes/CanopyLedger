"""M1B CLI and API demo surface tests."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app
from canopyledger.cli.cbb_demo import run


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer analyst-demo-token"}


def demo_payload() -> dict[str, object]:
    return {
        "certificate_id": "cbb_0198a000-0000-7000-8000-000000000001",
        "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
        "facility_id": "fac_0198a000-0000-7000-8000-000000000001",
        "facility_limit": {"amount": "300000.00", "currency": "EUR"},
        "contributions": [
            {
                "source_type": "inventory",
                "source_id": "lot_0198a000-0000-7000-8000-000000000001",
                "amount": {"amount": "250000.00", "currency": "EUR"},
            },
            {
                "source_type": "receivable",
                "source_id": "rec_0198a000-0000-7000-8000-000000000001",
                "amount": {"amount": "112485.62", "currency": "EUR"},
            },
        ],
        "reserves": [
            {
                "reserve_type": "documentation",
                "amount": {"amount": "12485.62", "currency": "EUR"},
            }
        ],
        "usage": {
            "current_principal": {"amount": "120000.00", "currency": "EUR"},
            "lc_exposure": {"amount": "25000.00", "currency": "EUR"},
            "other_contractual_usage": {"amount": "10000.00", "currency": "EUR"},
        },
        "reason_codes": ["RECEIVABLE_CREDIT_NOTE_APPLIED"],
    }


def pipeline_payload() -> dict[str, object]:
    return {
        "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
        "facility_id": "fac_0198a000-0000-7000-8000-000000000001",
        "certificate_id": "cbb_0198a000-0000-7000-8000-000000000001",
        "facility_limit": {"amount": "500000.00", "currency": "EUR"},
        "current_principal": {"amount": "20000.00", "currency": "EUR"},
        "lc_exposure": {"amount": "5000.00", "currency": "EUR"},
        "other_contractual_usage": {"amount": "10000.00", "currency": "EUR"},
        "market_snapshot": {
            "snapshot_id": "mkt_0198a000-0000-7000-8000-000000000001",
            "as_of": "2026-06-21T17:00:00.000000Z",
            "prices": [
                {
                    "symbol": "KC",
                    "price": "5871.42",
                    "unit": "USD_PER_MT",
                    "observed_at": "2026-06-21T16:55:00.000000Z",
                    "source": "synthetic-fixture",
                }
            ],
            "fx_rates": [
                {
                    "pair": "EUR/USD",
                    "rate": "0.918",
                    "observed_at": "2026-06-21T16:55:00.000000Z",
                    "source": "synthetic-fixture",
                }
            ],
        },
        "inventory_lots": [
            {
                "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
                "quantity": "18.4",
                "quantity_unit": "metric_tonne",
                "benchmark_symbol": "KC",
                "physical_differential_usd_per_mt": "185.00",
                "selling_cost_usd_per_mt": "142.00",
                "liquidation_cost": {"amount": "5200.00", "currency": "EUR"},
                "advance_rate": "0.65",
                "reason_codes": ["WAREHOUSE_RECEIPT_APPROVED"],
            }
        ],
        "receivables": [
            {
                "receivable_id": "rec_0198a000-0000-7000-8000-000000000001",
                "obligor_id": "obl_1",
                "invoice_amount": {"amount": "125000.00", "currency": "USD"},
                "credit_note_amount": {"amount": "2500.00", "currency": "USD"},
                "fx_pair": "EUR/USD",
                "age_days": 45,
                "advance_rate": "0.80",
                "max_age_days": 90,
                "delivery_evidence_approved": True,
            }
        ],
        "reserves": [
            {
                "reserve_type": "documentation",
                "amount": {"amount": "12485.62", "currency": "EUR"},
            }
        ],
        "market_bundle_digest": "sha256:" + "a" * 64,
        "policy_bundle_digest": "sha256:" + "b" * 64,
        "computation_bundle_digest": "sha256:" + "c" * 64,
    }


def test_api_demo_returns_deterministic_cbb_certificate() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/cbb-certificates/demo",
        headers=auth_headers(),
        json=demo_payload(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["contractual_borrowing_base"] == "300000.00"
    assert body["result"]["contractual_availability"] == "145000.00"
    assert body["output_digest"].startswith("sha256:")


def test_api_pipeline_demo_returns_stage_outputs_and_certificate() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/m1b/pipeline/demo",
        headers=auth_headers(),
        json=pipeline_payload(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [stage["stage"] for stage in body["stage_outputs"]] == [
        "market_normalization",
        "collateral_valuation",
        "eligibility_and_reserves",
        "contractual_borrowing_base",
    ]
    assert body["certificate"]["result"]["contractual_availability"] == "104034.45"
    assert body["stage_outputs"][-1]["result"]["contractual_availability"] == "104034.45"
    assert body["stage_outputs"][-1]["output_digest"].startswith("sha256:")
    assert body["certificate"]["output_digest"].startswith("sha256:")


def test_api_demo_openapi_response_is_typed() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/api/v1/cbb-certificates/demo"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CbbCertificateResponse"
    }


def test_cbb_demo_cli_writes_canonical_certificate_json(tmp_path: Path) -> None:
    input_path = tmp_path / "demo-input.json"
    output_path = tmp_path / "certificate.json"
    input_path.write_text(json.dumps(demo_payload()), encoding="utf-8")

    status = run([str(input_path), "--output", str(output_path)])

    assert status == 0
    body = json.loads(output_path.read_text(encoding="utf-8"))
    assert body["result"]["contractual_availability"] == "145000.00"
    assert body["output_digest"].startswith("sha256:")
