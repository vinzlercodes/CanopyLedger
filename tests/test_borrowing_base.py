"""Golden tests for deterministic M1B financial calculations."""

from decimal import Decimal

import pytest

from canopyledger.borrowing_base.calculation import (
    BorrowingBaseError,
    CollateralContribution,
    ContractualReserve,
    calculate_contractual_borrowing_base,
)
from canopyledger.collateral.eligibility import EligibilityStatus, contribution_from_valuation
from canopyledger.collateral.valuation import InventoryValuationInput, value_inventory_lot
from canopyledger.domain.money import Money


def test_values_inventory_lot_using_explicit_units_fx_and_costs() -> None:
    result = value_inventory_lot(
        InventoryValuationInput(
            lot_id="lot_0198a000-0000-7000-8000-000000000001",
            quantity_mt=Decimal("18.4"),
            benchmark_price_usd_per_mt=Decimal("5871.42"),
            physical_differential_usd_per_mt=Decimal("185.00"),
            selling_cost_usd_per_mt=Decimal("142.00"),
            fx_eur_per_usd=Decimal("0.918"),
            liquidation_cost_eur=Decimal("5200.00"),
        )
    )
    assert result.gross_market_value == Money(Decimal("99901.65"), "EUR")
    assert result.net_recovery_value == Money(Decimal("94701.65"), "EUR")


def test_conditional_eligibility_uses_policy_capped_advance_rate() -> None:
    valuation = value_inventory_lot(
        InventoryValuationInput(
            lot_id="lot_0198a000-0000-7000-8000-000000000001",
            quantity_mt=Decimal("18.4"),
            benchmark_price_usd_per_mt=Decimal("5871.42"),
            physical_differential_usd_per_mt=Decimal("185.00"),
            selling_cost_usd_per_mt=Decimal("142.00"),
            fx_eur_per_usd=Decimal("0.918"),
            liquidation_cost_eur=Decimal("5200.00"),
        )
    )
    contribution = contribution_from_valuation(
        valuation,
        status=EligibilityStatus.CONDITIONAL,
        base_advance_rate=Decimal("0.65"),
        maximum_advance_rate=Decimal("0.25"),
        reason_codes=("EUDR_PLOT_LINK_INCOMPLETE",),
    )
    assert contribution.applied_advance_rate == Decimal("0.25")
    assert contribution.amount == Money(Decimal("23675.41"), "EUR")


def test_ineligible_collateral_contributes_zero() -> None:
    valuation = value_inventory_lot(
        InventoryValuationInput(
            lot_id="lot_0198a000-0000-7000-8000-000000000001",
            quantity_mt=Decimal("1"),
            benchmark_price_usd_per_mt=Decimal("100"),
            physical_differential_usd_per_mt=Decimal("0"),
            selling_cost_usd_per_mt=Decimal("0"),
            fx_eur_per_usd=Decimal("1"),
            liquidation_cost_eur=Decimal("0"),
        )
    )
    contribution = contribution_from_valuation(
        valuation,
        status=EligibilityStatus.INELIGIBLE,
        base_advance_rate=Decimal("0.65"),
        reason_codes=("TITLE_MISSING",),
    )
    assert contribution.amount == Money(Decimal("0.00"), "EUR")


def test_calculates_contractual_borrowing_base_after_reserves_and_limit() -> None:
    assessment = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("50000000.00"), "EUR"),
        contributions=(
            CollateralContribution("inventory", "lot_1", Money(Decimal("25000000"), "EUR")),
            CollateralContribution("receivable", "rec_1", Money(Decimal("12000000"), "EUR")),
        ),
        reserves=(
            ContractualReserve("buyer_concentration", Money(Decimal("2000000"), "EUR")),
        ),
    )
    assert assessment.gross_eligible_contribution == Money(Decimal("37000000.00"), "EUR")
    assert assessment.total_reserves == Money(Decimal("2000000.00"), "EUR")
    assert assessment.contractual_borrowing_base == Money(Decimal("35000000.00"), "EUR")


def test_facility_limit_caps_contractual_borrowing_base() -> None:
    assessment = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("100.00"), "EUR"),
        contributions=(CollateralContribution("inventory", "lot_1", Money(Decimal("150"), "EUR")),),
        reserves=(),
    )
    assert assessment.contractual_borrowing_base == Money(Decimal("100.00"), "EUR")


def test_currency_mismatch_fails_closed() -> None:
    with pytest.raises(BorrowingBaseError, match="currency"):
        calculate_contractual_borrowing_base(
            facility_limit=Money(Decimal("100.00"), "EUR"),
            contributions=(
                CollateralContribution("inventory", "lot_1", Money(Decimal("50"), "USD")),
            ),
            reserves=(),
        )


def test_increasing_reserve_cannot_increase_borrowing_base() -> None:
    contribution = CollateralContribution("inventory", "lot_1", Money(Decimal("100"), "EUR"))
    lower = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("100"), "EUR"),
        contributions=(contribution,),
        reserves=(ContractualReserve("reserve", Money(Decimal("10"), "EUR")),),
    )
    higher = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("100"), "EUR"),
        contributions=(contribution,),
        reserves=(ContractualReserve("reserve", Money(Decimal("20"), "EUR")),),
    )
    assert higher.contractual_borrowing_base.amount <= lower.contractual_borrowing_base.amount
