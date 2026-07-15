"""Validated WGS84 geometries used by immutable traceability evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

Coordinate = tuple[Decimal, Decimal]


def _validate_coordinate(longitude: Decimal, latitude: Decimal) -> None:
    if not longitude.is_finite() or not latitude.is_finite():
        raise ValueError("geographic coordinates must be finite")
    if longitude < Decimal("-180") or longitude > Decimal("180"):
        raise ValueError("longitude must be between -180 and 180")
    if latitude < Decimal("-90") or latitude > Decimal("90"):
        raise ValueError("latitude must be between -90 and 90")


@dataclass(frozen=True)
class GeographicPoint:
    """One WGS84 longitude/latitude origin coordinate."""

    longitude: Decimal
    latitude: Decimal
    crs: str = "EPSG:4326"

    def __post_init__(self) -> None:
        if self.crs != "EPSG:4326":
            raise ValueError("traceability geometry CRS must be EPSG:4326")
        _validate_coordinate(self.longitude, self.latitude)

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "type": "Point",
            "crs": self.crs,
            "coordinates": [str(self.longitude), str(self.latitude)],
        }

    def to_wkt(self) -> str:
        """Return the WGS84 Well-Known Text form used by the PostGIS boundary."""
        return f"POINT({self.longitude} {self.latitude})"

    @property
    def coordinate_key(self) -> tuple[str, str]:
        return (str(self.longitude), str(self.latitude))


@dataclass(frozen=True)
class GeographicPolygon:
    """A simple, closed WGS84 polygon. Antimeridian-spanning areas are explicit rejects."""

    coordinates: tuple[Coordinate, ...]
    crs: str = "EPSG:4326"

    def __post_init__(self) -> None:
        if self.crs != "EPSG:4326":
            raise ValueError("traceability geometry CRS must be EPSG:4326")
        if len(self.coordinates) < 4:
            raise ValueError("polygon must have at least three vertices and a closing vertex")
        if self.coordinates[0] != self.coordinates[-1]:
            raise ValueError("polygon ring must be closed")
        unique_vertices = self.coordinates[:-1]
        if len(set(unique_vertices)) != len(unique_vertices):
            raise ValueError("polygon has duplicate vertices")
        for longitude, latitude in self.coordinates:
            _validate_coordinate(longitude, latitude)
        for first, second in pairwise(self.coordinates):
            if abs(first[0] - second[0]) > Decimal("180"):
                raise ValueError(
                    "polygon antimeridian crossing requires an approved split geometry"
                )
        if _self_intersects(self.coordinates):
            raise ValueError("polygon is self-intersecting")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "type": "Polygon",
            "crs": self.crs,
            "coordinates": [
                [str(longitude), str(latitude)] for longitude, latitude in self.coordinates
            ],
        }

    def to_wkt(self) -> str:
        """Return the WGS84 Well-Known Text form used by the PostGIS boundary."""
        coordinates = ", ".join(
            f"{longitude} {latitude}" for longitude, latitude in self.coordinates
        )
        return f"POLYGON(({coordinates}))"

    @property
    def coordinate_key(self) -> tuple[str, ...]:
        return tuple(f"{longitude}:{latitude}" for longitude, latitude in self.coordinates)


def _self_intersects(coordinates: tuple[Coordinate, ...]) -> bool:
    edges = tuple(pairwise(coordinates))
    for first_index, first in enumerate(edges):
        for second_index in range(first_index + 1, len(edges)):
            if second_index in (first_index - 1, first_index, first_index + 1):
                continue
            if first_index == 0 and second_index == len(edges) - 1:
                continue
            if _segments_intersect(first, edges[second_index]):
                return True
    return False


def _segments_intersect(
    first: tuple[Coordinate, Coordinate], second: tuple[Coordinate, Coordinate]
) -> bool:
    a, b = first
    c, d = second
    first_orientations = (_orientation(a, b, c), _orientation(a, b, d))
    second_orientations = (_orientation(c, d, a), _orientation(c, d, b))
    return (
        first_orientations[0] * first_orientations[1] < 0
        and second_orientations[0] * second_orientations[1] < 0
    )


def _orientation(first: Coordinate, second: Coordinate, third: Coordinate) -> Decimal:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])
