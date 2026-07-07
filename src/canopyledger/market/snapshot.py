"""Deterministic market snapshot resource."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


class MarketSnapshotError(ValueError):
    """Raised when market snapshot inputs violate contract."""


@dataclass(frozen=True)
class PriceObservation:
    symbol: str
    price: Decimal
    unit: str
    observed_at: str
    source: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.unit or not self.observed_at or not self.source:
            raise MarketSnapshotError("price observation metadata is required")
        if not self.price.is_finite() or self.price < 0:
            raise MarketSnapshotError("price must be finite and non-negative")

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "price": str(self.price),
            "unit": self.unit,
            "observed_at": self.observed_at,
            "source": self.source,
        }


@dataclass(frozen=True)
class FxRate:
    pair: str
    rate: Decimal
    observed_at: str
    source: str

    def __post_init__(self) -> None:
        if not self.pair or not self.observed_at or not self.source:
            raise MarketSnapshotError("FX metadata is required")
        if not self.rate.is_finite() or self.rate <= 0:
            raise MarketSnapshotError("FX rate must be finite and positive")

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "pair": self.pair,
            "rate": str(self.rate),
            "observed_at": self.observed_at,
            "source": self.source,
        }


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    as_of: str
    prices: tuple[PriceObservation, ...]
    fx_rates: tuple[FxRate, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.as_of:
            raise MarketSnapshotError("market snapshot id and as-of are required")
        if not self.prices:
            raise MarketSnapshotError("at least one price observation is required")
        if not self.fx_rates:
            raise MarketSnapshotError("at least one FX observation is required")
        if len({price.symbol for price in self.prices}) != len(self.prices):
            raise MarketSnapshotError("duplicate price symbol")
        if len({rate.pair for rate in self.fx_rates}) != len(self.fx_rates):
            raise MarketSnapshotError("duplicate FX pair")

    @property
    def digest(self) -> str:
        return domain_digest("market_snapshot", 1, canonical_json_bytes(self.to_canonical_dict()))

    def price(self, symbol: str) -> PriceObservation:
        for item in self.prices:
            if item.symbol == symbol:
                return item
        raise MarketSnapshotError("price observation not found")

    def fx_rate(self, pair: str) -> FxRate:
        for item in self.fx_rates:
            if item.pair == pair:
                return item
        raise MarketSnapshotError("FX observation not found")

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "as_of": self.as_of,
            "prices": [price.to_canonical_dict() for price in self.prices],
            "fx_rates": [rate.to_canonical_dict() for rate in self.fx_rates],
        }
