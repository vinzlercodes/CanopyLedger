"""Evidence-graph and legal-interpretation evaluation without compliance assertions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from itertools import pairwise

from canopyledger.climate.geometry import GeographicPoint, GeographicPolygon


class EvidenceNodeType(StrEnum):
    INVENTORY_LOT = "inventory_lot"
    PURCHASE_CONTRACT = "purchase_contract"
    SUPPLIER = "supplier"
    PRODUCER = "producer"
    PRODUCTION_AREA = "production_area"
    PRODUCTION_PERIOD = "production_period"
    SHIPMENT = "shipment"
    WAREHOUSE_RECEIPT = "warehouse_receipt"
    MARKET_CHANNEL = "market_channel"
    DOCUMENT = "document"


class EvidenceStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    CONFLICTING = "conflicting"
    STALE = "stale"
    NOT_REVIEWED = "not_reviewed"
    REVIEW_REQUIRED = "review_required"


class ProductionDateClass(StrEnum):
    BEFORE_CUTOFF = "before_cutoff"
    ON_OR_AFTER_CUTOFF = "on_or_after_cutoff"
    NOT_REVIEWED = "not_reviewed"


@dataclass(frozen=True)
class LegalInterpretationPolicy:
    """The date/freshness interpretation pinned by the legal bundle, not live law."""

    bundle_version: str
    production_cutoff: date
    evidence_freshness_days: int
    country_risk_reference_version: str

    def __post_init__(self) -> None:
        if not self.bundle_version or not self.country_risk_reference_version:
            raise ValueError("legal interpretation policy versions are required")
        if self.evidence_freshness_days < 1:
            raise ValueError("evidence freshness must be positive")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "bundle_version": self.bundle_version,
            "production_cutoff": self.production_cutoff.isoformat(),
            "evidence_freshness_days": self.evidence_freshness_days,
            "country_risk_reference_version": self.country_risk_reference_version,
        }


@dataclass(frozen=True)
class EvidenceGraphNode:
    node_id: str
    node_type: EvidenceNodeType
    approved_fact_id: str
    approved_fact_digest: str
    document_version_id: str
    document_byte_digest: str

    def __post_init__(self) -> None:
        if not self.node_id or not self.approved_fact_id or not self.document_version_id:
            raise ValueError("evidence graph node identity and approved fact lineage are required")
        for digest, label in (
            (self.approved_fact_digest, "approved fact"),
            (self.document_byte_digest, "document byte"),
        ):
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError(f"evidence graph node {label} digest must be SHA-256")

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "approved_fact_id": self.approved_fact_id,
            "approved_fact_digest": self.approved_fact_digest,
            "document_version_id": self.document_version_id,
            "document_byte_digest": self.document_byte_digest,
        }


@dataclass(frozen=True)
class EvidenceGraphEdge:
    source_id: str
    target_id: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id or self.source_id == self.target_id:
            raise ValueError("evidence graph edge endpoints must be distinct and present")

    def to_canonical_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "target_id": self.target_id}


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: tuple[EvidenceGraphNode, ...]
    edges: tuple[EvidenceGraphEdge, ...]

    def __post_init__(self) -> None:
        identifiers = tuple(node.node_id for node in self.nodes)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence graph node identifiers must be unique")
        node_ids = set(identifiers)
        if any(
            edge.source_id not in node_ids or edge.target_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("evidence graph edge references an unknown node")
        identities = tuple((edge.source_id, edge.target_id) for edge in self.edges)
        if len(identities) != len(set(identities)):
            raise ValueError("evidence graph edges must be unique")

    def missing_chain_steps(self) -> tuple[str, ...]:
        required = tuple(EvidenceNodeType)
        by_kind = {
            kind: tuple(node.node_id for node in self.nodes if node.node_type is kind)
            for kind in required
        }
        missing = [kind.value for kind, values in by_kind.items() if not values]
        edge_set = {(edge.source_id, edge.target_id) for edge in self.edges}
        for source_kind, target_kind in pairwise(required):
            if by_kind[source_kind] and by_kind[target_kind] and not any(
                (source, target) in edge_set
                for source in by_kind[source_kind]
                for target in by_kind[target_kind]
            ):
                missing.append(f"{source_kind.value}_to_{target_kind.value}")
        return tuple(missing)

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "nodes": [
                node.to_canonical_dict()
                for node in sorted(self.nodes, key=lambda item: item.node_id)
            ],
            "edges": [
                edge.to_canonical_dict()
                for edge in sorted(self.edges, key=lambda item: (item.source_id, item.target_id))
            ],
        }


@dataclass(frozen=True)
class TraceabilityLot:
    lot_id: str
    origin_country: str
    geometry: GeographicPoint | GeographicPolygon
    production_date: date | None
    country_risk_reference: str | None
    evidence_document_digest: str
    evidence_recorded_at: datetime
    graph: EvidenceGraph

    def __post_init__(self) -> None:
        if not self.lot_id or len(self.origin_country) != 2 or not self.origin_country.isalpha():
            raise ValueError("traceability lot must include an ISO-like origin country")
        if (
            not self.evidence_document_digest.startswith("sha256:")
            or len(self.evidence_document_digest) != 71
        ):
            raise ValueError("traceability evidence requires a SHA-256 document digest")
        if (
            self.evidence_recorded_at.tzinfo is None
            or self.evidence_recorded_at.utcoffset() is None
        ):
            raise ValueError("traceability evidence timestamp must be timezone-aware")

    def production_date_class(self, policy: LegalInterpretationPolicy) -> ProductionDateClass:
        if self.production_date is None:
            return ProductionDateClass.NOT_REVIEWED
        if self.production_date < policy.production_cutoff:
            return ProductionDateClass.BEFORE_CUTOFF
        return ProductionDateClass.ON_OR_AFTER_CUTOFF

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "lot_id": self.lot_id,
            "origin_country": self.origin_country.upper(),
            "geometry": self.geometry.to_canonical_dict(),
            "production_date": self.production_date.isoformat() if self.production_date else None,
            "country_risk_reference": self.country_risk_reference,
            "evidence_document_digest": self.evidence_document_digest,
            "evidence_recorded_at": self.evidence_recorded_at.isoformat(),
            "graph": self.graph.to_canonical_dict(),
        }
