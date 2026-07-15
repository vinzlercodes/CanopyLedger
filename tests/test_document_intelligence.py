"""M7 document-intelligence behaviour contracts."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def test_known_warehouse_receipt_template_yields_candidate_only_provenance() -> None:
    from canopyledger.document_intelligence.engine import parse_document

    result = parse_document(
        filename="receipt-wr-77.txt",
        content_type="text/plain",
        content=(
            b"WAREHOUSE RECEIPT\n"
            b"Warehouse ID: wh_0198a000-0000-7000-8000-000000000701\n"
            b"Receipt Number: WR-77\n"
            b"Lot ID: lot_0198a000-0000-7000-8000-000000000701\n"
            b"As Of: 2026-07-15\n"
            b"Quantity: 125.50 bags\n"
        ),
    )

    assert result.classification.document_type == "warehouse_receipt"
    assert result.classification.method == "deterministic_template"
    assert result.pages[0].text.startswith("WAREHOUSE RECEIPT")
    assert {(candidate.fact_type, candidate.subject_id) for candidate in result.candidates} == {
        ("warehouse_receipt", "wh_0198a000-0000-7000-8000-000000000701"),
        ("inventory_quantity", "lot_0198a000-0000-7000-8000-000000000701"),
    }
    assert all(candidate.confidence == "1.0000" for candidate in result.candidates)
    assert all(candidate.page_region == "page:1" for candidate in result.candidates)
    assert all(candidate.approval_state == "candidate" for candidate in result.candidates)


def test_pdf_text_and_pipe_table_extraction_use_the_same_known_template() -> None:
    from canopyledger.document_intelligence.engine import parse_document

    pdf_text = (
        "WAREHOUSE RECEIPT\nWarehouse ID: wh_0198a000-0000-7000-8000-000000000702\n"
        "Receipt Number: WR-78\nLot ID: lot_0198a000-0000-7000-8000-000000000702\n"
        "As Of: 2026-07-15\nQuantity: 126 bags\n| lot | bags |\n| 702 | 126 |"
    )
    content = _pdf_with_text(pdf_text)

    result = parse_document(filename="wr-78.pdf", content_type="application/pdf", content=content)

    assert result.classification.document_type == "warehouse_receipt"
    assert result.pages[0].tables == ((("lot", "bags"), ("702", "126")),)
    assert len(result.candidates) == 2


@pytest.mark.parametrize(
    ("content_type", "content", "message"),
    [
        ("application/zip", b"PK\x03\x04archive", "archives are not accepted"),
        ("application/pdf", b"%PDF-1.4 /Encrypt 1 0 R %%EOF", "encrypted"),
        ("application/pdf", b"not-a-pdf", "signature"),
        ("text/plain", b"x" * (5 * 1024 * 1024 + 1), "size limit"),
    ],
)
def test_unsafe_or_malformed_documents_are_rejected_before_extraction(
    content_type: str, content: bytes, message: str
) -> None:
    from canopyledger.document_intelligence.engine import DocumentIntelligenceError, parse_document

    with pytest.raises(DocumentIntelligenceError, match=message):
        parse_document(filename="attack", content_type=content_type, content=content)


def test_candidate_reconciliation_is_advisory_and_never_approves_a_fact() -> None:
    from canopyledger.document_intelligence.engine import ExtractedCandidate, reconcile_candidates

    issue = reconcile_candidates(
        (
            ExtractedCandidate(
                "inventory_quantity",
                "lot-a",
                "2026-07-15",
                {"quantity": "120", "unit": "bags"},
                "page:1",
                "120 bags",
                "120 bags",
                "1.0000",
            ),
            ExtractedCandidate(
                "warehouse_receipt",
                "warehouse-a",
                "2026-07-15",
                {"lot_id": "lot-a", "quantity": "100", "unit": "bags"},
                "page:1",
                "WR-1",
                "WR-1",
                "1.0000",
            ),
        )
    )

    assert issue is not None
    assert issue.code == "CANDIDATE_QUANTITY_MISMATCH"
    assert issue.blocks_freeze is False


@pytest.mark.parametrize(
    ("heading", "document_type"),
    [
        ("WAREHOUSE RECEIPT", "warehouse_receipt"),
        ("INVENTORY STATEMENT", "inventory_statement"),
        ("PURCHASE CONTRACT", "purchase_contract"),
        ("SALES INVOICE", "sales_invoice"),
        ("RECEIVABLES AGING REPORT", "receivables_aging_report"),
        ("BORROWER FINANCIAL STATEMENT", "borrower_financial_statement"),
        ("INSURANCE CERTIFICATE", "insurance_certificate"),
        ("INSPECTION REPORT", "inspection_report"),
        ("ORIGIN AND TRACEABILITY DECLARATION", "origin_traceability_declaration"),
        ("HEDGE STATEMENT", "hedge_statement"),
        ("FACILITY NOTICE", "facility_notice"),
    ],
)
def test_supported_document_catalog_is_classified_deterministically(
    heading: str, document_type: str
) -> None:
    from canopyledger.document_intelligence.engine import parse_document

    result = parse_document(
        filename="catalog.txt", content_type="text/plain", content=(heading + "\n").encode()
    )

    assert result.classification.document_type == document_type


def test_sales_invoice_template_produces_a_candidate_receivable_not_an_approved_fact() -> None:
    from canopyledger.document_intelligence.engine import parse_document

    result = parse_document(
        filename="invoice.txt",
        content_type="text/plain",
        content=(
            b"SALES INVOICE\nInvoice Number: INV-10\n"
            b"Obligor ID: obl_0198a000-0000-7000-8000-000000000701\n"
            b"As Of: 2026-07-15\nAmount: 1200.50 USD\n"
        ),
    )

    assert result.candidates == (
        result.candidates[0],
    )
    candidate = result.candidates[0]
    assert candidate.fact_type == "receivable_amount"
    assert candidate.value == {"invoice_number": "INV-10", "amount": "1200.50", "currency": "USD"}
    assert candidate.approval_state == "candidate"


def test_optional_extractor_adapter_can_only_contribute_candidates() -> None:
    from canopyledger.document_intelligence.engine import (
        ExtractedCandidate,
        ExtractedPage,
        parse_document,
    )

    @dataclass(frozen=True)
    class FixtureAdapter:
        name: str = "fixture"
        version: str = "2026.07"

        def extract(self, pages: tuple[ExtractedPage, ...]) -> tuple[ExtractedCandidate, ...]:
            assert pages[0].text == "UNRECOGNIZED\n"
            return (
                ExtractedCandidate(
                    "facility_notice",
                    "fac-a",
                    "2026-07-15",
                    {"notice": "fixture"},
                    "page:1",
                    "fixture",
                    "fixture",
                    "0.7500",
                    "approved",
                ),
            )

    result = parse_document(
        filename="unknown.txt",
        content_type="text/plain",
        content=b"UNRECOGNIZED\n",
        extractor_adapter=FixtureAdapter(),
    )

    assert result.extraction_method == "optional_extractor:fixture"
    assert result.extractor_version == "2026.07"
    assert result.candidates[0].approval_state == "candidate"


def test_benchmark_reports_template_coverage_and_candidate_exactness() -> None:
    from canopyledger.document_intelligence.benchmark import (
        ExtractionBenchmarkCase,
        run_extraction_benchmark,
    )

    result = run_extraction_benchmark(
        (
            ExtractionBenchmarkCase(
                case_id="receipt",
                filename="receipt.txt",
                content_type="text/plain",
                content=(
                    b"WAREHOUSE RECEIPT\nWarehouse ID: wh-a\nReceipt Number: WR-1\n"
                    b"Lot ID: lot-a\nAs Of: 2026-07-15\nQuantity: 100 bags\n"
                ),
                expected_document_type="warehouse_receipt",
                expected_fact_types=("inventory_quantity", "warehouse_receipt"),
            ),
        )
    )

    assert result.case_count == 1
    assert result.classification_accuracy == "1.0000"
    assert result.candidate_exactness == "1.0000"
    assert result.failures == ()


def test_extraction_service_persists_replayable_candidate_provenance_without_approval() -> None:
    from canopyledger.application.evidence import EvidenceService, InMemoryEvidenceStore
    from canopyledger.document_intelligence.service import (
        DocumentIntelligenceService,
        InMemoryDocumentIntelligenceStore,
    )

    ids = iter((
        "doc_0198a000-0000-7000-8000-000000000703",
        "exr_0198a000-0000-7000-8000-000000000703",
        "caf_0198a000-0000-7000-8000-000000000703",
        "caf_0198a000-0000-7000-8000-000000000704",
    ))
    evidence = EvidenceService(
        store=InMemoryEvidenceStore(), clock=lambda: NOW, id_factory=lambda _: next(ids)
    )
    document = evidence.upload_document(
        filename="receipt.txt",
        content_type="text/plain",
        content=(b"WAREHOUSE RECEIPT\nWarehouse ID: wh-a\nReceipt Number: WR-9\n"
                 b"Lot ID: lot-a\nAs Of: 2026-07-15\nQuantity: 100 bags\n"),
        actor_id="usr_analyst",
    )
    service = DocumentIntelligenceService(
        evidence=evidence,
        store=InMemoryDocumentIntelligenceStore(),
        clock=lambda: NOW,
        id_factory=lambda _: next(ids),
    )

    first = service.extract(document.resource_id)
    replayed = service.extract(document.resource_id)

    assert first == replayed
    assert first.status == "completed"
    assert first.document_byte_digest == document.byte_digest
    assert len(first.candidates) == 2
    assert all(item.approval_state == "candidate" for item in first.candidates)
    assert all(item.confidence == "1.0000" for item in first.candidates)
    assert all(item.extraction_id == first.resource_id for item in first.candidates)


def test_extraction_api_returns_candidate_only_parser_provenance() -> None:
    from canopyledger.api.app import create_app

    client = TestClient(create_app(clock=lambda: NOW))
    headers = {"Authorization": "Bearer analyst-demo-token"}
    uploaded = client.post(
        "/api/v1/evidence/documents",
        headers=headers,
        json={
            "filename": "receipt.txt",
            "content_type": "text/plain",
            "content_base64": base64.b64encode(
                b"WAREHOUSE RECEIPT\nWarehouse ID: wh-a\nReceipt Number: WR-9\n"
                b"Lot ID: lot-a\nAs Of: 2026-07-15\nQuantity: 100 bags\n"
            ).decode(),
        },
    )
    assert uploaded.status_code == 201

    extracted = client.post(
        f"/api/v1/evidence/documents/{uploaded.json()['document_version_id']}/extractions",
        headers=headers,
    )

    assert extracted.status_code == 201, extracted.text
    body = extracted.json()
    assert body["status"] == "completed"
    assert body["document_type"] == "warehouse_receipt"
    assert body["classification_method"] == "deterministic_template"
    assert len(body["candidates"]) == 2
    assert all(candidate["approval_state"] == "candidate" for candidate in body["candidates"])
    assert all(candidate["confidence"] == "1.0000" for candidate in body["candidates"])
    reloaded = client.get(
        f"/api/v1/evidence/extractions/{body['extraction_id']}", headers=headers
    )
    assert reloaded.json() == body
    provenance = client.get(
        f"/api/v1/evidence/candidate-facts/{body['candidates'][0]['candidate_fact_id']}/extraction-provenance",
        headers=headers,
    )
    assert provenance.status_code == 200
    assert provenance.json()["extraction_id"] == body["extraction_id"]


def test_extraction_api_rejects_archive_bytes_with_a_stable_problem_code() -> None:
    from canopyledger.api.app import create_app

    client = TestClient(create_app(clock=lambda: NOW))
    headers = {"Authorization": "Bearer analyst-demo-token"}
    uploaded = client.post(
        "/api/v1/evidence/documents",
        headers=headers,
        json={
            "filename": "archive.zip",
            "content_type": "application/zip",
            "content_base64": base64.b64encode(b"PK\x03\x04untrusted").decode(),
        },
    )
    assert uploaded.status_code == 201

    response = client.post(
        f"/api/v1/evidence/documents/{uploaded.json()['document_version_id']}/extractions",
        headers=headers,
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DOCUMENT_PROCESSING_REJECTED"


def _pdf_with_text(value: str) -> bytes:
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    escaped = escaped.replace("\n", "\\n")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    )
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, object_value in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode())
        result.extend(object_value)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    result.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(result)
