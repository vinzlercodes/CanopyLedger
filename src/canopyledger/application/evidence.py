"""Application service for M2 evidence review workflows."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from canopyledger.evidence.controls import (
    ApprovedFact,
    CandidateFact,
    DocumentVersion,
    DuplicateWarehouseReceipt,
    EvidenceControlError,
    FactIdentity,
    InventoryOwnershipClaim,
    OwnershipConflict,
    QuantityReconciliationIssue,
    RejectedFact,
    WarehouseReceiptEvidence,
    approved_fact_digest,
)


@dataclass(frozen=True)
class EvidenceReviewPacket:
    document: DocumentVersion
    candidate: CandidateFact
    conflicts: tuple[str, ...]
    approval_history: tuple[ApprovedFact, ...]
    rejection: RejectedFact | None
    supersession_chain: tuple[str, ...]


@dataclass(frozen=True)
class WarehouseReceiptRecord:
    resource_id: str
    receipt: WarehouseReceiptEvidence


@dataclass(frozen=True)
class OwnershipClaimRecord:
    resource_id: str
    claim: InventoryOwnershipClaim


@dataclass(frozen=True)
class QuantityReconciliationRecord:
    resource_id: str | None
    issue_state: str
    issue: QuantityReconciliationIssue
    detected_at: datetime


@dataclass(frozen=True)
class EvidenceSnapshotReference:
    resource_id: str
    digest: str


class EvidenceStore(Protocol):
    def insert_document_version(
        self, document: DocumentVersion, *, original_bytes: bytes
    ) -> None: ...

    def get_document_version(self, document_version_id: str) -> DocumentVersion | None: ...

    def get_document_original_bytes(self, document_version_id: str) -> bytes | None: ...

    def insert_candidate_fact(self, candidate: CandidateFact) -> None: ...

    def get_candidate_fact(self, candidate_fact_id: str) -> CandidateFact | None: ...

    def list_candidate_facts(self, *, limit: int) -> tuple[CandidateFact, ...]: ...

    def get_approved_fact_for_candidate(self, candidate_fact_id: str) -> ApprovedFact | None: ...

    def get_rejected_fact_for_candidate(self, candidate_fact_id: str) -> RejectedFact | None: ...

    def get_active_approved_fact(self, identity: FactIdentity) -> ApprovedFact | None: ...

    def get_approved_fact(self, approved_fact_id: str) -> ApprovedFact | None: ...

    def list_approved_facts_for_identity(
        self, identity: FactIdentity
    ) -> tuple[ApprovedFact, ...]: ...

    def insert_approved_fact(self, approved: ApprovedFact) -> None: ...

    def supersede_approved_fact(
        self, *, superseded: ApprovedFact, replacement: ApprovedFact
    ) -> None: ...

    def insert_rejected_fact(self, rejected: RejectedFact) -> None: ...

    def get_warehouse_receipt(
        self, *, warehouse_id: str, receipt_number: str
    ) -> WarehouseReceiptRecord | None: ...

    def insert_warehouse_receipt(
        self, *, resource_id: str, receipt: WarehouseReceiptEvidence
    ) -> None: ...

    def list_warehouse_receipts_for_lot(
        self, lot_id: str
    ) -> tuple[WarehouseReceiptRecord, ...]: ...

    def get_ownership_claim(self, *, lot_id: str, period: str) -> OwnershipClaimRecord | None: ...

    def insert_ownership_claim(
        self, *, resource_id: str, claim: InventoryOwnershipClaim
    ) -> None: ...

    def insert_quantity_reconciliation_issue(
        self,
        *,
        resource_id: str,
        issue: QuantityReconciliationIssue,
        detected_at: datetime,
    ) -> None: ...


class InMemoryEvidenceStore:
    """Simple evidence store used by the default local API factory and service tests."""

    def __init__(self) -> None:
        self._documents: dict[str, DocumentVersion] = {}
        self._document_bytes: dict[str, bytes] = {}
        self._candidates: dict[str, CandidateFact] = {}
        self._approved: dict[str, ApprovedFact] = {}
        self._rejected: dict[str, RejectedFact] = {}
        self._warehouse_receipts: dict[str, WarehouseReceiptRecord] = {}
        self._ownership_claims: dict[str, OwnershipClaimRecord] = {}
        self._quantity_issues: dict[str, QuantityReconciliationRecord] = {}

    def insert_document_version(self, document: DocumentVersion, *, original_bytes: bytes) -> None:
        existing = self._documents.get(document.resource_id)
        if existing is not None and (
            existing != document or self._document_bytes[document.resource_id] != original_bytes
        ):
            raise EvidenceControlError("document version already exists with different content")
        self._documents[document.resource_id] = document
        self._document_bytes[document.resource_id] = original_bytes

    def get_document_version(self, document_version_id: str) -> DocumentVersion | None:
        return self._documents.get(document_version_id)

    def get_document_original_bytes(self, document_version_id: str) -> bytes | None:
        return self._document_bytes.get(document_version_id)

    def insert_candidate_fact(self, candidate: CandidateFact) -> None:
        existing = self._candidates.get(candidate.fact_id)
        if existing is not None and existing != candidate:
            raise EvidenceControlError("candidate fact already exists with different content")
        self._candidates[candidate.fact_id] = candidate

    def get_candidate_fact(self, candidate_fact_id: str) -> CandidateFact | None:
        return self._candidates.get(candidate_fact_id)

    def list_candidate_facts(self, *, limit: int) -> tuple[CandidateFact, ...]:
        return tuple(
            sorted(
                self._candidates.values(),
                key=lambda candidate: (candidate.extracted_at, candidate.fact_id),
                reverse=True,
            )[:limit]
        )

    def get_approved_fact_for_candidate(self, candidate_fact_id: str) -> ApprovedFact | None:
        for fact in self._approved.values():
            if fact.candidate_fact_id == candidate_fact_id:
                return fact
        return None

    def get_rejected_fact_for_candidate(self, candidate_fact_id: str) -> RejectedFact | None:
        for fact in self._rejected.values():
            if fact.candidate_fact_id == candidate_fact_id:
                return fact
        return None

    def get_active_approved_fact(self, identity: FactIdentity) -> ApprovedFact | None:
        for fact in self._approved.values():
            if fact.identity == identity and fact.is_active:
                return fact
        return None

    def get_approved_fact(self, approved_fact_id: str) -> ApprovedFact | None:
        return self._approved.get(approved_fact_id)

    def list_approved_facts_for_identity(self, identity: FactIdentity) -> tuple[ApprovedFact, ...]:
        return tuple(
            sorted(
                (fact for fact in self._approved.values() if fact.identity == identity),
                key=lambda fact: (fact.approved_at, fact.fact_id),
            )
        )

    def insert_approved_fact(self, approved: ApprovedFact) -> None:
        existing = self._approved.get(approved.fact_id)
        if existing is not None and existing != approved:
            raise EvidenceControlError("approved fact already exists with different content")
        self._approved[approved.fact_id] = approved

    def supersede_approved_fact(
        self, *, superseded: ApprovedFact, replacement: ApprovedFact
    ) -> None:
        existing = self._approved.get(superseded.fact_id)
        if existing != superseded:
            raise EvidenceControlError("approved fact changed before supersession")
        if replacement.fact_id in self._approved:
            raise EvidenceControlError("replacement approved fact already exists")
        self._approved[superseded.fact_id] = _replace_superseded_by(superseded, replacement.fact_id)
        self._approved[replacement.fact_id] = replacement

    def insert_rejected_fact(self, rejected: RejectedFact) -> None:
        existing = self._rejected.get(rejected.fact_id)
        if existing is not None and existing != rejected:
            raise EvidenceControlError("rejected fact already exists with different content")
        self._rejected[rejected.fact_id] = rejected

    def get_warehouse_receipt(
        self, *, warehouse_id: str, receipt_number: str
    ) -> WarehouseReceiptRecord | None:
        for record in self._warehouse_receipts.values():
            if (
                record.receipt.warehouse_id == warehouse_id
                and record.receipt.receipt_number == receipt_number
            ):
                return record
        return None

    def insert_warehouse_receipt(
        self, *, resource_id: str, receipt: WarehouseReceiptEvidence
    ) -> None:
        existing = self._warehouse_receipts.get(resource_id)
        record = WarehouseReceiptRecord(resource_id=resource_id, receipt=receipt)
        if existing is not None and existing != record:
            raise EvidenceControlError("warehouse receipt evidence already exists")
        self._warehouse_receipts[resource_id] = record

    def list_warehouse_receipts_for_lot(self, lot_id: str) -> tuple[WarehouseReceiptRecord, ...]:
        return tuple(
            record
            for record in self._warehouse_receipts.values()
            if record.receipt.lot_id == lot_id
        )

    def get_ownership_claim(self, *, lot_id: str, period: str) -> OwnershipClaimRecord | None:
        for record in self._ownership_claims.values():
            if record.claim.lot_id == lot_id and record.claim.period == period:
                return record
        return None

    def insert_ownership_claim(self, *, resource_id: str, claim: InventoryOwnershipClaim) -> None:
        existing = self._ownership_claims.get(resource_id)
        record = OwnershipClaimRecord(resource_id=resource_id, claim=claim)
        if existing is not None and existing != record:
            raise EvidenceControlError("ownership claim already exists")
        self._ownership_claims[resource_id] = record

    def insert_quantity_reconciliation_issue(
        self,
        *,
        resource_id: str,
        issue: QuantityReconciliationIssue,
        detected_at: datetime,
    ) -> None:
        self._quantity_issues[resource_id] = QuantityReconciliationRecord(
            resource_id=resource_id,
            issue_state="open",
            issue=issue,
            detected_at=detected_at,
        )


class EvidenceService:
    """Coordinates document upload, candidate fact creation, and human review."""

    def __init__(
        self,
        *,
        store: EvidenceStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def upload_document(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        actor_id: str,
    ) -> DocumentVersion:
        document = DocumentVersion.from_bytes(
            document_id=self._id_factory("doc"),
            version=1,
            filename=filename,
            content_type=content_type,
            content=content,
            created_by=actor_id,
            created_at=self._clock(),
        )
        self._store.insert_document_version(document, original_bytes=content)
        return document

    def original_document(self, document_version_id: str) -> tuple[DocumentVersion, bytes]:
        """Return immutable source bytes only after verifying their recorded digest."""
        document = self._document(document_version_id)
        content = self._store.get_document_original_bytes(document_version_id)
        if content is None:
            raise EvidenceControlError("Document bytes not found")
        if f"sha256:{hashlib.sha256(content).hexdigest()}" != document.byte_digest:
            raise EvidenceControlError("Document bytes do not match the recorded digest")
        return document, content

    def create_candidate_fact(
        self,
        *,
        fact_type: str,
        subject_id: str,
        period: str,
        value: dict[str, object],
        document_version_id: str,
        document_byte_digest: str,
        page_region: str,
        extraction_method: str,
        extractor_version: str,
        raw_value: str,
        normalized_value: str,
    ) -> CandidateFact:
        document = self._store.get_document_version(document_version_id)
        if document is None:
            raise EvidenceControlError("Document version not found")
        if document.byte_digest != document_byte_digest:
            raise EvidenceControlError("Document byte digest mismatch")
        candidate = CandidateFact(
            fact_id=self._id_factory("caf"),
            identity=FactIdentity(fact_type=fact_type, subject_id=subject_id, period=period),
            value=value,
            document_version_id=document_version_id,
            document_byte_digest=document_byte_digest,
            extracted_at=self._clock(),
            page_region=page_region,
            extraction_method=extraction_method,
            extractor_version=extractor_version,
            raw_value=raw_value,
            normalized_value=normalized_value,
        )
        self._store.insert_candidate_fact(candidate)
        return candidate

    def review_packet(self, candidate_fact_id: str) -> EvidenceReviewPacket:
        candidate = self._candidate(candidate_fact_id)
        document = self._document(candidate.document_version_id)
        rejection = self._store.get_rejected_fact_for_candidate(candidate_fact_id)
        history = self._store.list_approved_facts_for_identity(candidate.identity)
        return EvidenceReviewPacket(
            document=document,
            candidate=candidate,
            conflicts=_review_conflicts(candidate_fact_id, history),
            approval_history=history,
            rejection=rejection,
            supersession_chain=_supersession_chain(history),
        )

    def review_queue(self, *, limit: int) -> tuple[EvidenceReviewPacket, ...]:
        if limit < 1 or limit > 100:
            raise EvidenceControlError("review queue limit must be between 1 and 100")
        return tuple(
            self.review_packet(candidate.fact_id)
            for candidate in self._store.list_candidate_facts(limit=limit)
            if self._store.get_approved_fact_for_candidate(candidate.fact_id) is None
            and self._store.get_rejected_fact_for_candidate(candidate.fact_id) is None
        )

    def approve_candidate_fact(self, candidate_fact_id: str, *, reviewer_id: str) -> ApprovedFact:
        candidate = self._candidate(candidate_fact_id)
        self._require_unreviewed(candidate_fact_id)
        if self._store.get_active_approved_fact(candidate.identity) is not None:
            raise EvidenceControlError(
                "active approved fact already exists for identity and period"
            )
        approved = ApprovedFact(
            fact_id=candidate.fact_id.replace("caf_", "apf_", 1),
            candidate_fact_id=candidate.fact_id,
            identity=candidate.identity,
            value=candidate.value,
            document_version_id=candidate.document_version_id,
            document_byte_digest=candidate.document_byte_digest,
            approved_by=reviewer_id,
            approved_at=self._clock(),
        )
        self._store.insert_approved_fact(approved)
        return approved

    def reject_candidate_fact(
        self, candidate_fact_id: str, *, reviewer_id: str, reason: str
    ) -> RejectedFact:
        candidate = self._candidate(candidate_fact_id)
        self._require_unreviewed(candidate_fact_id)
        rejected = RejectedFact(
            fact_id=candidate.fact_id.replace("caf_", "rjf_", 1),
            candidate_fact_id=candidate.fact_id,
            identity=candidate.identity,
            rejected_by=reviewer_id,
            rejected_at=self._clock(),
            reason=reason,
        )
        self._store.insert_rejected_fact(rejected)
        return rejected

    def supersede_approved_fact(
        self,
        approved_fact_id: str,
        *,
        candidate_fact_id: str,
        reviewer_id: str,
    ) -> ApprovedFact:
        superseded = self._approved_fact(approved_fact_id)
        if not superseded.is_active:
            raise EvidenceControlError("only active approved facts can be superseded")
        candidate = self._candidate(candidate_fact_id)
        self._require_unreviewed(candidate_fact_id)
        if candidate.identity != superseded.identity:
            raise EvidenceControlError("replacement fact identity must match superseded fact")
        replacement = ApprovedFact(
            fact_id=candidate.fact_id.replace("caf_", "apf_", 1),
            candidate_fact_id=candidate.fact_id,
            identity=candidate.identity,
            value=candidate.value,
            document_version_id=candidate.document_version_id,
            document_byte_digest=candidate.document_byte_digest,
            approved_by=reviewer_id,
            approved_at=self._clock(),
        )
        self._store.supersede_approved_fact(
            superseded=superseded,
            replacement=replacement,
        )
        return replacement

    def record_warehouse_receipt(
        self,
        *,
        receipt_number: str,
        warehouse_id: str,
        lot_id: str,
        quantity: str,
        approved_fact_id: str,
    ) -> WarehouseReceiptRecord:
        self._approved_fact(approved_fact_id)
        receipt = WarehouseReceiptEvidence(
            receipt_number=receipt_number,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity=quantity,
            approved_fact_id=approved_fact_id,
        )
        existing = self._store.get_warehouse_receipt(
            warehouse_id=warehouse_id,
            receipt_number=receipt_number,
        )
        if existing is not None:
            if existing.receipt == receipt:
                return existing
            raise DuplicateWarehouseReceipt(
                "warehouse receipt number already has approved evidence"
            )
        resource_id = self._id_factory("wre")
        self._store.insert_warehouse_receipt(resource_id=resource_id, receipt=receipt)
        return WarehouseReceiptRecord(resource_id=resource_id, receipt=receipt)

    def record_ownership_claim(
        self,
        *,
        lot_id: str,
        period: str,
        owner_party_id: str,
        pledgee_id: str,
        approved_fact_id: str,
    ) -> OwnershipClaimRecord:
        self._approved_fact(approved_fact_id)
        claim = InventoryOwnershipClaim(
            lot_id=lot_id,
            period=period,
            owner_party_id=owner_party_id,
            pledgee_id=pledgee_id,
            approved_fact_id=approved_fact_id,
        )
        existing = self._store.get_ownership_claim(lot_id=lot_id, period=period)
        if existing is not None:
            if existing.claim == claim:
                return existing
            raise OwnershipConflict("lot already has conflicting ownership or pledge evidence")
        resource_id = self._id_factory("ioc")
        self._store.insert_ownership_claim(resource_id=resource_id, claim=claim)
        return OwnershipClaimRecord(resource_id=resource_id, claim=claim)

    def reconcile_lot_quantity(
        self, *, lot_id: str, expected_quantity: str
    ) -> QuantityReconciliationRecord:
        receipt_quantity = sum(
            (
                Decimal(record.receipt.quantity)
                for record in self._store.list_warehouse_receipts_for_lot(lot_id)
            ),
            Decimal("0"),
        )
        expected = Decimal(expected_quantity)
        issue = QuantityReconciliationIssue(
            lot_id=lot_id,
            expected_quantity=expected_quantity,
            receipt_quantity=_format_quantity(receipt_quantity),
            difference=_format_quantity(receipt_quantity - expected),
        )
        if receipt_quantity == expected:
            return QuantityReconciliationRecord(
                resource_id=None,
                issue_state="matched",
                issue=issue,
                detected_at=self._clock(),
            )
        resource_id = self._id_factory("qri")
        detected_at = self._clock()
        self._store.insert_quantity_reconciliation_issue(
            resource_id=resource_id,
            issue=issue,
            detected_at=detected_at,
        )
        return QuantityReconciliationRecord(
            resource_id=resource_id,
            issue_state="open",
            issue=issue,
            detected_at=detected_at,
        )

    def active_approved_fact_digest(self, approved_fact_id: str) -> str:
        fact = self._approved_fact(approved_fact_id)
        if not fact.is_active:
            raise EvidenceControlError("Approved fact is superseded")
        return approved_fact_digest(fact)

    def active_approved_fact_reference(self, identity: FactIdentity) -> EvidenceSnapshotReference:
        fact = self._store.get_active_approved_fact(identity)
        if fact is None:
            raise EvidenceControlError(
                f"critical fact requires active approved evidence: {identity.fact_type}"
            )
        return EvidenceSnapshotReference(
            resource_id=fact.fact_id,
            digest=approved_fact_digest(fact),
        )

    def _candidate(self, candidate_fact_id: str) -> CandidateFact:
        candidate = self._store.get_candidate_fact(candidate_fact_id)
        if candidate is None:
            raise EvidenceControlError("Candidate fact not found")
        return candidate

    def _document(self, document_version_id: str) -> DocumentVersion:
        document = self._store.get_document_version(document_version_id)
        if document is None:
            raise EvidenceControlError("Document version not found")
        return document

    def _approved_fact(self, approved_fact_id: str) -> ApprovedFact:
        fact = self._store.get_approved_fact(approved_fact_id)
        if fact is None:
            raise EvidenceControlError("Approved fact not found")
        return fact

    def _require_unreviewed(self, candidate_fact_id: str) -> None:
        if self._store.get_approved_fact_for_candidate(candidate_fact_id) is not None:
            raise EvidenceControlError("candidate fact is already approved")
        if self._store.get_rejected_fact_for_candidate(candidate_fact_id) is not None:
            raise EvidenceControlError("candidate fact is already rejected")


def _format_quantity(quantity: Decimal) -> str:
    return f"{quantity.quantize(Decimal('0.00000001')):.8f}"


def _review_conflicts(
    candidate_fact_id: str,
    approved_facts: tuple[ApprovedFact, ...],
) -> tuple[str, ...]:
    return tuple(
        f"active approved fact already exists for identity and period: {fact.fact_id}"
        for fact in approved_facts
        if fact.is_active and fact.candidate_fact_id != candidate_fact_id
    )


def _supersession_chain(approved_facts: tuple[ApprovedFact, ...]) -> tuple[str, ...]:
    by_id = {fact.fact_id: fact for fact in approved_facts}
    replacement_ids = {
        fact.superseded_by for fact in approved_facts if fact.superseded_by is not None
    }
    chains: list[str] = []
    for fact in approved_facts:
        if fact.fact_id in replacement_ids or fact.superseded_by is None:
            continue
        ids = [fact.fact_id]
        current = fact
        while current.superseded_by is not None:
            ids.append(current.superseded_by)
            next_fact = by_id.get(current.superseded_by)
            if next_fact is None:
                break
            current = next_fact
        chains.append(" -> ".join(ids))
    return tuple(chains)


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
