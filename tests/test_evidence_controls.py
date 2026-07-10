"""M2 evidence-control acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from canopyledger.evidence.controls import (
    ActiveApprovedFactConflict,
    CandidateFact,
    CriticalFactBlocked,
    DocumentVersion,
    DuplicateWarehouseReceipt,
    EvidenceControlError,
    EvidenceRegistry,
    FactIdentity,
    InventoryOwnershipClaim,
    OwnershipConflict,
    QuantityReconciliationIssue,
    SupersessionCycle,
    WarehouseReceiptEvidence,
)

DOCUMENT_ID = "doc_018f72bc-0000-7000-8000-000000000001"
ACTOR_ID = "usr_018f72bc-0000-7000-8000-000000000001"
NOW = datetime(2026, 7, 9, 8, 0, tzinfo=UTC)


def test_original_document_version_digest_is_stable_over_raw_bytes() -> None:
    first = DocumentVersion.from_bytes(
        document_id=DOCUMENT_ID,
        version=1,
        filename="warehouse-receipt.pdf",
        content_type="application/pdf",
        content=b"%PDF receipt bytes\n",
        created_by=ACTOR_ID,
        created_at=NOW,
    )
    second = DocumentVersion.from_bytes(
        document_id=DOCUMENT_ID,
        version=1,
        filename="warehouse-receipt.pdf",
        content_type="application/pdf",
        content=b"%PDF receipt bytes\n",
        created_by=ACTOR_ID,
        created_at=NOW,
    )

    assert first.byte_digest == second.byte_digest
    assert first.size_bytes == 19
    assert first.resource_id == "dov_018f72bc-0000-7000-8000-000000000001_v1"


def test_duplicate_warehouse_receipt_number_is_rejected() -> None:
    registry = EvidenceRegistry()
    approved_fact_id = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=FactIdentity(
                fact_type="warehouse_receipt",
                subject_id="lot_018f72bc-0000-7000-8000-000000000001",
                period="2026-07",
            ),
            value={"receipt_number": "WR-1001"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    registry.record_warehouse_receipt(
        WarehouseReceiptEvidence(
            receipt_number="WR-1001",
            warehouse_id="wh_018f72bc-0000-7000-8000-000000000001",
            lot_id="lot_018f72bc-0000-7000-8000-000000000001",
            quantity="1250.00000000",
            approved_fact_id=approved_fact_id,
        )
    )

    with pytest.raises(DuplicateWarehouseReceipt):
        registry.record_warehouse_receipt(
            WarehouseReceiptEvidence(
                receipt_number="WR-1001",
                warehouse_id="wh_018f72bc-0000-7000-8000-000000000001",
                lot_id="lot_018f72bc-0000-7000-8000-000000000002",
                quantity="900.00000000",
                approved_fact_id=approved_fact_id,
            )
        )


def test_conflicting_ownership_and_pledge_evidence_is_rejected() -> None:
    registry = EvidenceRegistry()
    ownership_fact = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=FactIdentity(
                fact_type="ownership",
                subject_id="lot_018f72bc-0000-7000-8000-000000000001",
                period="2026-07",
            ),
            value={
                "owner_party_id": "pty_018f72bc-0000-7000-8000-000000000001",
                "pledgee_id": "bnk_018f72bc-0000-7000-8000-000000000001",
            },
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    registry.record_ownership_claim(
        InventoryOwnershipClaim(
            lot_id="lot_018f72bc-0000-7000-8000-000000000001",
            period="2026-07",
            owner_party_id="pty_018f72bc-0000-7000-8000-000000000001",
            pledgee_id="bnk_018f72bc-0000-7000-8000-000000000001",
            approved_fact_id=ownership_fact,
        )
    )

    with pytest.raises(OwnershipConflict):
        registry.record_ownership_claim(
            InventoryOwnershipClaim(
                lot_id="lot_018f72bc-0000-7000-8000-000000000001",
                period="2026-07",
                owner_party_id="pty_018f72bc-0000-7000-8000-000000000002",
                pledgee_id="bnk_018f72bc-0000-7000-8000-000000000001",
                approved_fact_id=ownership_fact,
            )
        )


def test_receipt_quantity_must_reconcile_to_approved_lot_quantity() -> None:
    registry = EvidenceRegistry()
    quantity_fact = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=FactIdentity(
                fact_type="inventory_quantity",
                subject_id="lot_018f72bc-0000-7000-8000-000000000001",
                period="2026-07",
            ),
            value={"quantity": "1000.00000000"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    registry.record_warehouse_receipt(
        WarehouseReceiptEvidence(
            receipt_number="WR-1001",
            warehouse_id="wh_018f72bc-0000-7000-8000-000000000001",
            lot_id="lot_018f72bc-0000-7000-8000-000000000001",
            quantity="999.99999999",
            approved_fact_id=quantity_fact,
        )
    )

    issue = registry.reconcile_lot_quantity(
        lot_id="lot_018f72bc-0000-7000-8000-000000000001",
        expected_quantity="1000.00000000",
    )

    assert issue == QuantityReconciliationIssue(
        lot_id="lot_018f72bc-0000-7000-8000-000000000001",
        expected_quantity="1000.00000000",
        receipt_quantity="999.99999999",
        difference="-0.00000001",
    )


def test_approved_fact_supersession_is_cycle_free() -> None:
    registry = EvidenceRegistry()
    identity = FactIdentity(
        fact_type="inventory_quantity",
        subject_id="lot_018f72bc-0000-7000-8000-000000000001",
        period="2026-07",
    )
    first = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=identity,
            value={"quantity": "1250.00000000"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    second = registry.supersede_fact(
        superseded_fact_id=first,
        candidate=CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000002",
            identity=identity,
            value={"quantity": "1240.00000000"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000002_v1",
            document_byte_digest="sha256:" + "2" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )

    with pytest.raises(SupersessionCycle):
        registry.supersede_existing_fact(
            superseded_fact_id=second,
            replacement_fact_id=first,
            reviewer_id=ACTOR_ID,
            reviewed_at=NOW,
        )


def test_superseding_correction_requires_unreviewed_candidate() -> None:
    registry = EvidenceRegistry()
    identity = FactIdentity(
        fact_type="inventory_quantity",
        subject_id="lot_018f72bc-0000-7000-8000-000000000001",
        period="2026-07",
    )
    first = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=identity,
            value={"quantity": "1250.00000000"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )
    rejected_candidate = CandidateFact(
        fact_id="caf_018f72bc-0000-7000-8000-000000000002",
        identity=identity,
        value={"quantity": "1240.00000000"},
        document_version_id="dov_018f72bc-0000-7000-8000-000000000002_v1",
        document_byte_digest="sha256:" + "2" * 64,
        extracted_at=NOW,
    )
    registry.reject_fact(
        rejected_candidate,
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
        reason="Quantity evidence illegible",
    )

    with pytest.raises(EvidenceControlError, match="already rejected"):
        registry.supersede_fact(
            superseded_fact_id=first,
            candidate=rejected_candidate,
            reviewer_id=ACTOR_ID,
            reviewed_at=NOW,
        )


def test_only_one_active_approved_fact_can_exist_per_identity_and_period() -> None:
    registry = EvidenceRegistry()
    identity = FactIdentity(
        fact_type="ownership",
        subject_id="lot_018f72bc-0000-7000-8000-000000000001",
        period="2026-07",
    )
    registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=identity,
            value={"owner_party_id": "pty_018f72bc-0000-7000-8000-000000000001"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )

    with pytest.raises(ActiveApprovedFactConflict):
        registry.approve_fact(
            CandidateFact(
                fact_id="caf_018f72bc-0000-7000-8000-000000000002",
                identity=identity,
                value={"owner_party_id": "pty_018f72bc-0000-7000-8000-000000000002"},
                document_version_id="dov_018f72bc-0000-7000-8000-000000000002_v1",
                document_byte_digest="sha256:" + "2" * 64,
                extracted_at=NOW,
            ),
            reviewer_id=ACTOR_ID,
            reviewed_at=NOW,
        )


def test_candidate_fact_cannot_satisfy_critical_snapshot_requirement() -> None:
    registry = EvidenceRegistry()
    identity = FactIdentity(
        fact_type="ownership",
        subject_id="lot_018f72bc-0000-7000-8000-000000000001",
        period="2026-07",
    )
    registry.record_candidate_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=identity,
            value={"owner_party_id": "pty_018f72bc-0000-7000-8000-000000000001"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        )
    )

    with pytest.raises(CriticalFactBlocked):
        registry.snapshot_input_references_for_required_facts((identity,))


def test_recorded_candidate_fact_can_be_approved_by_human_review() -> None:
    registry = EvidenceRegistry()
    candidate = CandidateFact(
        fact_id="caf_018f72bc-0000-7000-8000-000000000001",
        identity=FactIdentity(
            fact_type="warehouse_receipt",
            subject_id="lot_018f72bc-0000-7000-8000-000000000001",
            period="2026-07",
        ),
        value={"receipt_number": "WR-1001"},
        document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
        document_byte_digest="sha256:" + "1" * 64,
        extracted_at=NOW,
    )
    registry.record_candidate_fact(candidate)

    approved_fact_id = registry.approve_fact(candidate, reviewer_id=ACTOR_ID, reviewed_at=NOW)

    assert approved_fact_id == "apf_018f72bc-0000-7000-8000-000000000001"


def test_rejected_candidate_fact_cannot_later_be_approved() -> None:
    registry = EvidenceRegistry()
    candidate = CandidateFact(
        fact_id="caf_018f72bc-0000-7000-8000-000000000001",
        identity=FactIdentity(
            fact_type="warehouse_receipt",
            subject_id="lot_018f72bc-0000-7000-8000-000000000001",
            period="2026-07",
        ),
        value={"receipt_number": "WR-1001"},
        document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
        document_byte_digest="sha256:" + "1" * 64,
        extracted_at=NOW,
    )
    registry.reject_fact(
        candidate,
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
        reason="Receipt number is illegible",
    )

    with pytest.raises(EvidenceControlError, match="rejected"):
        registry.approve_fact(candidate, reviewer_id=ACTOR_ID, reviewed_at=NOW)


def test_approved_fact_lineage_can_satisfy_critical_snapshot_requirement() -> None:
    registry = EvidenceRegistry()
    identity = FactIdentity(
        fact_type="ownership",
        subject_id="lot_018f72bc-0000-7000-8000-000000000001",
        period="2026-07",
    )
    approved_fact_id = registry.approve_fact(
        CandidateFact(
            fact_id="caf_018f72bc-0000-7000-8000-000000000001",
            identity=identity,
            value={"owner_party_id": "pty_018f72bc-0000-7000-8000-000000000001"},
            document_version_id="dov_018f72bc-0000-7000-8000-000000000001_v1",
            document_byte_digest="sha256:" + "1" * 64,
            extracted_at=NOW,
        ),
        reviewer_id=ACTOR_ID,
        reviewed_at=NOW,
    )

    references = registry.snapshot_input_references_for_required_facts((identity,))

    assert references == (
        {
            "resource_type": "approved_fact",
            "resource_id": approved_fact_id,
            "digest": registry.approved_fact_digest(approved_fact_id),
            "approval_state": "approved",
            "lineage": {
                "candidate_fact_id": "caf_018f72bc-0000-7000-8000-000000000001",
                "document_version_id": "dov_018f72bc-0000-7000-8000-000000000001_v1",
                "document_byte_digest": "sha256:" + "1" * 64,
            },
        },
    )
