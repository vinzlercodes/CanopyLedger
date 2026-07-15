"""Pure M7 parsing and template extraction.

The module accepts document bytes and returns untrusted candidate observations only. It has no
database, network, shell, or model dependencies; human review through the evidence service remains
the sole path to approved evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 100
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"\x1f\x8b", b"Rar!\x1a\x07")


class DocumentIntelligenceError(ValueError):
    """Raised when a document is unsafe or unsupported for deterministic extraction."""


@dataclass(frozen=True)
class DocumentClassification:
    document_type: str
    method: str
    classifier_version: str
    confidence: str


@dataclass(frozen=True)
class ExtractedPage:
    number: int
    text: str
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()


@dataclass(frozen=True)
class ExtractedCandidate:
    fact_type: str
    subject_id: str
    period: str
    value: dict[str, object]
    page_region: str
    raw_value: str
    normalized_value: str
    confidence: str
    approval_state: str = "candidate"


@dataclass(frozen=True)
class ParsedDocument:
    classification: DocumentClassification
    pages: tuple[ExtractedPage, ...]
    candidates: tuple[ExtractedCandidate, ...]
    text_digest: str
    parser_version: str = "m7-deterministic-v1"
    extraction_method: str = "schema_guided_text"
    extractor_version: str = "m7-deterministic-v1"


class CandidateExtractorAdapter(Protocol):
    """Optional BYO extractor boundary; adapters emit candidates only, never review state."""

    name: str
    version: str

    def extract(self, pages: tuple[ExtractedPage, ...]) -> tuple[ExtractedCandidate, ...]: ...


@dataclass(frozen=True)
class CandidateReconciliationIssue:
    code: str
    lot_id: str
    expected_quantity: str
    receipt_quantity: str
    difference: str
    blocks_freeze: bool = False


def parse_document(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    extractor_adapter: CandidateExtractorAdapter | None = None,
) -> ParsedDocument:
    """Classify and deterministically extract known text or PDF templates as candidate facts."""
    del filename
    _validate_document(content_type=content_type, content=content)
    pages = (
        (ExtractedPage(number=1, text=_plain_text(content), tables=()),)
        if content_type == "text/plain"
        else _pdf_pages(content)
    )
    pages = tuple(replace(page, tables=_pipe_tables(page.text)) for page in pages)
    text = "\n".join(page.text for page in pages)
    normalized = text.replace("\r\n", "\n")
    classification = _classify(normalized)
    candidates = _template_candidates(classification.document_type, normalized)
    extraction_method = classification.method
    extractor_version = "m7-deterministic-v1"
    if not candidates and extractor_adapter is not None:
        candidates = extractor_adapter.extract(pages)
        extraction_method = f"optional_extractor:{extractor_adapter.name}"
        extractor_version = extractor_adapter.version
    candidates = tuple(
        _candidate_only(replace(candidate, page_region=_candidate_page_region(candidate, pages)))
        for candidate in candidates
    )
    return ParsedDocument(
        classification=classification,
        pages=pages,
        candidates=candidates,
        text_digest=f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()}",
        extraction_method=extraction_method,
        extractor_version=extractor_version,
    )


def reconcile_candidates(
    candidates: tuple[ExtractedCandidate, ...],
) -> CandidateReconciliationIssue | None:
    """Return an advisory mismatch; candidate observations cannot block or satisfy a freeze."""
    inventory = next(
        (candidate for candidate in candidates if candidate.fact_type == "inventory_quantity"),
        None,
    )
    if inventory is None:
        return None
    expected = _quantity_value(inventory.value, "inventory quantity")
    receipts = tuple(
        candidate for candidate in candidates if candidate.fact_type == "warehouse_receipt"
    )
    if not receipts:
        return None
    receipt_quantity = sum(
        (_quantity_value(candidate.value, "warehouse receipt quantity") for candidate in receipts),
        Decimal("0"),
    )
    if receipt_quantity == expected:
        return None
    return CandidateReconciliationIssue(
        code="CANDIDATE_QUANTITY_MISMATCH",
        lot_id=inventory.subject_id,
        expected_quantity=_decimal_string(expected),
        receipt_quantity=_decimal_string(receipt_quantity),
        difference=_decimal_string(receipt_quantity - expected),
    )


def _validate_document(*, content_type: str, content: bytes) -> None:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentIntelligenceError("document exceeds the 5 MiB size limit")
    if not content:
        raise DocumentIntelligenceError("document is empty")
    if content.startswith(_ARCHIVE_SIGNATURES):
        raise DocumentIntelligenceError("archives are not accepted for document extraction")
    if content_type not in {"text/plain", "application/pdf"}:
        raise DocumentIntelligenceError("document content type is not supported")
    if content_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise DocumentIntelligenceError("PDF file signature is invalid")
        if b"/Encrypt" in content:
            raise DocumentIntelligenceError("encrypted PDFs are not supported")
        if b"%%EOF" not in content:
            raise DocumentIntelligenceError("PDF is malformed: missing EOF marker")
        page_count = len(re.findall(rb"/Type\s*/Page(?!s)", content))
        if page_count == 0:
            raise DocumentIntelligenceError("PDF is malformed: no pages found")
        if page_count > MAX_PDF_PAGES:
            raise DocumentIntelligenceError("PDF exceeds the 100-page limit")


def _plain_text(content: bytes) -> str:
    if b"\x00" in content:
        raise DocumentIntelligenceError("plain-text document contains prohibited binary data")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentIntelligenceError("plain-text document must be valid UTF-8") from exc


def _pdf_pages(content: bytes) -> tuple[ExtractedPage, ...]:
    """Extract bounded page text through pypdf without interpreting actions or embedded scripts."""
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise DocumentIntelligenceError("encrypted PDFs are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentIntelligenceError("PDF exceeds the 100-page limit")
        pages = tuple(
            ExtractedPage(number=index, text=page.extract_text(extraction_mode="plain") or "")
            for index, page in enumerate(reader.pages, start=1)
        )
    except PdfReadError as exc:
        raise DocumentIntelligenceError("PDF is malformed or cannot be parsed") from exc
    if not any(page.text.strip() for page in pages):
        raise DocumentIntelligenceError("PDF has no extractable text")
    return pages


def _classify(text: str) -> DocumentClassification:
    heading = text.lstrip().split("\n", 1)[0].strip().upper()
    document_type = _SUPPORTED_HEADINGS.get(heading)
    if document_type is not None:
        return DocumentClassification(
            document_type=document_type,
            method="deterministic_template",
            classifier_version="m7-classifier-v1",
            confidence="1.0000",
        )
    return DocumentClassification(
        document_type="unknown",
        method="schema_guided_text",
        classifier_version="m7-classifier-v1",
        confidence="0.0000",
    )


_SUPPORTED_HEADINGS = {
    "WAREHOUSE RECEIPT": "warehouse_receipt",
    "INVENTORY STATEMENT": "inventory_statement",
    "PURCHASE CONTRACT": "purchase_contract",
    "SALES INVOICE": "sales_invoice",
    "RECEIVABLES AGING REPORT": "receivables_aging_report",
    "BORROWER FINANCIAL STATEMENT": "borrower_financial_statement",
    "INSURANCE CERTIFICATE": "insurance_certificate",
    "INSPECTION REPORT": "inspection_report",
    "ORIGIN AND TRACEABILITY DECLARATION": "origin_traceability_declaration",
    "HEDGE STATEMENT": "hedge_statement",
    "FACILITY NOTICE": "facility_notice",
}


def _template_candidates(document_type: str, text: str) -> tuple[ExtractedCandidate, ...]:
    extractors = {
        "warehouse_receipt": _extract_warehouse_receipt,
        "inventory_statement": _extract_inventory_statement,
        "purchase_contract": _extract_purchase_contract,
        "sales_invoice": _extract_sales_invoice,
        "insurance_certificate": _extract_insurance_certificate,
    }
    extractor = extractors.get(document_type)
    if extractor is None:
        return ()
    try:
        return extractor(text)
    except DocumentIntelligenceError:
        return ()


def _extract_warehouse_receipt(text: str) -> tuple[ExtractedCandidate, ...]:
    fields = {name: _required_field(text, label) for name, label in {
        "warehouse_id": "Warehouse ID",
        "receipt_number": "Receipt Number",
        "lot_id": "Lot ID",
        "as_of": "As Of",
        "quantity": "Quantity",
    }.items()}
    quantity_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+([A-Za-z]+)", fields["quantity"])
    if quantity_match is None:
        raise DocumentIntelligenceError("warehouse receipt quantity must be '<number> <unit>'")
    quantity, unit = quantity_match.groups()
    receipt_value = {
        "receipt_number": fields["receipt_number"],
        "warehouse_id": fields["warehouse_id"],
        "lot_id": fields["lot_id"],
        "quantity": quantity,
        "unit": unit,
    }
    return (
        ExtractedCandidate(
            fact_type="warehouse_receipt",
            subject_id=fields["warehouse_id"],
            period=fields["as_of"],
            value=receipt_value,
            page_region="page:1",
            raw_value=fields["receipt_number"],
            normalized_value=fields["receipt_number"],
            confidence="1.0000",
        ),
        ExtractedCandidate(
            fact_type="inventory_quantity",
            subject_id=fields["lot_id"],
            period=fields["as_of"],
            value={"quantity": quantity, "unit": unit, "warehouse_id": fields["warehouse_id"]},
            page_region="page:1",
            raw_value=fields["quantity"],
            normalized_value=f"{quantity} {unit}",
            confidence="1.0000",
        ),
    )


def _extract_inventory_statement(text: str) -> tuple[ExtractedCandidate, ...]:
    fields = _fields(text, {"lot_id": "Lot ID", "as_of": "As Of", "quantity": "Quantity"})
    quantity, unit = _quantity_and_unit(fields["quantity"], "inventory statement")
    return (
        ExtractedCandidate(
            fact_type="inventory_quantity",
            subject_id=fields["lot_id"],
            period=fields["as_of"],
            value={"quantity": quantity, "unit": unit},
            page_region="page:1",
            raw_value=fields["quantity"],
            normalized_value=f"{quantity} {unit}",
            confidence="1.0000",
        ),
    )


def _extract_purchase_contract(text: str) -> tuple[ExtractedCandidate, ...]:
    fields = _fields(
        text,
        {
            "contract_number": "Contract Number",
            "counterparty_id": "Counterparty ID",
            "maturity": "Maturity",
            "quantity": "Quantity",
        },
    )
    quantity, unit = _quantity_and_unit(fields["quantity"], "purchase contract")
    return (
        ExtractedCandidate(
            fact_type="purchase_contract",
            subject_id=fields["counterparty_id"],
            period=fields["maturity"],
            value={
                "contract_number": fields["contract_number"],
                "quantity": quantity,
                "unit": unit,
            },
            page_region="page:1",
            raw_value=fields["contract_number"],
            normalized_value=fields["contract_number"],
            confidence="1.0000",
        ),
    )


def _extract_sales_invoice(text: str) -> tuple[ExtractedCandidate, ...]:
    fields = _fields(
        text,
        {
            "invoice_number": "Invoice Number",
            "obligor_id": "Obligor ID",
            "as_of": "As Of",
            "amount": "Amount",
        },
    )
    amount, currency = _amount_and_currency(fields["amount"], "sales invoice")
    return (
        ExtractedCandidate(
            fact_type="receivable_amount",
            subject_id=fields["obligor_id"],
            period=fields["as_of"],
            value={
                "invoice_number": fields["invoice_number"],
                "amount": amount,
                "currency": currency,
            },
            page_region="page:1",
            raw_value=fields["amount"],
            normalized_value=f"{amount} {currency}",
            confidence="1.0000",
        ),
    )


def _extract_insurance_certificate(text: str) -> tuple[ExtractedCandidate, ...]:
    fields = _fields(
        text,
        {"policy_number": "Policy Number", "insured_id": "Insured ID", "expires_on": "Expires On"},
    )
    return (
        ExtractedCandidate(
            fact_type="insurance_certificate",
            subject_id=fields["insured_id"],
            period=fields["expires_on"],
            value={"policy_number": fields["policy_number"], "expires_on": fields["expires_on"]},
            page_region="page:1",
            raw_value=fields["policy_number"],
            normalized_value=fields["policy_number"],
            confidence="1.0000",
        ),
    )


def _required_field(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if match is None:
        raise DocumentIntelligenceError(f"warehouse receipt template is missing '{label}'")
    return match.group(1)


def _fields(text: str, labels: dict[str, str]) -> dict[str, str]:
    return {name: _required_field(text, label) for name, label in labels.items()}


def _quantity_and_unit(value: str, document_name: str) -> tuple[str, str]:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+([A-Za-z]+)", value)
    if match is None:
        raise DocumentIntelligenceError(f"{document_name} quantity must be '<number> <unit>'")
    return (str(match.group(1)), str(match.group(2)))


def _amount_and_currency(value: str, document_name: str) -> tuple[str, str]:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+([A-Z]{3})", value)
    if match is None:
        raise DocumentIntelligenceError(f"{document_name} amount must be '<number> <currency>'")
    return (str(match.group(1)), str(match.group(2)))


def _pipe_tables(text: str) -> tuple[tuple[tuple[str, ...], ...], ...]:
    rows = tuple(
        tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        for line in text.splitlines()
        if line.count("|") >= 2
    )
    return (rows,) if rows else ()


def _quantity_value(value: dict[str, object], label: str) -> Decimal:
    raw = value.get("quantity")
    if not isinstance(raw, str):
        raise DocumentIntelligenceError(f"{label} has no decimal quantity")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise DocumentIntelligenceError(f"{label} has an invalid decimal quantity") from exc


def _decimal_string(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.00000001')):.8f}"


def _candidate_only(candidate: ExtractedCandidate) -> ExtractedCandidate:
    """Prevent optional adapters from claiming a review state outside the M2 human workflow."""
    return ExtractedCandidate(
        fact_type=candidate.fact_type,
        subject_id=candidate.subject_id,
        period=candidate.period,
        value=candidate.value,
        page_region=candidate.page_region,
        raw_value=candidate.raw_value,
        normalized_value=candidate.normalized_value,
        confidence=candidate.confidence,
        approval_state="candidate",
    )


def _candidate_page_region(
    candidate: ExtractedCandidate, pages: tuple[ExtractedPage, ...]
) -> str:
    for page in pages:
        if candidate.raw_value in page.text or candidate.normalized_value in page.text:
            return f"page:{page.number}"
    return candidate.page_region
