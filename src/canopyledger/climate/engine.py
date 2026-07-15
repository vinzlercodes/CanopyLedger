"""Pure deterministic M5 evidence readiness, climate, and financed-emissions assessment."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from canopyledger.climate.eudr import (
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceNodeType,
    EvidenceStatus,
    LegalInterpretationPolicy,
    TraceabilityLot,
)
from canopyledger.climate.geometry import GeographicPoint, GeographicPolygon
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


class ClimateEudrError(ValueError):
    """Raised when an M5 authoritative input violates its pinned contract."""


_QUANTUM = Decimal("0.000001")


def _decimal(value: Decimal) -> str:
    return str(value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN))


def _require_digest(value: str, label: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ClimateEudrError(f"{label} must be a SHA-256 digest")


@dataclass(frozen=True)
class ClimateIndicator:
    origin_country: str
    indicator: str
    value: Decimal
    unit: str
    observed_at: date
    provider_id: str
    source_digest: str

    def __post_init__(self) -> None:
        if len(self.origin_country) != 2 or not self.origin_country.isalpha():
            raise ClimateEudrError("climate indicator origin country is invalid")
        if (
            not self.indicator
            or not self.unit
            or not self.provider_id
            or not self.value.is_finite()
        ):
            raise ClimateEudrError("climate indicator fields must be present and finite")
        _require_digest(self.source_digest, "climate indicator source digest")

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "origin_country": self.origin_country.upper(),
            "indicator": self.indicator,
            "value": _decimal(self.value),
            "unit": self.unit,
            "observed_at": self.observed_at.isoformat(),
            "provider_id": self.provider_id,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True)
class ClimateScenario:
    scenario_id: str
    family: str
    yield_shock: Decimal
    quality_shock: Decimal
    shipment_delay_days: int
    evidence_cost: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.family or len(self.currency) != 3:
            raise ClimateEudrError("climate scenario identity and currency are required")
        if (
            not self.yield_shock.is_finite()
            or not self.quality_shock.is_finite()
            or not self.evidence_cost.is_finite()
            or self.evidence_cost < 0
            or self.shipment_delay_days < 0
        ):
            raise ClimateEudrError("climate scenario values are invalid")

    def to_canonical_dict(self) -> dict[str, str | int]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "yield_shock": _decimal(self.yield_shock),
            "quality_shock": _decimal(self.quality_shock),
            "shipment_delay_days": self.shipment_delay_days,
            "evidence_cost": _decimal(self.evidence_cost),
            "currency": self.currency.upper(),
        }


@dataclass(frozen=True)
class FinancedEmissionsInput:
    borrower_scope_1: Decimal
    borrower_scope_2: Decimal
    borrower_scope_3: Decimal | None
    attribution_numerator: Decimal
    attribution_denominator: Decimal
    methodology_version: str
    data_quality_score: int
    source_period: str
    estimation_method: str
    restatement_lineage: str | None

    def __post_init__(self) -> None:
        values = (
            self.borrower_scope_1,
            self.borrower_scope_2,
            self.attribution_numerator,
            self.attribution_denominator,
        ) + ((self.borrower_scope_3,) if self.borrower_scope_3 is not None else ())
        if any(not value.is_finite() or value < 0 for value in values):
            raise ClimateEudrError("financed-emissions values must be finite and non-negative")
        if (
            self.attribution_denominator <= 0
            or self.attribution_numerator > self.attribution_denominator
        ):
            raise ClimateEudrError("financed-emissions attribution factor is invalid")
        if self.data_quality_score not in range(1, 6):
            raise ClimateEudrError("financed-emissions data-quality score must be between 1 and 5")
        if not self.methodology_version or not self.source_period or not self.estimation_method:
            raise ClimateEudrError("financed-emissions methodology provenance is required")
        if self.restatement_lineage is not None and not self.restatement_lineage:
            raise ClimateEudrError("financed-emissions restatement lineage must not be empty")

    def to_canonical_dict(self) -> dict[str, str | int | None]:
        return {
            "borrower_scope_1": _decimal(self.borrower_scope_1),
            "borrower_scope_2": _decimal(self.borrower_scope_2),
            "borrower_scope_3": _decimal(self.borrower_scope_3)
            if self.borrower_scope_3 is not None
            else None,
            "attribution_numerator": _decimal(self.attribution_numerator),
            "attribution_denominator": _decimal(self.attribution_denominator),
            "methodology_version": self.methodology_version,
            "data_quality_score": self.data_quality_score,
            "source_period": self.source_period,
            "estimation_method": self.estimation_method,
            "restatement_lineage": self.restatement_lineage,
        }


@dataclass(frozen=True)
class ClimateEudrInput:
    assessment_id: str
    snapshot_id: str
    legal_interpretation_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    legal_policy: LegalInterpretationPolicy
    traceability_lots: tuple[TraceabilityLot, ...]
    climate_indicators: tuple[ClimateIndicator, ...]
    climate_scenarios: tuple[ClimateScenario, ...]
    financed_emissions: FinancedEmissionsInput

    def __post_init__(self) -> None:
        if not self.assessment_id.startswith("clm_") or not self.snapshot_id.startswith("snp_"):
            raise ClimateEudrError("M5 assessment and snapshot identifiers are invalid")
        for value, label in (
            (self.legal_interpretation_bundle_digest, "legal bundle digest"),
            (self.policy_bundle_digest, "policy bundle digest"),
            (self.computation_bundle_digest, "computation bundle digest"),
        ):
            _require_digest(value, label)
        lot_ids = tuple(lot.lot_id for lot in self.traceability_lots)
        if not lot_ids or len(lot_ids) != len(set(lot_ids)):
            raise ClimateEudrError("M5 requires uniquely identified traceability lots")
        if len({scenario.scenario_id for scenario in self.climate_scenarios}) != len(
            self.climate_scenarios
        ):
            raise ClimateEudrError("climate scenarios must have unique identifiers")

    def to_input_canonical_dict(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "snapshot_id": self.snapshot_id,
            "legal_interpretation_bundle_digest": self.legal_interpretation_bundle_digest,
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "legal_policy": self.legal_policy.to_canonical_dict(),
            "traceability_lots": [
                lot.to_canonical_dict()
                for lot in sorted(self.traceability_lots, key=lambda item: item.lot_id)
            ],
            "climate_indicators": [
                value.to_canonical_dict()
                for value in sorted(
                    self.climate_indicators,
                    key=lambda item: (
                        item.origin_country,
                        item.indicator,
                        item.observed_at,
                        item.source_digest,
                    ),
                )
            ],
            "climate_scenarios": [
                value.to_canonical_dict()
                for value in sorted(self.climate_scenarios, key=lambda item: item.scenario_id)
            ],
            "financed_emissions": self.financed_emissions.to_canonical_dict(),
        }

    def to_stored_input_canonical_dict(self) -> dict[str, object]:
        """Exclude bindings that are supplied by the snapshot freeze transaction.

        The source input must exist before the snapshot that pins it. Snapshot and
        bundle IDs are consequently checked and injected by the durable runner,
        rather than becoming mutable pre-freeze input content.
        """
        payload = self.to_input_canonical_dict()
        for field in (
            "snapshot_id",
            "legal_interpretation_bundle_digest",
            "policy_bundle_digest",
            "computation_bundle_digest",
        ):
            payload.pop(field)
        return payload

    @classmethod
    def from_frozen_input(
        cls,
        payload: dict[str, object],
        *,
        snapshot_id: str | None = None,
        legal_interpretation_bundle_digest: str | None = None,
        policy_bundle_digest: str | None = None,
        computation_bundle_digest: str | None = None,
    ) -> ClimateEudrInput:
        """Hydrate only canonical stored values; callers still verify the input digest."""
        try:
            legal_value = _mapping(payload, "legal_policy")
            legal_policy = LegalInterpretationPolicy(
                bundle_version=_string(legal_value, "bundle_version"),
                production_cutoff=date.fromisoformat(_string(legal_value, "production_cutoff")),
                evidence_freshness_days=_integer(legal_value, "evidence_freshness_days"),
                country_risk_reference_version=_string(
                    legal_value, "country_risk_reference_version"
                ),
            )
            lots = tuple(_traceability_lot(value) for value in _rows(payload, "traceability_lots"))
            indicators = tuple(
                ClimateIndicator(
                    origin_country=_string(value, "origin_country"),
                    indicator=_string(value, "indicator"),
                    value=Decimal(_string(value, "value")),
                    unit=_string(value, "unit"),
                    observed_at=date.fromisoformat(_string(value, "observed_at")),
                    provider_id=_string(value, "provider_id"),
                    source_digest=_string(value, "source_digest"),
                )
                for value in _rows(payload, "climate_indicators")
            )
            scenarios = tuple(
                ClimateScenario(
                    scenario_id=_string(value, "scenario_id"),
                    family=_string(value, "family"),
                    yield_shock=Decimal(_string(value, "yield_shock")),
                    quality_shock=Decimal(_string(value, "quality_shock")),
                    shipment_delay_days=_integer(value, "shipment_delay_days"),
                    evidence_cost=Decimal(_string(value, "evidence_cost")),
                    currency=_string(value, "currency"),
                )
                for value in _rows(payload, "climate_scenarios")
            )
            emissions = _mapping(payload, "financed_emissions")
            scope_3 = emissions.get("borrower_scope_3")
            financed_emissions = FinancedEmissionsInput(
                borrower_scope_1=Decimal(_string(emissions, "borrower_scope_1")),
                borrower_scope_2=Decimal(_string(emissions, "borrower_scope_2")),
                borrower_scope_3=Decimal(scope_3) if isinstance(scope_3, str) else None,
                attribution_numerator=Decimal(_string(emissions, "attribution_numerator")),
                attribution_denominator=Decimal(_string(emissions, "attribution_denominator")),
                methodology_version=_string(emissions, "methodology_version"),
                data_quality_score=_integer(emissions, "data_quality_score"),
                source_period=_string(emissions, "source_period"),
                estimation_method=_string(emissions, "estimation_method"),
                restatement_lineage=(
                    _string(emissions, "restatement_lineage")
                    if emissions.get("restatement_lineage") is not None
                    else None
                ),
            )
            return cls(
                assessment_id=_string(payload, "assessment_id"),
                snapshot_id=snapshot_id or _string(payload, "snapshot_id"),
                legal_interpretation_bundle_digest=(
                    legal_interpretation_bundle_digest
                    or _string(payload, "legal_interpretation_bundle_digest")
                ),
                policy_bundle_digest=(
                    policy_bundle_digest or _string(payload, "policy_bundle_digest")
                ),
                computation_bundle_digest=(
                    computation_bundle_digest or _string(payload, "computation_bundle_digest")
                ),
                legal_policy=legal_policy,
                traceability_lots=lots,
                climate_indicators=indicators,
                climate_scenarios=scenarios,
                financed_emissions=financed_emissions,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise ClimateEudrError("stored climate/EUDR input is malformed") from exc

    @property
    def input_digest(self) -> str:
        return domain_digest(
            "climate_eudr_input", 1, canonical_json_bytes(self.to_stored_input_canonical_dict())
        )


@dataclass(frozen=True)
class ClimateEudrAssessment:
    assessment_id: str
    snapshot_id: str
    eudr_evidence_state: EvidenceStatus
    reason_codes: tuple[str, ...]
    result: dict[str, object]
    completed_at: datetime
    output_digest: str

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "assessment_id": self.assessment_id,
            "snapshot_id": self.snapshot_id,
            "eudr_evidence_state": self.eudr_evidence_state.value,
            "reason_codes": list(self.reason_codes),
            "result": self.result,
            "completed_at": self.completed_at.isoformat(),
            "output_digest": self.output_digest,
        }


def assess_climate_eudr(
    value: ClimateEudrInput, *, completed_at: datetime
) -> ClimateEudrAssessment:
    """Evaluate only immutable evidence/policy inputs and never infer legal compliance."""
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ClimateEudrError("M5 completion time must be timezone-aware")
    lot_results, reasons, state = _traceability_result(
        value.traceability_lots, value.legal_policy, completed_at
    )
    result: dict[str, object] = {
        "eudr_evidence_state": state.value,
        "legal_interpretation": {
            "bundle_version": value.legal_policy.bundle_version,
            "production_cutoff": value.legal_policy.production_cutoff.isoformat(),
            "country_risk_reference_version": value.legal_policy.country_risk_reference_version,
            "disclaimer": (
                "Evidence readiness is an operational state, not a legal compliance conclusion."
            ),
        },
        "traceability": {
            "lots": lot_results,
            "origin_concentration": _origin_concentration(value.traceability_lots),
        },
        "climate_indicators": [
            indicator.to_canonical_dict()
            for indicator in sorted(
                value.climate_indicators, key=lambda item: (item.origin_country, item.indicator)
            )
        ],
        "climate_scenarios": [
            scenario.to_canonical_dict()
            for scenario in sorted(value.climate_scenarios, key=lambda item: item.scenario_id)
        ],
        "financed_emissions": _financed_emissions_result(value.financed_emissions),
    }
    draft = {
        "assessment_id": value.assessment_id,
        "snapshot_id": value.snapshot_id,
        "eudr_evidence_state": state.value,
        "reason_codes": list(reasons),
        "result": result,
        "completed_at": completed_at.isoformat(),
    }
    return ClimateEudrAssessment(
        assessment_id=value.assessment_id,
        snapshot_id=value.snapshot_id,
        eudr_evidence_state=state,
        reason_codes=tuple(reasons),
        result=result,
        completed_at=completed_at,
        output_digest=domain_digest("climate_eudr_assessment", 1, canonical_json_bytes(draft)),
    )


def _traceability_result(
    lots: tuple[TraceabilityLot, ...], policy: LegalInterpretationPolicy, completed_at: datetime
) -> tuple[list[dict[str, object]], tuple[str, ...], EvidenceStatus]:
    reasons: list[str] = []
    coordinates: Counter[tuple[str, ...] | tuple[str, str]] = Counter()
    results: list[dict[str, object]] = []
    for lot in sorted(lots, key=lambda item: item.lot_id):
        geometry_key = lot.geometry.coordinate_key
        coordinates[geometry_key] += 1
        missing_links = lot.graph.missing_chain_steps()
        date_class = lot.production_date_class(policy)
        stale = (
            lot.evidence_recorded_at + timedelta(days=policy.evidence_freshness_days)
            < completed_at
        )
        lot_reasons: list[str] = []
        if missing_links:
            lot_reasons.append("TRACEABILITY_MISSING_LINK")
        if date_class.value == "not_reviewed":
            lot_reasons.append("PRODUCTION_DATE_NOT_REVIEWED")
        if lot.country_risk_reference != policy.country_risk_reference_version:
            lot_reasons.append("COUNTRY_RISK_REFERENCE_MISSING")
        if stale:
            lot_reasons.append("TRACEABILITY_EVIDENCE_STALE")
        reasons.extend(lot_reasons)
        results.append(
            {
                "lot_id": lot.lot_id,
                "origin_country": lot.origin_country.upper(),
                "geometry": lot.geometry.to_canonical_dict(),
                "geometry_state": "valid",
                "production_date": lot.production_date.isoformat() if lot.production_date else None,
                "production_date_class": date_class.value,
                "country_risk_reference": lot.country_risk_reference,
                "evidence_document_digest": lot.evidence_document_digest,
                "evidence_recorded_at": lot.evidence_recorded_at.isoformat(),
                "freshness_state": "stale" if stale else "current",
                "missing_links": list(missing_links),
                "reason_codes": lot_reasons,
                "evidence_graph": lot.graph.to_canonical_dict(),
            }
        )
    if any(count > 1 for count in coordinates.values()):
        reasons.append("DUPLICATE_ORIGIN_COORDINATE")
    unique_reasons = tuple(sorted(set(reasons)))
    if "DUPLICATE_ORIGIN_COORDINATE" in unique_reasons:
        state = EvidenceStatus.CONFLICTING
    elif any(
        reason in unique_reasons
        for reason in (
            "TRACEABILITY_MISSING_LINK",
            "PRODUCTION_DATE_NOT_REVIEWED",
            "COUNTRY_RISK_REFERENCE_MISSING",
        )
    ):
        state = EvidenceStatus.REVIEW_REQUIRED
    elif "TRACEABILITY_EVIDENCE_STALE" in unique_reasons:
        state = EvidenceStatus.STALE
    else:
        state = EvidenceStatus.COMPLETE
    return results, unique_reasons, state


def _origin_concentration(lots: tuple[TraceabilityLot, ...]) -> list[dict[str, str]]:
    totals = Counter(lot.origin_country.upper() for lot in lots)
    total = Decimal(len(lots))
    return [
        {
            "origin_country": country,
            "lot_count": str(count),
            "concentration": _decimal(Decimal(count) / total),
        }
        for country, count in sorted(totals.items())
    ]


def _financed_emissions_result(value: FinancedEmissionsInput) -> dict[str, object]:
    attribution = value.attribution_numerator / value.attribution_denominator
    scope_1 = value.borrower_scope_1 * attribution
    scope_2 = value.borrower_scope_2 * attribution
    scope_3 = value.borrower_scope_3 * attribution if value.borrower_scope_3 is not None else None
    total = scope_1 + scope_2 + (scope_3 or Decimal(0))
    return {
        "attribution_factor": _decimal(attribution),
        "scope_1": _decimal(scope_1),
        "scope_2": _decimal(scope_2),
        "scope_3": _decimal(scope_3) if scope_3 is not None else None,
        "total_available": _decimal(total),
        "data_quality_score": value.data_quality_score,
        "source_period": value.source_period,
        "estimation_method": value.estimation_method,
        "methodology_version": value.methodology_version,
        "restatement_lineage": value.restatement_lineage,
        "missing_data_warnings": [] if scope_3 is not None else ["SCOPE_3_UNAVAILABLE"],
    }


def _mapping(value: dict[str, object], field: str) -> dict[str, object]:
    result = value.get(field)
    if not isinstance(result, dict):
        raise ValueError(f"{field} must be an object")
    return result


def _rows(value: dict[str, object], field: str) -> tuple[dict[str, object], ...]:
    result = value.get(field)
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise ValueError(f"{field} must be an object array")
    return tuple(result)


def _string(value: dict[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{field} must be a non-empty string")
    return result


def _integer(value: dict[str, object], field: str) -> int:
    result = value.get(field)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError(f"{field} must be an integer")
    return result


def _traceability_lot(value: dict[str, object]) -> TraceabilityLot:
    geometry = _mapping(value, "geometry")
    geometry_type = _string(geometry, "type")
    crs = _string(geometry, "crs")
    raw_coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        if (
            not isinstance(raw_coordinates, list)
            or len(raw_coordinates) != 2
            or not all(isinstance(item, str) for item in raw_coordinates)
        ):
            raise ValueError("point geometry coordinates are malformed")
        parsed_geometry: GeographicPoint | GeographicPolygon = GeographicPoint(
            longitude=Decimal(raw_coordinates[0]), latitude=Decimal(raw_coordinates[1]), crs=crs
        )
    elif geometry_type == "Polygon":
        if not isinstance(raw_coordinates, list):
            raise ValueError("polygon geometry coordinates are malformed")
        coordinates = tuple(
            (Decimal(pair[0]), Decimal(pair[1]))
            for pair in raw_coordinates
            if isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(item, str) for item in pair)
        )
        if len(coordinates) != len(raw_coordinates):
            raise ValueError("polygon geometry coordinates are malformed")
        parsed_geometry = GeographicPolygon(coordinates=coordinates, crs=crs)
    else:
        raise ValueError("traceability geometry type is unsupported")
    graph = _mapping(value, "graph")
    nodes = tuple(
        EvidenceGraphNode(
            node_id=_string(item, "node_id"),
            node_type=EvidenceNodeType(_string(item, "node_type")),
            approved_fact_id=_string(item, "approved_fact_id"),
            approved_fact_digest=_string(item, "approved_fact_digest"),
            document_version_id=_string(item, "document_version_id"),
            document_byte_digest=_string(item, "document_byte_digest"),
        )
        for item in _rows(graph, "nodes")
    )
    edges = tuple(
        EvidenceGraphEdge(
            source_id=_string(item, "source_id"), target_id=_string(item, "target_id")
        )
        for item in _rows(graph, "edges")
    )
    production_date = value.get("production_date")
    if production_date is not None and not isinstance(production_date, str):
        raise ValueError("production date is malformed")
    evidence_recorded_at = datetime.fromisoformat(_string(value, "evidence_recorded_at"))
    return TraceabilityLot(
        lot_id=_string(value, "lot_id"),
        origin_country=_string(value, "origin_country"),
        geometry=parsed_geometry,
        production_date=(
            date.fromisoformat(production_date) if production_date is not None else None
        ),
        country_risk_reference=(
            _string(value, "country_risk_reference")
            if value.get("country_risk_reference") is not None
            else None
        ),
        evidence_document_digest=_string(value, "evidence_document_digest"),
        evidence_recorded_at=evidence_recorded_at,
        graph=EvidenceGraph(nodes=nodes, edges=edges),
    )
