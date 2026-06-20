"""Deterministic contractual borrowing-base calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from canopyledger.domain.money import Money


class BorrowingBaseError(ValueError):
    """Raised when borrowing-base inputs violate contract."""


@dataclass(frozen=True)
class CollateralContribution:
    source_type: str
    source_id: str
    amount: Money


@dataclass(frozen=True)
class ContractualReserve:
    reserve_type: str
    amount: Money


@dataclass(frozen=True)
class ContractualBorrowingBaseAssessment:
    currency: str
    facility_limit: Money
    gross_eligible_contribution: Money
    total_reserves: Money
    contractual_borrowing_base: Money


def calculate_contractual_borrowing_base(
    *,
    facility_limit: Money,
    contributions: tuple[CollateralContribution, ...],
    reserves: tuple[ContractualReserve, ...],
) -> ContractualBorrowingBaseAssessment:
    """Apply contractual contributions, reserves, zero floor, and facility limit."""
    currency = facility_limit.currency
    if facility_limit.amount < 0:
        raise BorrowingBaseError("facility limit cannot be negative")
    for item in contributions:
        if item.amount.currency != currency:
            raise BorrowingBaseError("all amounts must use facility currency")
        if item.amount.amount < 0:
            raise BorrowingBaseError("contributions and reserves cannot be negative")
    for reserve in reserves:
        if reserve.amount.currency != currency:
            raise BorrowingBaseError("all amounts must use facility currency")
        if reserve.amount.amount < 0:
            raise BorrowingBaseError("contributions and reserves cannot be negative")

    gross = sum((item.amount.amount for item in contributions), start=Decimal(0))
    reserve_total = sum((item.amount.amount for item in reserves), start=Decimal(0))
    net = max(Decimal(0), gross - reserve_total)
    borrowing_base = min(facility_limit.amount, net)

    return ContractualBorrowingBaseAssessment(
        currency=currency,
        facility_limit=facility_limit.quantized(),
        gross_eligible_contribution=Money(gross, currency).quantized(),
        total_reserves=Money(reserve_total, currency).quantized(),
        contractual_borrowing_base=Money(borrowing_base, currency).quantized(),
    )
