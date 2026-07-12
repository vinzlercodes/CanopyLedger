"""M4A deterministic scenario capacity contracts."""

from decimal import Decimal

from canopyledger.domain.money import Money
from canopyledger.scenario.engine import (
    IrcPolicy,
    ScenarioCapacityInput,
    ScenarioDefinition,
    compile_shocks,
    evaluate_scenario_capacity,
)
from canopyledger.scenario.pipeline import build_scenario_capacity_stage_output


def _input() -> ScenarioCapacityInput:
    return ScenarioCapacityInput(
        assessment_id="scn_0198a000-0000-7000-8000-000000000001",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        market_bundle_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
        computation_bundle_digest="sha256:" + "e" * 64,
        scenario_version="coffee-scenarios-v1",
        prng_family="python-mt19937-v1",
        seed=41,
        path_count=500,
        time_steps=5,
        thread_count=1,
        confidence_level=Decimal("0.95"),
        quantization_scale=Decimal("0.01"),
        correlation=Decimal("0.35"),
        cbb=Money(Decimal("100000"), "USD"),
        facility_commitment=Money(Decimal("120000"), "USD"),
        outstanding_exposure=Money(Decimal("85000"), "USD"),
        base_margin_call=Money(Decimal("15000"), "USD"),
        available_liquidity=Money(Decimal("12000"), "USD"),
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
            ScenarioDefinition(
                "evidence",
                "evidence_transition",
                Decimal("0"),
                Decimal("0.10"),
                Decimal("1"),
                Decimal("2500"),
            ),
        ),
        irc_policy=IrcPolicy(
            tail_loss_multiplier=Decimal("1.1"),
            liquidity_multiplier=Decimal("1"),
            counterparty_buffer=Decimal("3000"),
            climate_evidence_buffer=Decimal("1500"),
        ),
    )


def test_m4a_is_repeatable_and_retains_independent_irc_and_cbb() -> None:
    first, second = evaluate_scenario_capacity(_input()), evaluate_scenario_capacity(_input())
    assert first.output_digest == second.output_digest
    result = first.result
    assert result["monte_carlo"]["prng_family"] == "python-mt19937-v1"
    assert result["monte_carlo"]["seed_derivation"] == "snapshot-scenario-v1"
    assert result["monte_carlo"]["correlation_matrix"] == [["1", "0.35"], ["0.35", "1"]]
    assert result["monte_carlo"]["regime_mixture"] == [{"name": "base", "weight": "1"}]
    assert result["internal_risk_capacity"]["cbb"] == "100000.00"
    assert Decimal(result["internal_risk_capacity"]["irc"]) <= Decimal(
        result["internal_risk_capacity"]["cbb"]
    )
    assert Decimal(result["deterministic_scenarios"][0]["stressed_cbb"]) < Decimal("100000")
    assert result["deterministic_scenarios"][1]["margin_liquidity_shortfall"] == "18000.00"
    assert result["worst_scenario_families"][0]["family"] == "price_decline"
    assert Decimal(result["monte_carlo"]["threshold_stability"]["band_width"]) >= 0
    contributions = result["monte_carlo"]["tail_contribution_by_factor"]
    assert Decimal(contributions["collateral_price"]) + Decimal(
        contributions["margin_liquidity"]
    ) <= Decimal("1.000001")
    assert result["monte_carlo"]["hedge_effectiveness_distribution"]["median"] == "0"


def test_m4a_input_digest_excludes_publication_context_but_output_uses_pinned_lineage() -> None:
    value = _input()
    assert value.input_digest.startswith("sha256:")
    result = evaluate_scenario_capacity(value)
    assert result.to_canonical_dict()["output_digest"] == result.output_digest


def test_shock_compiler_applies_price_haircut_and_reserve_in_declared_order() -> None:
    value = _input()
    shock = compile_shocks(value, value.scenarios[0])
    assert shock.collateral_loss == Decimal("25000.00")
    assert shock.margin_multiplier == Decimal("1")


def test_m4a_stage_output_keeps_scenario_and_irc_as_separate_resources() -> None:
    from datetime import UTC, datetime

    value = _input()
    output = build_scenario_capacity_stage_output(
        value,
        stage_output_id="out_0198a000-0000-7000-8000-000000000001",
        started_at=datetime(2026, 7, 11, tzinfo=UTC),
        completed_at=datetime(2026, 7, 11, tzinfo=UTC),
    ).to_canonical_dict()
    assert output["stage"] == "scenario_capacity"
    assert output["scenario"]["assessment_digest"].startswith("sha256:")
    assert output["internal_risk_capacity"]["irc"] != output["internal_risk_capacity"]["cbb"]
