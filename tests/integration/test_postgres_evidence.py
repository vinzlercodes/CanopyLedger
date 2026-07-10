"""PostgreSQL M2 evidence-store acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from canopyledger.application.evidence import EvidenceService
from canopyledger.persistence.postgres import PostgresEvidenceStore

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 9, 10, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def test_postgres_evidence_review_survives_service_recreation(database_engine: Engine) -> None:
    counters: dict[str, int] = {}

    def next_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}_0198a000-0000-7000-8000-{counters[prefix]:012d}"

    first = EvidenceService(
        store=PostgresEvidenceStore(database_engine),
        clock=lambda: NOW,
        id_factory=next_id,
    )
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
    first.record_warehouse_receipt(
        receipt_number="WR-1001",
        warehouse_id="wh_0198a000-0000-7000-8000-000000000001",
        lot_id="lot_0198a000-0000-7000-8000-000000000001",
        quantity="999.99999999",
        approved_fact_id=approved.fact_id,
    )
    first.record_ownership_claim(
        lot_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
        owner_party_id="pty_0198a000-0000-7000-8000-000000000001",
        pledgee_id="bnk_0198a000-0000-7000-8000-000000000001",
        approved_fact_id=approved.fact_id,
    )

    restarted = EvidenceService(
        store=PostgresEvidenceStore(database_engine),
        clock=lambda: NOW,
        id_factory=next_id,
    )
    packet = restarted.review_packet(candidate.fact_id)
    reconciliation = restarted.reconcile_lot_quantity(
        lot_id="lot_0198a000-0000-7000-8000-000000000001",
        expected_quantity="1000.00000000",
    )
    correction = restarted.create_candidate_fact(
        fact_type="warehouse_receipt",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
        value={"receipt_number": "WR-1001", "quantity": "1000.00000000"},
        document_version_id=document.resource_id,
        document_byte_digest=document.byte_digest,
        page_region="page=1;box=10,20,300,90",
        extraction_method="deterministic_template",
        extractor_version="warehouse-receipt-template-v2",
        raw_value="WR-1001 1000.00000000",
        normalized_value="WR-1001 1000.00000000",
    )
    replacement = restarted.supersede_approved_fact(
        approved.fact_id,
        candidate_fact_id=correction.fact_id,
        reviewer_id=ACTOR_ID,
    )
    corrected_packet = restarted.review_packet(correction.fact_id)
    reloaded_store = PostgresEvidenceStore(database_engine)

    assert packet.document == document
    assert packet.candidate == candidate
    assert packet.approval_history == (approved,)
    assert reconciliation.resource_id is not None
    assert reconciliation.issue.difference == "-0.00000001"
    reloaded_superseded = reloaded_store.get_approved_fact(approved.fact_id)
    reloaded_replacement = reloaded_store.get_approved_fact(replacement.fact_id)
    assert reloaded_superseded is not None
    assert reloaded_replacement is not None
    assert reloaded_superseded.superseded_by == replacement.fact_id
    assert reloaded_replacement == replacement
    assert tuple(fact.fact_id for fact in corrected_packet.approval_history) == (
        approved.fact_id,
        replacement.fact_id,
    )
    assert corrected_packet.supersession_chain == (
        f"{approved.fact_id} -> {replacement.fact_id}",
    )

    with pytest.raises(ValueError, match="receipt number"):
        restarted.record_warehouse_receipt(
            receipt_number="WR-1001",
            warehouse_id="wh_0198a000-0000-7000-8000-000000000001",
            lot_id="lot_0198a000-0000-7000-8000-000000000002",
            quantity="900.00000000",
            approved_fact_id=approved.fact_id,
        )

    with pytest.raises(ValueError, match="ownership"):
        restarted.record_ownership_claim(
            lot_id="lot_0198a000-0000-7000-8000-000000000001",
            period="2026-07",
            owner_party_id="pty_0198a000-0000-7000-8000-000000000002",
            pledgee_id="bnk_0198a000-0000-7000-8000-000000000001",
            approved_fact_id=approved.fact_id,
        )
