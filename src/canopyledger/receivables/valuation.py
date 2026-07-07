"""Deterministic receivable valuation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from canopyledger.domain.money import Money


class ReceivableValuationError(ValueError):
    """Raised when receivable valuation inputs violate contract."""


@dataclass(frozen=True)
class ReceivableValuationInput:
    receivable_id: str
    invoice_amount: Money
    credit_note_amount: Money
    facility_currency: str
    fx_facility_per_invoice: Decimal

    def __post_init__(self) -> None:
        if self.invoice_amount.currency != self.credit_note_amount.currency:
            raise ReceivableValuationError("invoice and credit note currencies must match")
        if self.invoice_amount.amount < 0 or self.credit_note_amount.amount < 0:
            raise ReceivableValuationError("receivable amounts cannot be negative")
        if self.credit_note_amount.amount > self.invoice_amount.amount:
            raise ReceivableValuationError("credit note cannot exceed invoice amount")
        if (
            len(self.facility_currency) != 3
            or not self.facility_currency.isascii()
            or not self.facility_currency.isupper()
        ):
            raise ReceivableValuationError(
                "facility currency must be a three-letter uppercase code"
            )
        if not self.fx_facility_per_invoice.is_finite() or self.fx_facility_per_invoice <= 0:
            raise ReceivableValuationError("FX rate must be positive and finite")


@dataclass(frozen=True)
class ReceivableValuation:
    receivable_id: str
    invoice_amount: Money
    credit_note_amount: Money
    open_amount: Money
    facility_value: Money


def value_receivable(value: ReceivableValuationInput) -> ReceivableValuation:
    """Apply credit notes and FX conversion into facility currency."""
    open_amount = Money(
        value.invoice_amount.amount - value.credit_note_amount.amount,
        value.invoice_amount.currency,
    ).quantized()
    fx_rate = (
        Decimal(1)
        if value.invoice_amount.currency == value.facility_currency
        else value.fx_facility_per_invoice
    )
    facility_value = Money(
        open_amount.amount * fx_rate,
        value.facility_currency,
    ).quantized()
    return ReceivableValuation(
        receivable_id=value.receivable_id,
        invoice_amount=value.invoice_amount.quantized(),
        credit_note_amount=value.credit_note_amount.quantized(),
        open_amount=open_amount,
        facility_value=facility_value,
    )
