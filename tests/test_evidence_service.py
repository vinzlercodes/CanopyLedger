"""Evidence application service contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from canopyledger.application.evidence import (
    EvidenceService,
    EvidenceStore,
    InMemoryEvidenceStore,
)

NOW = datetime(2026, 7, 9, 10, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def next_id(prefix: str) -> str:
    counters[prefix] = counters.get(prefix, 0) + 1
    return f"{prefix}_0198a000-0000-7000-8000-{counters[prefix]:012d}"


counters: dict[str, int] = {}


def service(store: EvidenceStore) -> EvidenceService:
    return EvidenceService(store=store, clock=lambda: NOW, id_factory=next_id)


def test_reviewed_evidence_survives_service_recreation() -> None:
    counters.clear()
    store = InMemoryEvidenceStore()
    first = service(store)
    document = first.upload_document(
        filename="warehouse-receipt.pdf",
        content_type="application/pdf",
        content=b"%PDF receipt bytes\n",
        actor_id=ACTOR_ID,
    )
    candidate = first.create_candidate_fact(
        fact_type="warehouse_receipt",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
        value={"receipt_number": "WR-1001"},
        document_version_id=document.resource_id,
        document_byte_digest=document.byte_digest,
        page_region="page=1;box=10,20,300,80",
        extraction_method="deterministic_template",
        extractor_version="warehouse-receipt-template-v1",
        raw_value="WR-1001",
        normalized_value="WR-1001",
    )
    approved = first.approve_candidate_fact(candidate.fact_id, reviewer_id=ACTOR_ID)

    restarted = service(store)
    packet = restarted.review_packet(candidate.fact_id)

    assert packet.document == document
    assert packet.candidate == candidate
    assert packet.approval_history == (approved,)
    assert packet.supersession_chain == ()


def test_review_packet_surfaces_same_identity_conflict_history_and_supersession_chain() -> None:
    counters.clear()
    store = InMemoryEvidenceStore()
    evidence = service(store)
    document = evidence.upload_document(
        filename="ownership.pdf",
        content_type="application/pdf",
        content=b"ownership bytes\n",
        actor_id=ACTOR_ID,
    )
    first = evidence.create_candidate_fact(
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
        document_version_id=document.resource_id,
        document_byte_digest=document.byte_digest,
        page_region="page=1;box=10,20,300,80",
        extraction_method="deterministic_template",
        extractor_version="ownership-template-v1",
        raw_value="pty_0198a000-0000-7000-8000-000000000001",
        normalized_value="pty_0198a000-0000-7000-8000-000000000001",
    )
    approved = evidence.approve_candidate_fact(first.fact_id, reviewer_id=ACTOR_ID)
    correction = evidence.create_candidate_fact(
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000002"},
        document_version_id=document.resource_id,
        document_byte_digest=document.byte_digest,
        page_region="page=1;box=10,20,300,90",
        extraction_method="deterministic_template",
        extractor_version="ownership-template-v2",
        raw_value="pty_0198a000-0000-7000-8000-000000000002",
        normalized_value="pty_0198a000-0000-7000-8000-000000000002",
    )

    packet = evidence.review_packet(correction.fact_id)

    assert packet.approval_history == (approved,)
    assert packet.conflicts == (
        f"active approved fact already exists for identity and period: {approved.fact_id}",
    )

    replacement = evidence.supersede_approved_fact(
        approved.fact_id,
        candidate_fact_id=correction.fact_id,
        reviewer_id=ACTOR_ID,
    )
    updated = evidence.review_packet(correction.fact_id)

    assert tuple(fact.fact_id for fact in updated.approval_history) == (
        approved.fact_id,
        replacement.fact_id,
    )
    assert updated.approval_history[0].superseded_by == replacement.fact_id
    assert updated.conflicts == ()
    assert updated.supersession_chain == (f"{approved.fact_id} -> {replacement.fact_id}",)


def test_candidate_creation_requires_matching_document_byte_digest() -> None:
    counters.clear()
    evidence = service(InMemoryEvidenceStore())
    document = evidence.upload_document(
        filename="warehouse-receipt.pdf",
        content_type="application/pdf",
        content=b"%PDF receipt bytes\n",
        actor_id=ACTOR_ID,
    )

    with pytest.raises(ValueError, match="Document byte digest mismatch"):
        evidence.create_candidate_fact(
            fact_type="warehouse_receipt",
            subject_id="lot_0198a000-0000-7000-8000-000000000001",
            period="2026-07",
            value={"receipt_number": "WR-1001"},
            document_version_id=document.resource_id,
            document_byte_digest="sha256:" + "0" * 64,
            page_region="page=1;box=10,20,300,80",
            extraction_method="deterministic_template",
            extractor_version="warehouse-receipt-template-v1",
            raw_value="WR-1001",
            normalized_value="WR-1001",
        )
