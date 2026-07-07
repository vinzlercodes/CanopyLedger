"""Versioned unit normalization primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


class UnitConversionError(ValueError):
    """Raised when unit conversion inputs violate contract."""


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise UnitConversionError("quantity must be finite")
        if self.value < 0:
            raise UnitConversionError("quantity cannot be negative")
        if not self.unit:
            raise UnitConversionError("unit is required")


@dataclass(frozen=True)
class UnitConversionTable:
    version: str
    factors: dict[tuple[str, str], Decimal]

    def __post_init__(self) -> None:
        if not self.version:
            raise UnitConversionError("conversion table version is required")
        for factor in self.factors.values():
            if not factor.is_finite() or factor <= 0:
                raise UnitConversionError("conversion factors must be positive and finite")


@dataclass(frozen=True)
class UnitConversion:
    input_value: Decimal
    input_unit: str
    factor: Decimal
    output_value: Decimal
    output_unit: str
    conversion_table_version: str


def normalize_quantity(
    quantity: Quantity,
    *,
    output_unit: str,
    table: UnitConversionTable,
) -> UnitConversion:
    """Convert a quantity using a versioned factor table."""
    if not output_unit:
        raise UnitConversionError("output unit is required")
    factor = Decimal(1) if quantity.unit == output_unit else table.factors.get(
        (quantity.unit, output_unit)
    )
    if factor is None:
        raise UnitConversionError("unit conversion factor is not defined")
    output = (quantity.value * factor).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)
    return UnitConversion(
        input_value=quantity.value,
        input_unit=quantity.unit,
        factor=factor,
        output_value=output,
        output_unit=output_unit,
        conversion_table_version=table.version,
    )
