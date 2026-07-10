"""M2 evidence controls for document lineage and reviewed facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from canopyledger.integrity.canonical import (
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)


class EvidenceControlError(ValueError):
    """Base error for evidence-control contract violations."""


class DuplicateWarehouseReceipt(EvidenceControlError):
    """Raised when one warehouse receipt identity maps to conflicting evidence."""


class ActiveApprovedFactConflict(EvidenceControlError):
    """Raised when approving a fact would create two active facts for one identity."""


class OwnershipConflict(EvidenceControlError):
    """Raised when ownership or pledge evidence conflicts for one lot and period."""


class SupersessionCycle(EvidenceControlError):
    """Raised when a fact correction would create a supersession cycle."""


class CriticalFactBlocked(EvidenceControlError):
    """Raised when required snapshot evidence lacks an active approved fact."""


@dataclass(frozen=True)
class DocumentVersion:
    """Immutable original document bytes metadata."""

    resource_id: str
    document_id: str
    version: int
    filename: str
    content_type: str
    byte_digest: str
    size_bytes: int
    created_by: str
    created_at: datetime

    @classmethod
    def from_bytes(
        cls,
        *,
        document_id: str,
        version: int,
        filename: str,
        content_type: str,
        content: bytes,
        created_by: str,
        created_at: datetime,
    ) -> DocumentVersion:
        if version < 1:
            raise EvidenceControlError("document version must be positive")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise EvidenceControlError("document timestamp must be timezone-aware")
        return cls(
            resource_id=f"{document_id.replace('doc_', 'dov_', 1)}_v{version}",
            document_id=document_id,
            version=version,
            filename=filename,
            content_type=content_type,
            byte_digest=_sha256(content),
            size_bytes=len(content),
            created_by=created_by,
            created_at=created_at,
        )


@dataclass(frozen=True)
class FactIdentity:
    """Semantic identity that admits at most one active approved fact."""

    fact_type: str
    subject_id: str
    period: str


@dataclass(frozen=True)
class CandidateFact:
    """Extracted fact that cannot satisfy critical snapshot requirements."""

    fact_id: str
    identity: FactIdentity
    value: dict[str, object]
    document_version_id: str
    document_byte_digest: str
    extracted_at: datetime
    page_region: str | None = None
    extraction_method: str | None = None
    extractor_version: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None


@dataclass(frozen=True)
class ApprovedFact:
    """Human-reviewed fact with immutable source lineage."""

    fact_id: str
    candidate_fact_id: str
    identity: FactIdentity
    value: dict[str, object]
    document_version_id: str
    document_byte_digest: str
    approved_by: str
    approved_at: datetime
    superseded_by: str | None = None

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None


@dataclass(frozen=True)
class RejectedFact:
    """Candidate fact rejected by human review."""

    fact_id: str
    candidate_fact_id: str
    identity: FactIdentity
    rejected_by: str
    rejected_at: datetime
    reason: str


@dataclass(frozen=True)
class WarehouseReceiptEvidence:
    """Approved warehouse receipt claim tied to a reviewed fact."""

    receipt_number: str
    warehouse_id: str
    lot_id: str
    quantity: str
    approved_fact_id: str

    @property
    def receipt_identity(self) -> tuple[str, str]:
        return (self.warehouse_id, self.receipt_number)


@dataclass(frozen=True)
class InventoryOwnershipClaim:
    """Approved ownership and pledge claim for an inventory lot and period."""

    lot_id: str
    period: str
    owner_party_id: str
    pledgee_id: str
    approved_fact_id: str

    @property
    def claim_identity(self) -> tuple[str, str]:
        return (self.lot_id, self.period)


@dataclass(frozen=True)
class QuantityReconciliationIssue:
    """Structured quantity mismatch between approved facts and receipt evidence."""

    lot_id: str
    expected_quantity: str
    receipt_quantity: str
    difference: str


class EvidenceRegistry:
    """In-memory M2 control surface used by domain tests and future persistence adapters."""

    def __init__(self) -> None:
        self._candidates: dict[str, CandidateFact] = {}
        self._approved: dict[str, ApprovedFact] = {}
        self._rejected: dict[str, RejectedFact] = {}
        self._receipts: dict[tuple[str, str], WarehouseReceiptEvidence] = {}
        self._ownership_claims: dict[tuple[str, str], InventoryOwnershipClaim] = {}

    def record_candidate_fact(self, candidate: CandidateFact) -> None:
        if candidate.fact_id in self._candidates:
            raise EvidenceControlError(f"candidate fact already exists: {candidate.fact_id}")
        self._candidates[candidate.fact_id] = candidate

    def approve_fact(
        self,
        candidate: CandidateFact,
        *,
        reviewer_id: str,
        reviewed_at: datetime,
    ) -> str:
        self._require_unreviewed_candidate(candidate.fact_id)
        self._require_no_active_fact(candidate.identity)
        self._record_or_reuse_candidate_fact(candidate)
        approved = _approved_from_candidate(candidate, reviewer_id, reviewed_at)
        self._approved[approved.fact_id] = approved
        return approved.fact_id

    def reject_fact(
        self,
        candidate: CandidateFact,
        *,
        reviewer_id: str,
        reviewed_at: datetime,
        reason: str,
    ) -> str:
        self._require_unreviewed_candidate(candidate.fact_id)
        self._record_or_reuse_candidate_fact(candidate)
        rejected = RejectedFact(
            fact_id=candidate.fact_id.replace("caf_", "rjf_", 1),
            candidate_fact_id=candidate.fact_id,
            identity=candidate.identity,
            rejected_by=reviewer_id,
            rejected_at=reviewed_at,
            reason=reason,
        )
        self._rejected[rejected.fact_id] = rejected
        return rejected.fact_id

    def supersede_fact(
        self,
        *,
        superseded_fact_id: str,
        candidate: CandidateFact,
        reviewer_id: str,
        reviewed_at: datetime,
    ) -> str:
        old = self._approved_fact(superseded_fact_id)
        if not old.is_active:
            raise EvidenceControlError("only active approved facts can be superseded")
        if candidate.identity != old.identity:
            raise EvidenceControlError("replacement fact identity must match superseded fact")
        self._require_unreviewed_candidate(candidate.fact_id)
        self._record_or_reuse_candidate_fact(candidate)
        replacement = _approved_from_candidate(candidate, reviewer_id, reviewed_at)
        self._approved[replacement.fact_id] = replacement
        self._approved[superseded_fact_id] = _replace_superseded_by(old, replacement.fact_id)
        return replacement.fact_id

    def supersede_existing_fact(
        self,
        *,
        superseded_fact_id: str,
        replacement_fact_id: str,
        reviewer_id: str,
        reviewed_at: datetime,
    ) -> None:
        del reviewer_id, reviewed_at
        superseded = self._approved_fact(superseded_fact_id)
        replacement = self._approved_fact(replacement_fact_id)
        if superseded.identity != replacement.identity:
            raise EvidenceControlError("replacement fact identity must match superseded fact")
        if self._would_create_cycle(superseded_fact_id, replacement_fact_id):
            raise SupersessionCycle("fact supersession must be acyclic")
        self._approved[superseded_fact_id] = _replace_superseded_by(
            superseded, replacement_fact_id
        )

    def record_warehouse_receipt(self, receipt: WarehouseReceiptEvidence) -> None:
        self._approved_fact(receipt.approved_fact_id)
        existing = self._receipts.get(receipt.receipt_identity)
        if existing is not None and existing != receipt:
            raise DuplicateWarehouseReceipt(
                "warehouse receipt number already has approved evidence"
            )
        self._receipts[receipt.receipt_identity] = receipt

    def candidate_fact(self, fact_id: str) -> CandidateFact:
        try:
            return self._candidates[fact_id]
        except KeyError as exc:
            raise EvidenceControlError(f"candidate fact not found: {fact_id}") from exc

    def approved_fact(self, fact_id: str) -> ApprovedFact:
        return self._approved_fact(fact_id)

    def record_ownership_claim(self, claim: InventoryOwnershipClaim) -> None:
        self._approved_fact(claim.approved_fact_id)
        existing = self._ownership_claims.get(claim.claim_identity)
        if existing is not None and existing != claim:
            raise OwnershipConflict("lot already has conflicting ownership or pledge evidence")
        self._ownership_claims[claim.claim_identity] = claim

    def reconcile_lot_quantity(
        self, *, lot_id: str, expected_quantity: str
    ) -> QuantityReconciliationIssue | None:
        expected = Decimal(expected_quantity)
        receipt_quantity = sum(
            (
                Decimal(receipt.quantity)
                for receipt in self._receipts.values()
                if receipt.lot_id == lot_id
            ),
            Decimal("0"),
        )
        if receipt_quantity == expected:
            return None
        return QuantityReconciliationIssue(
            lot_id=lot_id,
            expected_quantity=expected_quantity,
            receipt_quantity=_format_quantity(receipt_quantity),
            difference=_format_quantity(receipt_quantity - expected),
        )

    def snapshot_input_references_for_required_facts(
        self, identities: tuple[FactIdentity, ...]
    ) -> tuple[dict[str, object], ...]:
        references: list[dict[str, object]] = []
        for identity in identities:
            fact = self._active_fact_for(identity)
            if fact is None:
                raise CriticalFactBlocked(
                    f"critical fact requires active approved evidence: {identity.fact_type}"
                )
            references.append(
                {
                    "resource_type": "approved_fact",
                    "resource_id": fact.fact_id,
                    "digest": self.approved_fact_digest(fact.fact_id),
                    "approval_state": "approved",
                    "lineage": {
                        "candidate_fact_id": fact.candidate_fact_id,
                        "document_version_id": fact.document_version_id,
                        "document_byte_digest": fact.document_byte_digest,
                    },
                }
            )
        return tuple(references)

    def approved_fact_digest(self, fact_id: str) -> str:
        fact = self._approved_fact(fact_id)
        return approved_fact_digest(fact)

    def _approved_fact(self, fact_id: str) -> ApprovedFact:
        try:
            return self._approved[fact_id]
        except KeyError as exc:
            raise EvidenceControlError(f"approved fact not found: {fact_id}") from exc

    def _record_or_reuse_candidate_fact(self, candidate: CandidateFact) -> None:
        existing = self._candidates.get(candidate.fact_id)
        if existing is None:
            self._candidates[candidate.fact_id] = candidate
            return
        if existing != candidate:
            raise EvidenceControlError(
                f"candidate fact already exists with different content: {candidate.fact_id}"
            )

    def _require_unreviewed_candidate(self, candidate_fact_id: str) -> None:
        if any(fact.candidate_fact_id == candidate_fact_id for fact in self._approved.values()):
            raise EvidenceControlError("candidate fact is already approved")
        if any(fact.candidate_fact_id == candidate_fact_id for fact in self._rejected.values()):
            raise EvidenceControlError("candidate fact is already rejected")

    def _require_no_active_fact(self, identity: FactIdentity) -> None:
        if self._active_fact_for(identity) is not None:
            raise ActiveApprovedFactConflict(
                "active approved fact already exists for identity and period"
            )

    def _active_fact_for(self, identity: FactIdentity) -> ApprovedFact | None:
        for fact in self._approved.values():
            if fact.identity == identity and fact.is_active:
                return fact
        return None

    def _would_create_cycle(self, superseded_fact_id: str, replacement_fact_id: str) -> bool:
        current: str | None = replacement_fact_id
        while current is not None:
            if current == superseded_fact_id:
                return True
            current = self._approved_fact(current).superseded_by
        return False


def _approved_from_candidate(
    candidate: CandidateFact, reviewer_id: str, reviewed_at: datetime
) -> ApprovedFact:
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise EvidenceControlError("review timestamp must be timezone-aware")
    return ApprovedFact(
        fact_id=candidate.fact_id.replace("caf_", "apf_", 1),
        candidate_fact_id=candidate.fact_id,
        identity=candidate.identity,
        value=candidate.value,
        document_version_id=candidate.document_version_id,
        document_byte_digest=candidate.document_byte_digest,
        approved_by=reviewer_id,
        approved_at=reviewed_at,
    )


def _replace_superseded_by(fact: ApprovedFact, superseded_by: str) -> ApprovedFact:
    return ApprovedFact(
        fact_id=fact.fact_id,
        candidate_fact_id=fact.candidate_fact_id,
        identity=fact.identity,
        value=fact.value,
        document_version_id=fact.document_version_id,
        document_byte_digest=fact.document_byte_digest,
        approved_by=fact.approved_by,
        approved_at=fact.approved_at,
        superseded_by=superseded_by,
    )


def approved_fact_digest(fact: ApprovedFact) -> str:
    payload = {
        "fact_id": fact.fact_id,
        "candidate_fact_id": fact.candidate_fact_id,
        "identity": {
            "fact_type": fact.identity.fact_type,
            "subject_id": fact.identity.subject_id,
            "period": fact.identity.period,
        },
        "value": _stable_value(fact.value),
        "document_version_id": fact.document_version_id,
        "document_byte_digest": fact.document_byte_digest,
        "approved_by": fact.approved_by,
        "approved_at": canonical_timestamp(fact.approved_at),
        "superseded_by": fact.superseded_by,
    }
    return domain_digest("approved_fact", 1, canonical_json_bytes(payload))


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _stable_value(value: dict[str, object]) -> object:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _format_quantity(quantity: Decimal) -> str:
    return f"{quantity.quantize(Decimal('0.00000001')):.8f}"
