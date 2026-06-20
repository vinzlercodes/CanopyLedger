"""Authoritative money value object."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


class MoneyError(ValueError):
    """Raised for invalid money values."""


@dataclass(frozen=True)
class Money:
    """Decimal amount with explicit ISO-style currency code."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.amount.is_finite():
            raise MoneyError("money amount must be finite")
        if self.amount.is_zero() and self.amount.is_signed():
            raise MoneyError("negative zero is forbidden")
        if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isupper():
            raise MoneyError("currency must be a three-letter uppercase ASCII code")

    def quantized(self, scale: int = 2) -> Money:
        quantum = Decimal(1).scaleb(-scale)
        amount = self.amount.quantize(quantum, rounding=ROUND_HALF_EVEN)
        if amount.is_zero():
            amount = abs(amount)
        return Money(amount, self.currency)

