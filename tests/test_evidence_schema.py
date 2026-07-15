"""M2 evidence persistence schema contract tests."""

from __future__ import annotations

from canopyledger.persistence.schema import metadata

EXPECTED_EVIDENCE_TABLES = {
    "canopyledger.evidence_document",
    "canopyledger.evidence_document_version",
    "canopyledger.candidate_fact",
    "canopyledger.approved_fact",
    "canopyledger.rejected_fact",
    "canopyledger.warehouse_receipt_evidence",
    "canopyledger.inventory_ownership_claim",
    "canopyledger.quantity_reconciliation_issue",
}


def test_metadata_declares_m2_evidence_resource_schema() -> None:
    assert EXPECTED_EVIDENCE_TABLES.issubset(set(metadata.tables))


def test_document_version_schema_stores_original_bytes_and_digest() -> None:
    table = metadata.tables["canopyledger.evidence_document_version"]

    assert {"original_bytes", "byte_digest", "size_bytes"}.issubset(table.c.keys())
    assert not table.c.original_bytes.nullable
    assert not table.c.byte_digest.nullable


def test_approved_fact_schema_enforces_active_identity_uniqueness_and_lineage() -> None:
    table = metadata.tables["canopyledger.approved_fact"]

    assert {"candidate_fact_id", "document_version_id", "document_byte_digest"}.issubset(
        table.c.keys()
    )
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    } >= {"approved_fact_candidate", "approved_fact_document_version"}
    assert {index.name for index in table.indexes} >= {"one_active_approved_fact_per_identity"}
    superseded_fk = next(iter(table.c.superseded_by.foreign_keys))
    assert superseded_fk.deferrable
    assert superseded_fk.initially == "DEFERRED"


def test_receipt_and_ownership_controls_have_unique_identity_constraints() -> None:
    receipt = metadata.tables["canopyledger.warehouse_receipt_evidence"]
    ownership = metadata.tables["canopyledger.inventory_ownership_claim"]

    assert {
        constraint.name
        for constraint in receipt.constraints
        if constraint.name is not None
    } >= {"receipt_number_per_warehouse"}
    assert {
        constraint.name
        for constraint in ownership.constraints
        if constraint.name is not None
    } >= {"ownership_claim_identity"}


def test_m7_extraction_schema_keeps_candidate_provenance_immutable_and_separate() -> None:
    extraction = metadata.tables["canopyledger.document_extraction"]
    provenance = metadata.tables["canopyledger.candidate_fact_extraction"]

    assert {
        "request_digest",
        "document_version_id",
        "document_byte_digest",
        "classification_method",
        "extractor_version",
        "text_digest",
    }.issubset(extraction.c.keys())
    assert {"candidate_fact_id", "extraction_id", "confidence"}.issubset(provenance.c.keys())
    assert provenance.c.candidate_fact_id.primary_key
