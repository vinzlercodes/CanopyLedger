"""Application orchestration for M7 extraction runs.

This layer deliberately delegates candidate creation to :class:`EvidenceService`; it never calls an
approval operation and returns durable provenance for each generated candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from canopyledger.application.evidence import EvidenceService
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest

from .engine import (
    CandidateExtractorAdapter,
    CandidateReconciliationIssue,
    DocumentIntelligenceError,
    reconcile_candidates,
)


@dataclass(frozen=True)
class ExtractedCandidateProvenance:
    candidate_fact_id: str
    extraction_id: str
    confidence: str
    approval_state: str


@dataclass(frozen=True)
class DocumentExtraction:
    resource_id: str
    request_digest: str
    document_version_id: str
    document_byte_digest: str
    status: str
    document_type: str
    classification_method: str
    classifier_version: str
    extractor_version: str
    text_digest: str
    candidates: tuple[ExtractedCandidateProvenance, ...]
    reconciliation_issue: CandidateReconciliationIssue | None
    completed_at: datetime


class DocumentIntelligenceStore(Protocol):
    def find_by_request_digest(self, request_digest: str) -> DocumentExtraction | None: ...

    def insert(self, extraction: DocumentExtraction) -> None: ...

    def get(self, extraction_id: str) -> DocumentExtraction | None: ...

    def get_candidate_provenance(
        self, candidate_fact_id: str
    ) -> ExtractedCandidateProvenance | None: ...


class InMemoryDocumentIntelligenceStore:
    """Small deterministic store used by the local API factory and focused behaviour tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, DocumentExtraction] = {}
        self._by_request: dict[str, str] = {}
        self._candidate: dict[str, ExtractedCandidateProvenance] = {}

    def find_by_request_digest(self, request_digest: str) -> DocumentExtraction | None:
        extraction_id = self._by_request.get(request_digest)
        return None if extraction_id is None else self._by_id[extraction_id]

    def insert(self, extraction: DocumentExtraction) -> None:
        previous = self._by_id.get(extraction.resource_id)
        if previous is not None and previous != extraction:
            raise DocumentIntelligenceError(
                "document extraction ID already exists with different data"
            )
        prior_request = self._by_request.get(extraction.request_digest)
        if prior_request is not None and prior_request != extraction.resource_id:
            raise DocumentIntelligenceError("document extraction request already exists")
        self._by_id[extraction.resource_id] = extraction
        self._by_request[extraction.request_digest] = extraction.resource_id
        for candidate in extraction.candidates:
            self._candidate[candidate.candidate_fact_id] = candidate

    def get(self, extraction_id: str) -> DocumentExtraction | None:
        return self._by_id.get(extraction_id)

    def get_candidate_provenance(
        self, candidate_fact_id: str
    ) -> ExtractedCandidateProvenance | None:
        return self._candidate.get(candidate_fact_id)


class DocumentIntelligenceService:
    """Runs the pure parser against immutable bytes and records candidate-only provenance."""

    def __init__(
        self,
        *,
        evidence: EvidenceService,
        store: DocumentIntelligenceStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str],
        extractor_adapter: CandidateExtractorAdapter | None = None,
    ) -> None:
        self._evidence = evidence
        self._store = store
        self._clock = clock
        self._id_factory = id_factory
        self._extractor_adapter = extractor_adapter

    def extract(self, document_version_id: str) -> DocumentExtraction:
        document, content = self._evidence.original_document(document_version_id)
        request_digest = domain_digest(
            "document_extraction_request",
            1,
            canonical_json_bytes(
                {
                    "document_version_id": document.resource_id,
                    "document_byte_digest": document.byte_digest,
                    "parser_version": "m7-deterministic-v1",
                }
            ),
        )
        existing = self._store.find_by_request_digest(request_digest)
        if existing is not None:
            return existing

        from .engine import parse_document

        parsed = parse_document(
            filename=document.filename,
            content_type=document.content_type,
            content=content,
            extractor_adapter=self._extractor_adapter,
        )
        extraction_id = self._id_factory("exr")
        provenance: list[ExtractedCandidateProvenance] = []
        for extracted in parsed.candidates:
            candidate = self._evidence.create_candidate_fact(
                fact_type=extracted.fact_type,
                subject_id=extracted.subject_id,
                period=extracted.period,
                value=extracted.value,
                document_version_id=document.resource_id,
                document_byte_digest=document.byte_digest,
                page_region=extracted.page_region,
                extraction_method=parsed.extraction_method,
                extractor_version=parsed.extractor_version,
                raw_value=extracted.raw_value,
                normalized_value=extracted.normalized_value,
            )
            provenance.append(
                ExtractedCandidateProvenance(
                    candidate_fact_id=candidate.fact_id,
                    extraction_id=extraction_id,
                    confidence=extracted.confidence,
                    approval_state="candidate",
                )
            )
        completed_at = self._clock()
        extraction = DocumentExtraction(
            resource_id=extraction_id,
            request_digest=request_digest,
            document_version_id=document.resource_id,
            document_byte_digest=document.byte_digest,
            status="completed",
            document_type=parsed.classification.document_type,
            classification_method=parsed.classification.method,
            classifier_version=parsed.classification.classifier_version,
            extractor_version=parsed.extractor_version,
            text_digest=parsed.text_digest,
            candidates=tuple(provenance),
            reconciliation_issue=reconcile_candidates(parsed.candidates),
            completed_at=completed_at,
        )
        self._store.insert(extraction)
        return extraction

    def get(self, extraction_id: str) -> DocumentExtraction:
        extraction = self._store.get(extraction_id)
        if extraction is None:
            raise DocumentIntelligenceError("document extraction not found")
        return extraction

    def candidate_provenance(self, candidate_fact_id: str) -> ExtractedCandidateProvenance:
        provenance = self._store.get_candidate_provenance(candidate_fact_id)
        if provenance is None:
            raise DocumentIntelligenceError("candidate has no document extraction provenance")
        return provenance
