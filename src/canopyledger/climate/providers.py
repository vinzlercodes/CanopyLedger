"""Read-only climate-data provider boundary for M5 reference fixtures and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from canopyledger.climate.engine import ClimateIndicator


class ClimateDataProvider(Protocol):
    """A provider supplies observations; it cannot evaluate evidence or publish calculations."""

    @property
    def provider_id(self) -> str: ...

    def observations_for(
        self, origin_country: str, *, as_of: date
    ) -> tuple[ClimateIndicator, ...]: ...


@dataclass(frozen=True)
class ReferenceClimateDataProvider:
    """Deterministic local reference provider used to build a frozen M5 input."""

    provider_id: str
    observations: tuple[ClimateIndicator, ...]

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("climate provider identity is required")
        if any(item.provider_id != self.provider_id for item in self.observations):
            raise ValueError("reference climate observation provider identities must match")

    def observations_for(self, origin_country: str, *, as_of: date) -> tuple[ClimateIndicator, ...]:
        country = origin_country.upper()
        return tuple(
            sorted(
                (
                    item
                    for item in self.observations
                    if item.origin_country.upper() == country and item.observed_at <= as_of
                ),
                key=lambda item: (item.indicator, item.observed_at, item.source_digest),
            )
        )
