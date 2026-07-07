"""M1B initial-domain stage graph tests."""

from dataclasses import replace
from decimal import Decimal

from canopyledger.domain.money import Money
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
    run_initial_domain_pipeline,
)
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.market.snapshot import FxRate, MarketSnapshot, PriceObservation


def sample_market() -> MarketSnapshot:
    return MarketSnapshot(
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
    )


def sample_input() -> M1BPipelineInput:
    return M1BPipelineInput(
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        facility_id="fac_0198a000-0000-7000-8000-000000000001",
        certificate_id="cbb_0198a000-0000-7000-8000-000000000001",
        facility_limit=Money(Decimal("500000.00"), "EUR"),
        current_principal=Money(Decimal("20000.00"), "EUR"),
        lc_exposure=Money(Decimal("5000.00"), "EUR"),
        other_contractual_usage=Money(Decimal("10000.00"), "EUR"),
        market_snapshot=sample_market(),
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
        reserves=(
            ReserveInput("documentation", Money(Decimal("12485.62"), "EUR")),
        ),
        market_bundle_digest="sha256:" + "a" * 64,
        policy_bundle_digest="sha256:" + "b" * 64,
        computation_bundle_digest="sha256:" + "c" * 64,
    )


def test_initial_domain_pipeline_publishes_ordered_stage_outputs_and_certificate() -> None:
    result = run_initial_domain_pipeline(sample_input())

    assert [output.stage for output in result.stage_outputs] == [
        "market_normalization",
        "collateral_valuation",
        "eligibility_and_reserves",
        "contractual_borrowing_base",
    ]
    assert all(output.snapshot_id == sample_input().snapshot_id for output in result.stage_outputs)
    assert all(output.output_digest.startswith("sha256:") for output in result.stage_outputs)
    assert all(
        output.policy_bundle_digest == "sha256:" + "b" * 64 for output in result.stage_outputs
    )
    assert result.certificate.contractual_availability == Money(Decimal("104034.45"), "EUR")
    assert result.certificate.output_digest.startswith("sha256:")


def test_pipeline_normalizes_inventory_units_before_valuation() -> None:
    base = sample_input()
    metric_input = replace(
        base,
        inventory_lots=(
            replace(
                base.inventory_lots[0],
                quantity=Decimal("6.0"),
                quantity_unit="metric_tonne",
            ),
        ),
        receivables=(),
        reserves=(),
    )
    bag_input = replace(
        base,
        inventory_lots=(
            replace(
                base.inventory_lots[0],
                quantity=Decimal("100"),
                quantity_unit="bag_60kg",
            ),
        ),
        receivables=(),
        reserves=(),
    )

    metric = run_initial_domain_pipeline(metric_input)
    bag = run_initial_domain_pipeline(bag_input)

    bag_inventory = bag.stage_outputs[1].result["inventory"][0]
    assert bag_inventory["quantity"] == "6.00000000"
    assert bag_inventory["quantity_unit"] == "metric_tonne"
    assert bag.certificate.contractual_availability == metric.certificate.contractual_availability


def test_pipeline_does_not_fx_discount_same_currency_receivables() -> None:
    base = sample_input()
    same_currency = replace(
        base,
        inventory_lots=(),
        receivables=(
            replace(
                base.receivables[0],
                invoice_amount=Money(Decimal("100.00"), "EUR"),
                credit_note_amount=Money(Decimal("0.00"), "EUR"),
                fx_pair="EUR/USD",
                advance_rate=Decimal("0.80"),
            ),
        ),
        reserves=(),
    )

    result = run_initial_domain_pipeline(same_currency)

    receivable = result.stage_outputs[1].result["receivables"][0]
    assert receivable["facility_value"] == "100.00"
    assert receivable["advanced_value"] == "80.00"


def test_m1b_fixed_input_monotonic_properties() -> None:
    base = sample_input()
    base_result = run_initial_domain_pipeline(base).certificate

    with_more_reserve = replace(
        base,
        reserves=(*base.reserves, ReserveInput("extra", Money(Decimal("1000.00"), "EUR"))),
    )
    with_more_usage = replace(
        base,
        other_contractual_usage=Money(
            base.other_contractual_usage.amount + Decimal("1000.00"), "EUR"
        ),
    )
    with_lower_advance_rate = replace(
        base,
        inventory_lots=(
            replace(base.inventory_lots[0], advance_rate=Decimal("0.10")),
        ),
    )
    with_older_receivable = replace(
        base,
        receivables=(replace(base.receivables[0], age_days=91),),
    )

    reserve_result = run_initial_domain_pipeline(with_more_reserve).certificate
    usage_result = run_initial_domain_pipeline(with_more_usage).certificate
    advance_result = run_initial_domain_pipeline(with_lower_advance_rate).certificate
    older_result = run_initial_domain_pipeline(with_older_receivable).certificate

    assert (
        reserve_result.assessment.contractual_borrowing_base.amount
        <= base_result.assessment.contractual_borrowing_base.amount
    )
    assert (
        usage_result.contractual_availability.amount
        <= base_result.contractual_availability.amount
    )
    assert (
        advance_result.assessment.contractual_borrowing_base.amount
        <= base_result.assessment.contractual_borrowing_base.amount
    )
    assert (
        older_result.assessment.contractual_borrowing_base.amount
        <= base_result.assessment.contractual_borrowing_base.amount
    )
    assert older_result.contractual_availability.amount >= 0


def test_stage_output_digest_matches_its_canonical_payload() -> None:
    result = run_initial_domain_pipeline(sample_input())

    for output in result.stage_outputs:
        payload = output.to_canonical_dict()
        payload.pop("output_digest")
        assert output.output_digest == domain_digest(
            "pipeline_stage_output", 1, canonical_json_bytes(payload)
        )


def test_initial_domain_pipeline_stage_outputs_are_replay_stable() -> None:
    first = run_initial_domain_pipeline(sample_input())
    second = run_initial_domain_pipeline(sample_input())

    assert [output.to_canonical_dict() for output in first.stage_outputs] == [
        output.to_canonical_dict() for output in second.stage_outputs
    ]


def test_market_snapshot_digest_changes_when_observation_changes() -> None:
    original = sample_market()
    changed = MarketSnapshot(
        snapshot_id=original.snapshot_id,
        as_of=original.as_of,
        prices=(
            PriceObservation(
                symbol="KC",
                price=Decimal("5872.42"),
                unit="USD_PER_MT",
                observed_at="2026-06-21T16:55:00.000000Z",
                source="synthetic-fixture",
            ),
        ),
        fx_rates=original.fx_rates,
    )

    assert original.digest != changed.digest
