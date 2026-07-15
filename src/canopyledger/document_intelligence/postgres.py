"""PostgreSQL persistence adapter for immutable M7 extraction provenance."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from canopyledger.evidence.controls import EvidenceControlError
from canopyledger.persistence.schema import candidate_fact_extraction, document_extraction

from .engine import CandidateReconciliationIssue, DocumentIntelligenceError
from .service import DocumentExtraction, ExtractedCandidateProvenance


class PostgresDocumentIntelligenceStore:
    """Immutable run/provenance storage; approved-fact state remains in the M2 store."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_by_request_digest(self, request_digest: str) -> DocumentExtraction | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(document_extraction).where(
                    document_extraction.c.request_digest == request_digest
                )
            ).mappings().one_or_none()
        return None if row is None else self._extraction(row)

    def insert(self, extraction: DocumentExtraction) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(document_extraction).values(
                        resource_id=extraction.resource_id,
                        request_digest=extraction.request_digest,
                        document_version_id=extraction.document_version_id,
                        document_byte_digest=extraction.document_byte_digest,
                        status=extraction.status,
                        document_type=extraction.document_type,
                        classification_method=extraction.classification_method,
                        classifier_version=extraction.classifier_version,
                        extractor_version=extraction.extractor_version,
                        text_digest=extraction.text_digest,
                        reconciliation_issue=_issue_to_json(extraction.reconciliation_issue),
                        completed_at=extraction.completed_at,
                    )
                )
                if extraction.candidates:
                    connection.execute(
                        insert(candidate_fact_extraction),
                        [
                            {
                                "candidate_fact_id": item.candidate_fact_id,
                                "extraction_id": extraction.resource_id,
                                "confidence": item.confidence,
                            }
                            for item in extraction.candidates
                        ],
                    )
        except IntegrityError as exc:
            existing = self.find_by_request_digest(extraction.request_digest)
            if existing == extraction:
                return
            raise DocumentIntelligenceError(
                "document extraction already exists with different data"
            ) from exc

    def get(self, extraction_id: str) -> DocumentExtraction | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(document_extraction).where(
                    document_extraction.c.resource_id == extraction_id
                )
            ).mappings().one_or_none()
        return None if row is None else self._extraction(row)

    def get_candidate_provenance(
        self, candidate_fact_id: str
    ) -> ExtractedCandidateProvenance | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(candidate_fact_extraction).where(
                    candidate_fact_extraction.c.candidate_fact_id == candidate_fact_id
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        return ExtractedCandidateProvenance(
            candidate_fact_id=str(row["candidate_fact_id"]),
            extraction_id=str(row["extraction_id"]),
            confidence=str(row["confidence"]),
            approval_state="candidate",
        )

    def _extraction(self, row: RowMapping) -> DocumentExtraction:
        with self._engine.connect() as connection:
            candidate_rows = connection.execute(
                select(candidate_fact_extraction)
                .where(candidate_fact_extraction.c.extraction_id == row["resource_id"])
                .order_by(candidate_fact_extraction.c.candidate_fact_id)
            ).mappings().all()
        return DocumentExtraction(
            resource_id=str(row["resource_id"]),
            request_digest=str(row["request_digest"]),
            document_version_id=str(row["document_version_id"]),
            document_byte_digest=str(row["document_byte_digest"]),
            status=str(row["status"]),
            document_type=str(row["document_type"]),
            classification_method=str(row["classification_method"]),
            classifier_version=str(row["classifier_version"]),
            extractor_version=str(row["extractor_version"]),
            text_digest=str(row["text_digest"]),
            candidates=tuple(
                ExtractedCandidateProvenance(
                    candidate_fact_id=str(candidate["candidate_fact_id"]),
                    extraction_id=str(candidate["extraction_id"]),
                    confidence=str(candidate["confidence"]),
                    approval_state="candidate",
                )
                for candidate in candidate_rows
            ),
            reconciliation_issue=_issue_from_json(row["reconciliation_issue"]),
            completed_at=row["completed_at"],
        )


def _issue_to_json(issue: CandidateReconciliationIssue | None) -> dict[str, object] | None:
    if issue is None:
        return None
    return {
        "code": issue.code,
        "lot_id": issue.lot_id,
        "expected_quantity": issue.expected_quantity,
        "receipt_quantity": issue.receipt_quantity,
        "difference": issue.difference,
        "blocks_freeze": issue.blocks_freeze,
    }


def _issue_from_json(value: Any) -> CandidateReconciliationIssue | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EvidenceControlError("stored extraction reconciliation issue is invalid")
    return CandidateReconciliationIssue(
        code=str(value["code"]),
        lot_id=str(value["lot_id"]),
        expected_quantity=str(value["expected_quantity"]),
        receipt_quantity=str(value["receipt_quantity"]),
        difference=str(value["difference"]),
        blocks_freeze=bool(value["blocks_freeze"]),
    )
