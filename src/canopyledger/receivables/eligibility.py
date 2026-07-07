"""Deterministic receivable eligibility contribution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from canopyledger.domain.money import Money

from .valuation import ReceivableValuation


class ReceivableEligibilityError(ValueError):
    """Raised when receivable eligibility inputs violate contract."""


class ReceivableStatus(StrEnum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DISPUTED = "DISPUTED"
    RELATED_PARTY = "RELATED_PARTY"


@dataclass(frozen=True)
class ReceivableEligibilityPolicy:
    max_age_days: int
    advance_rate: Decimal

    def __post_init__(self) -> None:
        if self.max_age_days < 0:
            raise ReceivableEligibilityError("max age cannot be negative")
        if not self.advance_rate.is_finite() or not Decimal(0) <= self.advance_rate <= Decimal(1):
            raise ReceivableEligibilityError("advance rate must be between zero and one")


@dataclass(frozen=True)
class ReceivableEligibilityContribution:
    receivable_id: str
    obligor_id: str
    status: ReceivableStatus
    age_days: int
    applied_advance_rate: Decimal
    amount: Money
    reason_codes: tuple[str, ...]


def assess_receivable_eligibility(
    valuation: ReceivableValuation,
    *,
    policy: ReceivableEligibilityPolicy,
    age_days: int,
    status: ReceivableStatus,
    delivery_evidence_approved: bool,
    obligor_id: str,
) -> ReceivableEligibilityContribution:
    """Calculate receivable contribution after hard eligibility exclusions."""
    if age_days < 0:
        raise ReceivableEligibilityError("age cannot be negative")
    if not obligor_id:
        raise ReceivableEligibilityError("obligor id is required")

    reasons: list[str] = []
    if age_days > policy.max_age_days:
        reasons.append("RECEIVABLE_EXCESS_AGE")
    if status == ReceivableStatus.PAST_DUE:
        reasons.append("RECEIVABLE_PAST_DUE")
    if status == ReceivableStatus.DISPUTED:
        reasons.append("RECEIVABLE_DISPUTED")
    if status == ReceivableStatus.RELATED_PARTY:
        reasons.append("RECEIVABLE_RELATED_PARTY")
    if not delivery_evidence_approved:
        reasons.append("DELIVERY_EVIDENCE_MISSING")

    applied = Decimal(0) if reasons else policy.advance_rate
    amount = (valuation.facility_value.amount * applied).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )
    return ReceivableEligibilityContribution(
        receivable_id=valuation.receivable_id,
        obligor_id=obligor_id,
        status=status,
        age_days=age_days,
        applied_advance_rate=applied,
        amount=Money(amount, valuation.facility_value.currency),
        reason_codes=tuple(reasons),
    )
