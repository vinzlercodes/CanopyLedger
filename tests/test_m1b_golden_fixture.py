"""Golden fixture test for the M1B initial-domain pipeline."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from canopyledger.domain.money import Money
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
    run_initial_domain_pipeline,
)
from canopyledger.market.snapshot import FxRate, MarketSnapshot, PriceObservation

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_m1b_golden_fixture_produces_expected_certificate_and_stage_summary() -> None:
    input_payload = json.loads((FIXTURE_DIR / "m1b_golden_input.json").read_text())
    expected = json.loads((FIXTURE_DIR / "m1b_golden_expected.json").read_text())

    result = run_initial_domain_pipeline(_pipeline_input(input_payload))

    certificate = result.certificate.to_canonical_dict()
    assert certificate["result"]["gross_eligible_contribution"] == expected[
        "gross_eligible_contribution"
    ]
    assert certificate["result"]["total_reserves"] == expected["total_reserves"]
    assert certificate["result"]["contractual_borrowing_base"] == expected[
        "contractual_borrowing_base"
    ]
    assert certificate["result"]["contractual_availability"] == expected[
        "contractual_availability"
    ]
    assert [output.stage for output in result.stage_outputs] == expected["stages"]
    assert result.stage_outputs[1].result["receivables"][2]["reason_codes"] == [
        "RECEIVABLE_EXCESS_AGE"
    ]
    assert all(output.output_digest.startswith("sha256:") for output in result.stage_outputs)


def _pipeline_input(payload: dict[str, Any]) -> M1BPipelineInput:
    return M1BPipelineInput(
        snapshot_id=payload["snapshot_id"],
        facility_id=payload["facility_id"],
        certificate_id=payload["certificate_id"],
        facility_limit=_money(payload["facility_limit"]),
        current_principal=_money(payload["current_principal"]),
        lc_exposure=_money(payload["lc_exposure"]),
        other_contractual_usage=_money(payload["other_contractual_usage"]),
        market_snapshot=MarketSnapshot(
            snapshot_id=payload["market_snapshot"]["snapshot_id"],
            as_of=payload["market_snapshot"]["as_of"],
            prices=tuple(
                PriceObservation(
                    symbol=item["symbol"],
                    price=Decimal(item["price"]),
                    unit=item["unit"],
                    observed_at=item["observed_at"],
                    source=item["source"],
                )
                for item in payload["market_snapshot"]["prices"]
            ),
            fx_rates=tuple(
                FxRate(
                    pair=item["pair"],
                    rate=Decimal(item["rate"]),
                    observed_at=item["observed_at"],
                    source=item["source"],
                )
                for item in payload["market_snapshot"]["fx_rates"]
            ),
        ),
        inventory_lots=tuple(
            InventoryLotInput(
                lot_id=item["lot_id"],
                quantity=Decimal(item["quantity"]),
                quantity_unit=item["quantity_unit"],
                benchmark_symbol=item["benchmark_symbol"],
                physical_differential_usd_per_mt=Decimal(
                    item["physical_differential_usd_per_mt"]
                ),
                selling_cost_usd_per_mt=Decimal(item["selling_cost_usd_per_mt"]),
                liquidation_cost=_money(item["liquidation_cost"]),
                advance_rate=Decimal(item["advance_rate"]),
                reason_codes=tuple(item["reason_codes"]),
            )
            for item in payload["inventory_lots"]
        ),
        receivables=tuple(
            ReceivableInput(
                receivable_id=item["receivable_id"],
                obligor_id=item["obligor_id"],
                invoice_amount=_money(item["invoice_amount"]),
                credit_note_amount=_money(item["credit_note_amount"]),
                fx_pair=item["fx_pair"],
                age_days=item["age_days"],
                advance_rate=Decimal(item["advance_rate"]),
                max_age_days=item["max_age_days"],
                delivery_evidence_approved=item["delivery_evidence_approved"],
            )
            for item in payload["receivables"]
        ),
        reserves=tuple(
            ReserveInput(item["reserve_type"], _money(item["amount"]))
            for item in payload["reserves"]
        ),
        market_bundle_digest=payload["market_bundle_digest"],
        policy_bundle_digest=payload["policy_bundle_digest"],
        computation_bundle_digest=payload["computation_bundle_digest"],
    )


def _money(payload: dict[str, str]) -> Money:
    return Money(Decimal(payload["amount"]), payload["currency"])
