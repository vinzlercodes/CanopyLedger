"""M3 hedge and liquidity acceptance tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from canopyledger.domain.money import Money
from canopyledger.domain.units import UnitConversionTable
from canopyledger.hedge.engine import (
    ExchangeContractSpecification,
    ExerciseStyle,
    FuturesPosition,
    HedgeLiquidityInput,
    OptionPosition,
    OptionType,
    PhysicalExposure,
    black76_price_and_greeks,
    crr_american_price,
    evaluate_hedge_and_liquidity,
)

UNIT_TABLE = UnitConversionTable(
    version="coffee-units-v1",
    factors={
        ("lb", "metric_tonne"): Decimal("0.00045359237"),
    },
)


def _spec(product_code: str) -> ExchangeContractSpecification:
    if product_code == "KC":
        return ExchangeContractSpecification(
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
            delivery_months=("2026-09", "2026-12"),
            effective_from="2026-01-01",
            effective_to="2026-12-31",
            source_document_digest="sha256:" + "a" * 64,
        )
    return ExchangeContractSpecification(
        exchange="ICE",
        product_code="AC",
        contract_symbol="AC",
        contract_size=Decimal("10"),
        contract_size_unit="metric_tonne",
        price_unit="USD_PER_METRIC_TONNE",
        price_unit_factor=Decimal("1"),
        tick_size=Decimal("0.01"),
        currency="USD",
        exercise_style=ExerciseStyle.AMERICAN,
        settlement_rule="futures_delivery",
        calendar_version="ICE-2026-v1",
        delivery_months=("2026-09",),
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        source_document_digest="sha256:" + "b" * 64,
    )


def _input() -> HedgeLiquidityInput:
    return HedgeLiquidityInput(
        assessment_id="hdl_0198a000-0000-7000-8000-000000000001",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        as_of=date(2026, 6, 21),
        cbb_output_digest="sha256:" + "c" * 64,
        market_bundle_digest="sha256:" + "d" * 64,
        policy_bundle_digest="sha256:" + "e" * 64,
        computation_bundle_digest="sha256:" + "f" * 64,
        exposure_unit="metric_tonne",
        unit_conversion_table=UNIT_TABLE,
        physical_exposure=(PhysicalExposure("KC", "2026-09", Decimal("100"), "metric_tonne"),),
        purchase_commitments=(),
        sales_commitments=(),
        futures_positions=(
            FuturesPosition(
                contract_specification=_spec("KC"),
                contracts=Decimal("-5"),
                delivery_month="2026-09",
                entry_futures_price=Decimal("180"),
                current_futures_price=Decimal("200"),
            ),
        ),
        option_positions=(),
        fx_exposure=Money(Decimal("1200"), "USD"),
        basis_exposure=Decimal("12"),
        available_cash=Money(Decimal("5000"), "USD"),
        undrawn_contractual_availability=Money(Decimal("3000"), "USD"),
        one_day_futures_moves={"KC": Decimal("8")},
        multi_day_futures_moves={"KC": Decimal("25")},
    )


def test_kc_and_ac_are_distinct_products_with_explicit_unit_normalization() -> None:
    assessment = evaluate_hedge_and_liquidity(_input())

    kc = assessment.result["contract_specifications"][0]
    assert kc["product_code"] == "KC"
    assert kc["contract_size_in_exposure_unit"] == "17.00971388"
    assert _spec("KC").product_code != _spec("AC").product_code
    assert _spec("KC").contract_size_unit != _spec("AC").contract_size_unit


def test_futures_pnl_exposure_hedge_ratio_and_margin_liquidity_are_explained() -> None:
    assessment = evaluate_hedge_and_liquidity(_input())

    assert assessment.result["futures_positions"][0]["pnl"] == "-37500.00"
    assert assessment.result["exposure"]["gross_physical_exposure"] == "100.00000000"
    assert assessment.result["exposure"]["futures_exposure"] == "-85.04856940"
    assert assessment.result["exposure"]["hedge_ratio"] == "0.85048569"
    assert assessment.result["exposure"]["concentration_by_month"] == [
        {"delivery_month": "2026-09", "physical_concentration": "1.00000000"}
    ]
    assert assessment.result["liquidity"]["one_day_margin_stress"] == "15000.00"
    assert assessment.result["liquidity"]["multi_day_margin_stress"] == "46875.00"
    assert assessment.result["liquidity"]["margin_call_shortfall"] == "38875.00"
    assert assessment.result["liquidity"]["liquidity_coverage_ratio"] == "0.17066667"
    assert "HEDGE_REDUCES_PRICE_EXPOSURE" in assessment.reason_codes
    assert "MARGIN_LIQUIDITY_SHORTFALL" in assessment.reason_codes


def test_black76_put_call_parity_and_greeks_match_reference_values() -> None:
    call = black76_price_and_greeks(
        option_type=OptionType.CALL,
        futures_price=Decimal("100"),
        strike=Decimal("100"),
        volatility=Decimal("0.20"),
        risk_free_rate=Decimal("0.05"),
        time_to_expiry=Decimal("1"),
    )
    put = black76_price_and_greeks(
        option_type=OptionType.PUT,
        futures_price=Decimal("100"),
        strike=Decimal("100"),
        volatility=Decimal("0.20"),
        risk_free_rate=Decimal("0.05"),
        time_to_expiry=Decimal("1"),
    )

    assert call.price == pytest.approx(Decimal("7.577082"), abs=Decimal("0.00001"))
    assert call.delta == pytest.approx(Decimal("0.513500"), abs=Decimal("0.00001"))
    assert call.gamma == pytest.approx(Decimal("0.018880"), abs=Decimal("0.000001"))
    assert call.vega == pytest.approx(Decimal("37.759294"), abs=Decimal("0.00001"))
    assert call.theta == pytest.approx(Decimal("-3.397075"), abs=Decimal("0.00001"))
    assert call.rho == pytest.approx(Decimal("-7.577082"), abs=Decimal("0.00001"))
    assert call.price - put.price == pytest.approx(Decimal("0"), abs=Decimal("0.00001"))
    assert call.delta - put.delta == pytest.approx(Decimal("0.951229"), abs=Decimal("0.00001"))


def test_crr_american_respects_european_lower_bound_converges_and_supports_early_exercise() -> None:
    european = black76_price_and_greeks(
        option_type=OptionType.PUT,
        futures_price=Decimal("60"),
        strike=Decimal("100"),
        volatility=Decimal("0.20"),
        risk_free_rate=Decimal("0.05"),
        time_to_expiry=Decimal("1"),
    ).price
    american_200 = crr_american_price(
        option_type=OptionType.PUT,
        futures_price=Decimal("60"),
        strike=Decimal("100"),
        volatility=Decimal("0.20"),
        risk_free_rate=Decimal("0.05"),
        time_to_expiry=Decimal("1"),
        steps=200,
    )
    american_400 = crr_american_price(
        option_type=OptionType.PUT,
        futures_price=Decimal("60"),
        strike=Decimal("100"),
        volatility=Decimal("0.20"),
        risk_free_rate=Decimal("0.05"),
        time_to_expiry=Decimal("1"),
        steps=400,
    )

    assert american_200 >= european
    assert american_200 > european
    assert abs(american_400 - american_200) < Decimal("0.03")


def test_option_edges_are_finite_at_expiry_zero_volatility_and_near_zero_rate() -> None:
    expiry = black76_price_and_greeks(
        option_type=OptionType.CALL,
        futures_price=Decimal("105"),
        strike=Decimal("100"),
        volatility=Decimal("0"),
        risk_free_rate=Decimal("0"),
        time_to_expiry=Decimal("0"),
    )
    zero_vol_american = crr_american_price(
        option_type=OptionType.PUT,
        futures_price=Decimal("95"),
        strike=Decimal("100"),
        volatility=Decimal("0"),
        risk_free_rate=Decimal("0.000000001"),
        time_to_expiry=Decimal("0.01"),
        steps=10,
    )

    assert expiry.price == Decimal("5")
    assert expiry.delta == Decimal("1")
    assert zero_vol_american == Decimal("5")


def test_deep_moneyness_and_low_volatility_remain_stable() -> None:
    deep_otm_call = black76_price_and_greeks(
        option_type=OptionType.CALL,
        futures_price=Decimal("50"),
        strike=Decimal("150"),
        volatility=Decimal("0.15"),
        risk_free_rate=Decimal("0.000000001"),
        time_to_expiry=Decimal("1"),
    )
    low_vol_put = black76_price_and_greeks(
        option_type=OptionType.PUT,
        futures_price=Decimal("99"),
        strike=Decimal("100"),
        volatility=Decimal("0.0001"),
        risk_free_rate=Decimal("0"),
        time_to_expiry=Decimal("0.25"),
    )

    assert Decimal("0") <= deep_otm_call.price < Decimal("0.000001")
    assert low_vol_put.price == pytest.approx(Decimal("1"), abs=Decimal("0.00001"))


def test_option_assessment_keeps_black76_reference_and_american_authoritative_value() -> None:
    value = replace(
        _input(),
        option_positions=(
            OptionPosition(
                contract_specification=_spec("KC"),
                contracts=Decimal("2"),
                delivery_month="2026-12",
                option_type=OptionType.PUT,
                strike=Decimal("220"),
                futures_price=Decimal("200"),
                volatility=Decimal("0.25"),
                risk_free_rate=Decimal("0.03"),
                time_to_expiry=Decimal("0.5"),
                lattice_steps=200,
                entry_option_price=Decimal("24"),
            ),
        ),
    )

    assessment = evaluate_hedge_and_liquidity(value)
    option = assessment.result["option_positions"][0]

    assert Decimal(option["authoritative_price"]) >= Decimal(option["black76_reference_price"])
    assert option["value"] != "0.00"
    assert assessment.result["exposure"]["option_delta_equivalent"] != "0.00000000"


def test_assessment_is_replay_stable_and_rejects_unknown_contract_for_margin_stress() -> None:
    first = evaluate_hedge_and_liquidity(_input())
    second = evaluate_hedge_and_liquidity(_input())

    assert first.output_digest == second.output_digest
    invalid = _input()
    object.__setattr__(invalid, "one_day_futures_moves", {"AC": Decimal("8")})
    with pytest.raises(ValueError, match="unknown futures move product"):
        evaluate_hedge_and_liquidity(invalid)


def test_cross_currency_contract_requires_a_pinned_conversion_before_liquidity_is_reported() -> (
    None
):
    cross_currency = replace(
        _input(),
        available_cash=Money(Decimal("5000"), "EUR"),
        undrawn_contractual_availability=Money(Decimal("3000"), "EUR"),
    )

    with pytest.raises(ValueError, match="contract currency requires a pinned FX conversion"):
        evaluate_hedge_and_liquidity(cross_currency)

    converted = replace(cross_currency, fx_rates_to_facility={"USD/EUR": Decimal("0.90")})
    assessment = evaluate_hedge_and_liquidity(converted)
    assert assessment.result["futures_positions"][0]["pnl"] == "-33750.00"
    assert assessment.result["exposure"]["fx_exposure"] == "1080.00"


def test_rejects_ineffective_contract_invalid_delivery_and_invalid_tick() -> None:
    ineffective = replace(_input(), as_of=date(2027, 1, 1))
    with pytest.raises(ValueError, match="not effective"):
        evaluate_hedge_and_liquidity(ineffective)

    invalid_delivery = replace(
        _input(),
        futures_positions=(replace(_input().futures_positions[0], delivery_month="2027-01"),),
    )
    with pytest.raises(ValueError, match="delivery month"):
        evaluate_hedge_and_liquidity(invalid_delivery)

    invalid_tick = replace(
        _input(),
        futures_positions=(
            replace(_input().futures_positions[0], current_futures_price=Decimal("200.01")),
        ),
    )
    with pytest.raises(ValueError, match="tick size"):
        evaluate_hedge_and_liquidity(invalid_tick)

    invalid_option_strike = replace(
        _input(),
        option_positions=(
            OptionPosition(
                contract_specification=_spec("KC"),
                contracts=Decimal("1"),
                delivery_month="2026-09",
                option_type=OptionType.CALL,
                strike=Decimal("200.01"),
                futures_price=Decimal("200"),
                volatility=Decimal("0.2"),
                risk_free_rate=Decimal("0.01"),
                time_to_expiry=Decimal("0.5"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="tick size"):
        evaluate_hedge_and_liquidity(invalid_option_strike)


def test_exchange_specification_requires_supported_settlement_calendar_and_digest() -> None:
    with pytest.raises(ValueError, match="settlement rule"):
        replace(_spec("KC"), settlement_rule="unknown")
    with pytest.raises(ValueError, match="metadata is required"):
        replace(_spec("KC"), calendar_version="")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(_spec("KC"), source_document_digest="sha256:not-a-digest")


def test_zero_futures_price_has_a_deterministic_option_limit() -> None:
    call = black76_price_and_greeks(
        option_type=OptionType.CALL,
        futures_price=Decimal("0"),
        strike=Decimal("100"),
        volatility=Decimal("0.2"),
        risk_free_rate=Decimal("0.01"),
        time_to_expiry=Decimal("1"),
    )
    put = black76_price_and_greeks(
        option_type=OptionType.PUT,
        futures_price=Decimal("0"),
        strike=Decimal("100"),
        volatility=Decimal("0.2"),
        risk_free_rate=Decimal("0.01"),
        time_to_expiry=Decimal("1"),
    )

    assert call.price == Decimal("0")
    assert put.price == pytest.approx(Decimal("99.004983"), abs=Decimal("0.000001"))
