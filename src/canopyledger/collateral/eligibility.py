"""Deterministic collateral eligibility contribution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from canopyledger.domain.money import Money

from .valuation import InventoryValuation


class EligibilityError(ValueError):
    """Raised for invalid eligibility parameters."""


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    INELIGIBLE = "INELIGIBLE"
    PENDING_REVIEW = "PENDING_REVIEW"


@dataclass(frozen=True)
class EligibilityContribution:
    lot_id: str
    status: EligibilityStatus
    applied_advance_rate: Decimal
    amount: Money
    reason_codes: tuple[str, ...]


def contribution_from_valuation(
    valuation: InventoryValuation,
    *,
    status: EligibilityStatus,
    base_advance_rate: Decimal,
    reason_codes: tuple[str, ...],
    maximum_advance_rate: Decimal | None = None,
) -> EligibilityContribution:
    """Calculate contractual contribution after deterministic eligibility outcome."""
    _validate_rate(base_advance_rate, "base advance rate")
    if maximum_advance_rate is not None:
        _validate_rate(maximum_advance_rate, "maximum advance rate")
    if status in {EligibilityStatus.INELIGIBLE, EligibilityStatus.PENDING_REVIEW}:
        applied = Decimal(0)
    elif maximum_advance_rate is None:
        applied = base_advance_rate
    else:
        applied = min(base_advance_rate, maximum_advance_rate)

    amount = (valuation.net_recovery_value.amount * applied).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )
    return EligibilityContribution(
        lot_id=valuation.lot_id,
        status=status,
        applied_advance_rate=applied,
        amount=Money(amount, valuation.net_recovery_value.currency),
        reason_codes=reason_codes,
    )


def _validate_rate(value: Decimal, name: str) -> None:
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
        raise EligibilityError(f"{name} must be between zero and one")

