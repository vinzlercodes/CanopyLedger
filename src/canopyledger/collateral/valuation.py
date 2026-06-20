"""Deterministic inventory-lot valuation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from canopyledger.domain.money import Money


class ValuationError(ValueError):
    """Raised when valuation inputs violate their domain."""


@dataclass(frozen=True)
class InventoryValuationInput:
    lot_id: str
    quantity_mt: Decimal
    benchmark_price_usd_per_mt: Decimal
    physical_differential_usd_per_mt: Decimal
    selling_cost_usd_per_mt: Decimal
    fx_eur_per_usd: Decimal
    liquidation_cost_eur: Decimal

    def __post_init__(self) -> None:
        values = (
            self.quantity_mt,
            self.benchmark_price_usd_per_mt,
            self.physical_differential_usd_per_mt,
            self.selling_cost_usd_per_mt,
            self.fx_eur_per_usd,
            self.liquidation_cost_eur,
        )
        if any(not value.is_finite() for value in values):
            raise ValuationError("valuation inputs must be finite")
        if self.quantity_mt < 0:
            raise ValuationError("quantity cannot be negative")
        if self.benchmark_price_usd_per_mt < 0:
            raise ValuationError("benchmark price cannot be negative")
        if self.selling_cost_usd_per_mt < 0 or self.liquidation_cost_eur < 0:
            raise ValuationError("costs cannot be negative")
        if self.fx_eur_per_usd <= 0:
            raise ValuationError("FX rate must be positive")


@dataclass(frozen=True)
class InventoryValuation:
    lot_id: str
    gross_market_value: Money
    net_recovery_value: Money


def value_inventory_lot(value: InventoryValuationInput) -> InventoryValuation:
    """Apply benchmark, differential, selling cost, FX, and liquidation cost."""
    raw_gross = (
        value.quantity_mt
        * (
            value.benchmark_price_usd_per_mt
            + value.physical_differential_usd_per_mt
            - value.selling_cost_usd_per_mt
        )
        * value.fx_eur_per_usd
    )
    raw_net = max(Decimal(0), raw_gross - value.liquidation_cost_eur)
    return InventoryValuation(
        lot_id=value.lot_id,
        gross_market_value=Money(max(Decimal(0), raw_gross), "EUR").quantized(),
        net_recovery_value=Money(raw_net, "EUR").quantized(),
    )

