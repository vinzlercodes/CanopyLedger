"""M1B domain-pipeline contract tests."""

from decimal import Decimal

import pytest

from canopyledger.borrowing_base.calculation import (
    CollateralContribution,
    ContractualReserve,
    calculate_contractual_borrowing_base,
)
from canopyledger.borrowing_base.certificate import (
    ContractualUsage,
    DuplicateCollateralError,
    build_cbb_certificate,
)
from canopyledger.domain.money import Money
from canopyledger.domain.units import Quantity, UnitConversionTable, normalize_quantity
from canopyledger.receivables.eligibility import (
    ReceivableEligibilityPolicy,
    ReceivableStatus,
    assess_receivable_eligibility,
)
from canopyledger.receivables.valuation import ReceivableValuationInput, value_receivable


def test_values_receivable_using_credit_notes_fx_and_rounding() -> None:
    result = value_receivable(
        ReceivableValuationInput(
            receivable_id="rec_0198a000-0000-7000-8000-000000000001",
            invoice_amount=Money(Decimal("125000.00"), "USD"),
            credit_note_amount=Money(Decimal("2500.00"), "USD"),
            facility_currency="EUR",
            fx_facility_per_invoice=Decimal("0.91825"),
        )
    )

    assert result.open_amount == Money(Decimal("122500.00"), "USD")
    assert result.facility_value == Money(Decimal("112485.62"), "EUR")


def test_normalizes_inventory_quantity_units_with_versioned_factor() -> None:
    table = UnitConversionTable(
        version="unit-table-v1",
        factors={
            ("bag_60kg", "metric_tonne"): Decimal("0.06"),
            ("kilogram", "metric_tonne"): Decimal("0.001"),
        },
    )

    result = normalize_quantity(
        Quantity(Decimal("320"), "bag_60kg"),
        output_unit="metric_tonne",
        table=table,
    )

    assert result.input_value == Decimal("320")
    assert result.input_unit == "bag_60kg"
    assert result.factor == Decimal("0.06")
    assert result.output_value == Decimal("19.20000000")
    assert result.output_unit == "metric_tonne"
    assert result.conversion_table_version == "unit-table-v1"


def test_m1b_numeric_inputs_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="money amount must be finite"):
        Money(Decimal("NaN"), "EUR")

    with pytest.raises(ValueError, match="quantity must be finite"):
        Quantity(Decimal("Infinity"), "metric_tonne")

    with pytest.raises(ValueError, match="conversion factors must be positive and finite"):
        UnitConversionTable(
            version="unit-table-v1",
            factors={("bag_60kg", "metric_tonne"): Decimal("NaN")},
        )


def test_receivable_age_and_dispute_reasons_fail_closed() -> None:
    valuation = value_receivable(
        ReceivableValuationInput(
            receivable_id="rec_0198a000-0000-7000-8000-000000000001",
            invoice_amount=Money(Decimal("100.00"), "EUR"),
            credit_note_amount=Money(Decimal("0.00"), "EUR"),
            facility_currency="EUR",
            fx_facility_per_invoice=Decimal("1"),
        )
    )
    policy = ReceivableEligibilityPolicy(max_age_days=90, advance_rate=Decimal("0.80"))

    current = assess_receivable_eligibility(
        valuation,
        policy=policy,
        age_days=90,
        status=ReceivableStatus.CURRENT,
        delivery_evidence_approved=True,
        obligor_id="obl_1",
    )
    stale = assess_receivable_eligibility(
        valuation,
        policy=policy,
        age_days=91,
        status=ReceivableStatus.CURRENT,
        delivery_evidence_approved=True,
        obligor_id="obl_1",
    )
    disputed = assess_receivable_eligibility(
        valuation,
        policy=policy,
        age_days=10,
        status=ReceivableStatus.DISPUTED,
        delivery_evidence_approved=True,
        obligor_id="obl_1",
    )

    assert current.amount == Money(Decimal("80.00"), "EUR")
    assert stale.amount == Money(Decimal("0.00"), "EUR")
    assert "RECEIVABLE_EXCESS_AGE" in stale.reason_codes
    assert disputed.amount == Money(Decimal("0.00"), "EUR")
    assert "RECEIVABLE_DISPUTED" in disputed.reason_codes
    assert stale.amount.amount <= current.amount.amount


def test_builds_cbb_certificate_with_contractual_availability_and_digest() -> None:
    inventory = CollateralContribution(
        "inventory",
        "lot_0198a000-0000-7000-8000-000000000001",
        Money(Decimal("250000.00"), "EUR"),
    )
    receivable = CollateralContribution(
        "receivable",
        "rec_0198a000-0000-7000-8000-000000000001",
        Money(Decimal("112485.62"), "EUR"),
    )
    reserve = ContractualReserve("documentation", Money(Decimal("12485.62"), "EUR"))
    assessment = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("300000.00"), "EUR"),
        contributions=(inventory, receivable),
        reserves=(reserve,),
    )

    certificate = build_cbb_certificate(
        certificate_id="cbb_0198a000-0000-7000-8000-000000000001",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        facility_id="fac_0198a000-0000-7000-8000-000000000001",
        assessment=assessment,
        contributions=(inventory, receivable),
        reserves=(reserve,),
        usage=ContractualUsage(
            current_principal=Money(Decimal("120000.00"), "EUR"),
            lc_exposure=Money(Decimal("25000.00"), "EUR"),
            other_contractual_usage=Money(Decimal("10000.00"), "EUR"),
        ),
        reason_codes=("RECEIVABLE_CREDIT_NOTE_APPLIED",),
    )

    payload = certificate.to_canonical_dict()
    assert certificate.contractual_exposure_limit == Money(Decimal("300000.00"), "EUR")
    assert certificate.contractual_availability == Money(Decimal("145000.00"), "EUR")
    assert payload["output_digest"].startswith("sha256:")
    assert payload["result"]["contractual_availability"] == "145000.00"
    assert payload["result"]["contributions"][1]["source_type"] == "receivable"


def test_cbb_certificate_rejects_duplicate_collateral_sources() -> None:
    duplicate_a = CollateralContribution("receivable", "rec_1", Money(Decimal("50.00"), "EUR"))
    duplicate_b = CollateralContribution("receivable", "rec_1", Money(Decimal("50.00"), "EUR"))
    assessment = calculate_contractual_borrowing_base(
        facility_limit=Money(Decimal("1000.00"), "EUR"),
        contributions=(duplicate_a, duplicate_b),
        reserves=(),
    )

    with pytest.raises(DuplicateCollateralError):
        build_cbb_certificate(
            certificate_id="cbb_0198a000-0000-7000-8000-000000000001",
            snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
            facility_id="fac_0198a000-0000-7000-8000-000000000001",
            assessment=assessment,
            contributions=(duplicate_a, duplicate_b),
            reserves=(),
            usage=ContractualUsage(
                current_principal=Money(Decimal("0.00"), "EUR"),
                lc_exposure=Money(Decimal("0.00"), "EUR"),
                other_contractual_usage=Money(Decimal("0.00"), "EUR"),
            ),
            reason_codes=(),
        )
