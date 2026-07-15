"""PostgreSQL M7 extraction provenance and candidate-only acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from canopyledger.application.evidence import EvidenceService
from canopyledger.document_intelligence.postgres import PostgresDocumentIntelligenceStore
from canopyledger.document_intelligence.service import DocumentIntelligenceService
from canopyledger.persistence.postgres import PostgresEvidenceStore

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000007"


def test_m7_postgres_extraction_persists_candidate_only_provenance_immutably(
    database_engine: Engine,
) -> None:
    counters: dict[str, int] = {}

    def next_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}_0198a000-0000-7000-8000-0000000007{counters[prefix]:02d}"

    evidence = EvidenceService(
        store=PostgresEvidenceStore(database_engine),
        clock=lambda: NOW,
        id_factory=next_id,
    )
    document = evidence.upload_document(
        filename="warehouse-receipt.txt",
        content_type="text/plain",
        content=(
            b"WAREHOUSE RECEIPT\nWarehouse ID: wh-m7\nReceipt Number: WR-M7\n"
            b"Lot ID: lot-m7\nAs Of: 2026-07-15\nQuantity: 100 bags\n"
        ),
        actor_id=ACTOR_ID,
    )
    service = DocumentIntelligenceService(
        evidence=evidence,
        store=PostgresDocumentIntelligenceStore(database_engine),
        clock=lambda: NOW,
        id_factory=next_id,
    )

    extraction = service.extract(document.resource_id)
    replayed = service.extract(document.resource_id)

    assert extraction == replayed
    assert extraction.status == "completed"
    assert len(extraction.candidates) == 2
    assert all(item.approval_state == "candidate" for item in extraction.candidates)
    first_candidate = extraction.candidates[0]
    assert service.candidate_provenance(first_candidate.candidate_fact_id) == first_candidate

    with pytest.raises(DBAPIError), database_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE canopyledger.document_extraction "
                "SET status = 'tampered' WHERE resource_id = :resource_id"
            ),
            {"resource_id": extraction.resource_id},
        )
