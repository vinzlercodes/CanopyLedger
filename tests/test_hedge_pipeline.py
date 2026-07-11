"""Pure S5 hedge/liquidity stage-output tests."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from test_hedge_liquidity import _input

from canopyledger.domain.money import Money
from canopyledger.hedge.pipeline import build_hedge_liquidity_stage_output


def test_s5_stage_output_carries_frozen_input_and_s4_lineage() -> None:
    value = _input()

    output = build_hedge_liquidity_stage_output(
        value,
        stage_output_id="out_0198a000-0000-7000-8000-000000000001",
        started_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
        completed_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
    )

    payload = output.to_canonical_dict()
    assert payload["stage"] == "hedge_liquidity"
    assert payload["input_digests"] == [
        value.cbb_output_digest,
        value.input_digest,
        value.market_bundle_digest,
    ]
    assert payload["result"]["assessment_digest"].startswith("sha256:")
    assert payload["output_digest"].startswith("sha256:")


def test_frozen_business_input_digest_is_stable_across_publication_context() -> None:
    value = _input()
    changed_context = replace(
        value,
        snapshot_id="snp_0198a000-0000-7000-8000-000000000099",
        cbb_output_digest="sha256:" + "9" * 64,
    )

    assert changed_context.input_digest == value.input_digest


def test_frozen_input_uses_the_published_cbb_availability_not_working_placeholder() -> None:
    value = replace(
        _input(),
        available_cash=Money(Decimal("5000"), "EUR"),
        undrawn_contractual_availability=Money(Decimal("3000"), "EUR"),
        fx_rates_to_facility={"USD/EUR": Decimal("0.90")},
    )
    reconstructed = value.from_frozen_input(
        value.to_input_canonical_dict(),
        assessment_id=value.assessment_id,
        snapshot_id=value.snapshot_id,
        cbb_output_digest=value.cbb_output_digest,
        market_bundle_digest=value.market_bundle_digest,
        policy_bundle_digest=value.policy_bundle_digest,
        computation_bundle_digest=value.computation_bundle_digest,
        undrawn_contractual_availability=Money(Decimal("12345.67"), "EUR"),
    )

    assert reconstructed.undrawn_contractual_availability.amount == Decimal("12345.67")
