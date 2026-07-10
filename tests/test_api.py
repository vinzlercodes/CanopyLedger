"""API v1 contract tests for the first runnable vertical slice."""

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app
from canopyledger.integrity.bundles import BundleType, VersionBundle


def client() -> TestClient:
    return TestClient(create_app())


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer analyst-demo-token"}


def test_health_is_public() -> None:
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_facility_returns_resource_and_strong_etag() -> None:
    response = client().post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["id"].startswith("fac_")
    assert response.json()["version"] == 1
    assert response.headers["etag"].startswith('"facility:fac_')


def test_create_facility_replays_same_idempotent_response() -> None:
    api = client()
    headers = {**auth_headers(), "Idempotency-Key": "facility-create-0001"}
    body = {
        "legal_name": "Meridian Coffee Trading BV",
        "currency": "EUR",
        "facility_commitment": "50000000.00",
    }
    first = api.post("/api/v1/facilities", headers=headers, json=body)
    second = api.post("/api/v1/facilities", headers=headers, json=body)
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    assert second.headers["idempotency-replayed"] == "true"


def test_patch_requires_if_match() -> None:
    api = client()
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    response = api.patch(
        f"/api/v1/facilities/{created.json()['id']}",
        headers={**auth_headers(), "Idempotency-Key": "facility-update-0001"},
        json={"legal_name": "Meridian Coffee Trading B.V.", "reason": "Legal-name correction"},
    )
    assert response.status_code == 428
    assert response.json()["code"] == "PRECONDITION_REQUIRED"


def test_patch_rejects_stale_etag_and_accepts_current_etag() -> None:
    api = client()
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    path = f"/api/v1/facilities/{created.json()['id']}"
    body = {"legal_name": "Meridian Coffee Trading B.V.", "reason": "Legal-name correction"}
    stale = api.patch(
        path,
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-update-0001",
            "If-Match": '"facility:stale:v1:bad"',
        },
        json=body,
    )
    assert stale.status_code == 412

    updated = api.patch(
        path,
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-update-0002",
            "If-Match": created.headers["etag"],
        },
        json=body,
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.headers["etag"] != created.headers["etag"]


def test_freeze_creates_immutable_snapshot_manifest() -> None:
    api = client()
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    facility_id = created.json()["id"]
    response = api.post(
        f"/api/v1/facilities/{facility_id}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json={
            "as_of": "2026-06-21T17:00:00.000000Z",
            "market_bundle": {
                "resource_id": "mkt_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "a" * 64,
            },
            "policy_bundle": {
                "resource_id": "pol_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "b" * 64,
            },
            "legal_interpretation_bundle": {
                "resource_id": "leg_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "d" * 64,
            },
            "computation_bundle": {
                "resource_id": "cmp_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "c" * 64,
            },
            "inputs": [],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["snapshot_id"].startswith("snp_")
    assert response.json()["facility_working_version"] == 1
    assert response.json()["schema_version"] == "1.0"
    assert response.json()["digest"].startswith("sha256:")
    assert response.json()["created_by"].startswith("act_")
    assert response.json()["created_at"].endswith("Z")
    assert response.json()["legal_interpretation_bundle"]["digest"] == "sha256:" + "d" * 64

    fetched = api.get(
        f"/api/v1/snapshots/{response.json()['snapshot_id']}/manifest",
        headers=auth_headers(),
    )
    assert fetched.status_code == 200
    assert fetched.json() == response.json()


def test_freeze_rejects_candidate_fact_snapshot_input_as_problem_response() -> None:
    api = client()
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    facility_id = created.json()["id"]

    response = api.post(
        f"/api/v1/facilities/{facility_id}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json={
            "as_of": "2026-06-21T17:00:00.000000Z",
            "market_bundle": {
                "resource_id": "mkt_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "a" * 64,
            },
            "policy_bundle": {
                "resource_id": "pol_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "b" * 64,
            },
            "legal_interpretation_bundle": {
                "resource_id": "leg_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "d" * 64,
            },
            "computation_bundle": {
                "resource_id": "cmp_0198a000-0000-7000-8000-000000000001",
                "digest": "sha256:" + "c" * 64,
            },
            "inputs": [
                {
                    "resource_type": "candidate_fact",
                    "resource_id": "caf_0198a000-0000-7000-8000-000000000001",
                    "digest": "sha256:" + "1" * 64,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert "Candidate evidence cannot" in response.json()["detail"]


def test_freeze_rejects_unapproved_fact_snapshot_input() -> None:
    api = client()
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )

    response = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(
            inputs=[
                {
                    "resource_type": "approved_fact",
                    "resource_id": "apf_0198a000-0000-7000-8000-000000000999",
                    "digest": "sha256:" + "1" * 64,
                }
            ]
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert "Approved fact not found" in response.json()["detail"]


def test_freeze_rejects_approved_fact_snapshot_input_digest_mismatch() -> None:
    api = client()
    approved = _approved_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
    )
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )

    response = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(
            inputs=[
                {
                    "resource_type": "approved_fact",
                    "resource_id": approved["approved_fact_id"],
                    "digest": "sha256:" + "0" * 64,
                }
            ]
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert "digest mismatch" in response.json()["detail"]


def test_freeze_accepts_active_approved_fact_snapshot_input() -> None:
    api = client()
    approved = _approved_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
    )
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )

    response = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(
            inputs=[
                {
                    "resource_type": "approved_fact",
                    "resource_id": approved["approved_fact_id"],
                    "digest": approved["digest"],
                }
            ]
        ),
    )

    assert response.status_code == 201, response.text
    assert response.json()["inputs"] == [
        {
            "resource_type": "approved_fact",
            "resource_id": approved["approved_fact_id"],
            "digest": approved["digest"],
        }
    ]


def test_freeze_blocks_policy_required_critical_fact_without_active_approval() -> None:
    policy = _policy_bundle_with_required_fact(
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
    )
    api = TestClient(create_app(policy_bundle_loader=_single_policy_loader(policy)))
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )

    response = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(inputs=[], policy_bundle=policy.reference.model_dump()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert "critical fact requires active approved evidence: ownership" in response.json()[
        "detail"
    ]


def test_freeze_expands_policy_required_critical_fact_input_from_active_approval() -> None:
    policy = _policy_bundle_with_required_fact(
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        period="2026-07",
    )
    api = TestClient(create_app(policy_bundle_loader=_single_policy_loader(policy)))
    approved = _approved_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
    )
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )

    response = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(inputs=[], policy_bundle=policy.reference.model_dump()),
    )

    assert response.status_code == 201, response.text
    assert response.json()["inputs"] == [
        {
            "resource_type": "approved_fact",
            "resource_id": approved["approved_fact_id"],
            "digest": approved["digest"],
        }
    ]


def test_evidence_superseding_correction_api_replaces_active_fact() -> None:
    api = client()
    first = _approved_fact(
        api,
        fact_type="inventory_quantity",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"quantity": "1250.00000000"},
    )
    correction = _candidate_fact(
        api,
        fact_type="inventory_quantity",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"quantity": "1240.00000000"},
    )

    replacement = api.post(
        f"/api/v1/evidence/approved-facts/{first['approved_fact_id']}/supersede",
        headers=auth_headers(),
        json={"candidate_fact_id": correction["candidate_fact_id"]},
    )

    assert replacement.status_code == 201, replacement.text
    replacement_body = replacement.json()
    assert replacement_body["approved_fact_id"].startswith("apf_")
    assert replacement_body["approved_fact_id"] != first["approved_fact_id"]
    assert replacement_body["approval_state"] == "approved"
    assert replacement_body["lineage"]["candidate_fact_id"] == correction["candidate_fact_id"]

    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "facility-create-0001"},
        json={
            "legal_name": "Meridian Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "50000000.00",
        },
    )
    old_fact = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0001",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(
            inputs=[
                {
                    "resource_type": "approved_fact",
                    "resource_id": first["approved_fact_id"],
                    "digest": first["digest"],
                }
            ]
        ),
    )
    assert old_fact.status_code == 422
    assert "superseded" in old_fact.json()["detail"]

    current_fact = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
        headers={
            **auth_headers(),
            "Idempotency-Key": "facility-freeze-0002",
            "If-Match": created.headers["etag"],
        },
        json=_snapshot_body(
            inputs=[
                {
                    "resource_type": "approved_fact",
                    "resource_id": replacement_body["approved_fact_id"],
                    "digest": replacement_body["digest"],
                }
            ]
        ),
    )
    assert current_fact.status_code == 201, current_fact.text


def test_evidence_superseding_correction_rejects_identity_mismatch() -> None:
    api = client()
    first = _approved_fact(
        api,
        fact_type="inventory_quantity",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"quantity": "1250.00000000"},
    )
    correction = _candidate_fact(
        api,
        fact_type="inventory_quantity",
        subject_id="lot_0198a000-0000-7000-8000-000000000002",
        value={"quantity": "1240.00000000"},
    )

    response = api.post(
        f"/api/v1/evidence/approved-facts/{first['approved_fact_id']}/supersede",
        headers=auth_headers(),
        json={"candidate_fact_id": correction["candidate_fact_id"]},
    )

    assert response.status_code == 422
    assert "identity" in response.json()["detail"]


def test_evidence_document_candidate_review_and_approval_flow() -> None:
    api = client()
    document = api.post(
        "/api/v1/evidence/documents",
        headers=auth_headers(),
        json={
            "filename": "warehouse-receipt.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF receipt bytes\n").decode(),
        },
    )
    assert document.status_code == 201, document.text
    document_body = document.json()
    assert document_body["document_id"].startswith("doc_")
    assert document_body["document_version_id"].startswith("dov_")
    assert document_body["version"] == 1
    assert document_body["byte_digest"].startswith("sha256:")
    assert document_body["size_bytes"] == 19

    candidate = api.post(
        "/api/v1/evidence/candidate-facts",
        headers=auth_headers(),
        json={
            "fact_type": "warehouse_receipt",
            "subject_id": "lot_0198a000-0000-7000-8000-000000000001",
            "period": "2026-07",
            "value": {"receipt_number": "WR-1001"},
            "document_version_id": document_body["document_version_id"],
            "document_byte_digest": document_body["byte_digest"],
            "page_region": "page=1;box=10,20,300,80",
            "extraction_method": "deterministic_template",
            "extractor_version": "warehouse-receipt-template-v1",
            "raw_value": "WR-1001",
            "normalized_value": "WR-1001",
        },
    )
    assert candidate.status_code == 201, candidate.text
    candidate_body = candidate.json()
    assert candidate_body["candidate_fact_id"].startswith("caf_")
    assert candidate_body["approval_state"] == "candidate"
    assert candidate_body["lineage"]["document_version_id"] == document_body["document_version_id"]
    assert candidate_body["lineage"]["document_byte_digest"] == document_body["byte_digest"]

    review = api.get(
        f"/api/v1/evidence/candidate-facts/{candidate_body['candidate_fact_id']}/review",
        headers=auth_headers(),
    )
    assert review.status_code == 200, review.text
    review_body = review.json()
    assert review_body["document"]["filename"] == "warehouse-receipt.pdf"
    assert review_body["candidate_fact"]["page_region"] == "page=1;box=10,20,300,80"
    assert review_body["conflicts"] == []
    assert review_body["approval_history"] == []
    assert review_body["supersession_chain"] == []

    approved = api.post(
        f"/api/v1/evidence/candidate-facts/{candidate_body['candidate_fact_id']}/approve",
        headers=auth_headers(),
        json={},
    )
    assert approved.status_code == 201, approved.text
    approved_body = approved.json()
    assert approved_body["approved_fact_id"].startswith("apf_")
    assert approved_body["approval_state"] == "approved"
    assert approved_body["lineage"] == candidate_body["lineage"]
    assert approved_body["digest"].startswith("sha256:")


def test_evidence_review_page_renders_human_review_controls() -> None:
    api = client()
    candidate = _candidate_fact(
        api,
        fact_type="warehouse_receipt",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"receipt_number": "WR-1001"},
    )

    response = api.get(
        f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/review-page",
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "warehouse_receipt.pdf" in response.text
    assert str(candidate["candidate_fact_id"]) in response.text
    assert "page=1;box=10,20,300,80" in response.text
    assert "WR-1001" in response.text
    assert "Conflicts" in response.text
    assert "Approval History" in response.text
    assert "Supersession Chain" in response.text
    approve_path = f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/approve"
    reject_path = f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/reject"
    assert approve_path in response.text
    assert reject_path in response.text
    assert "approveCandidateFact" in response.text
    assert "rejectCandidateFact" in response.text


def test_evidence_review_api_surfaces_active_fact_conflict_history() -> None:
    api = client()
    approved = _approved_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
    )
    candidate = _candidate_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"owner_party_id": "pty_0198a000-0000-7000-8000-000000000002"},
    )

    response = api.get(
        f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/review",
        headers=auth_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["approval_history"][0]["approved_fact_id"] == approved[
        "approved_fact_id"
    ]
    assert response.json()["conflicts"] == [
        "active approved fact already exists for identity and period: "
        f"{approved['approved_fact_id']}"
    ]


def test_evidence_candidate_rejection_blocks_later_approval() -> None:
    api = client()
    document = api.post(
        "/api/v1/evidence/documents",
        headers=auth_headers(),
        json={
            "filename": "warehouse-receipt.pdf",
            "content_type": "application/pdf",
            "content_base64": base64.b64encode(b"%PDF receipt bytes\n").decode(),
        },
    ).json()
    candidate = api.post(
        "/api/v1/evidence/candidate-facts",
        headers=auth_headers(),
        json={
            "fact_type": "warehouse_receipt",
            "subject_id": "lot_0198a000-0000-7000-8000-000000000001",
            "period": "2026-07",
            "value": {"receipt_number": "WR-1001"},
            "document_version_id": document["document_version_id"],
            "document_byte_digest": document["byte_digest"],
            "page_region": "page=1;box=10,20,300,80",
            "extraction_method": "deterministic_template",
            "extractor_version": "warehouse-receipt-template-v1",
            "raw_value": "WR-1001",
            "normalized_value": "WR-1001",
        },
    ).json()

    rejected = api.post(
        f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/reject",
        headers=auth_headers(),
        json={"reason": "Receipt number is illegible"},
    )

    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["approval_state"] == "rejected"
    assert rejected.json()["candidate_fact_id"] == candidate["candidate_fact_id"]

    approved = api.post(
        f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/approve",
        headers=auth_headers(),
        json={},
    )
    assert approved.status_code == 422
    assert "rejected" in approved.json()["detail"]


def test_evidence_receipt_ownership_and_reconciliation_api_controls() -> None:
    api = client()
    approved_receipt = _approved_fact(
        api,
        fact_type="warehouse_receipt",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={"receipt_number": "WR-1001", "quantity": "1000.00000000"},
    )
    receipt = api.post(
        "/api/v1/evidence/warehouse-receipts",
        headers=auth_headers(),
        json={
            "receipt_number": "WR-1001",
            "warehouse_id": "wh_0198a000-0000-7000-8000-000000000001",
            "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
            "quantity": "999.99999999",
            "approved_fact_id": approved_receipt["approved_fact_id"],
        },
    )
    assert receipt.status_code == 201, receipt.text
    receipt_body = receipt.json()
    assert receipt_body["receipt_evidence_id"].startswith("wre_")
    assert receipt_body["receipt_number"] == "WR-1001"

    duplicate = api.post(
        "/api/v1/evidence/warehouse-receipts",
        headers=auth_headers(),
        json={
            "receipt_number": "WR-1001",
            "warehouse_id": "wh_0198a000-0000-7000-8000-000000000001",
            "lot_id": "lot_0198a000-0000-7000-8000-000000000002",
            "quantity": "900.00000000",
            "approved_fact_id": approved_receipt["approved_fact_id"],
        },
    )
    assert duplicate.status_code == 422
    assert "receipt number" in duplicate.json()["detail"]

    reconciliation = api.post(
        "/api/v1/evidence/quantity-reconciliations",
        headers=auth_headers(),
        json={
            "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
            "expected_quantity": "1000.00000000",
        },
    )
    assert reconciliation.status_code == 201, reconciliation.text
    assert reconciliation.json() == {
        "reconciliation_issue_id": reconciliation.json()["reconciliation_issue_id"],
        "issue_state": "open",
        "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
        "expected_quantity": "1000.00000000",
        "receipt_quantity": "999.99999999",
        "difference": "-0.00000001",
    }
    assert reconciliation.json()["reconciliation_issue_id"].startswith("qri_")

    approved_ownership = _approved_fact(
        api,
        fact_type="ownership",
        subject_id="lot_0198a000-0000-7000-8000-000000000001",
        value={
            "owner_party_id": "pty_0198a000-0000-7000-8000-000000000001",
            "pledgee_id": "bnk_0198a000-0000-7000-8000-000000000001",
        },
    )
    ownership = api.post(
        "/api/v1/evidence/ownership-claims",
        headers=auth_headers(),
        json={
            "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
            "period": "2026-07",
            "owner_party_id": "pty_0198a000-0000-7000-8000-000000000001",
            "pledgee_id": "bnk_0198a000-0000-7000-8000-000000000001",
            "approved_fact_id": approved_ownership["approved_fact_id"],
        },
    )
    assert ownership.status_code == 201, ownership.text
    assert ownership.json()["ownership_claim_id"].startswith("ioc_")

    conflict = api.post(
        "/api/v1/evidence/ownership-claims",
        headers=auth_headers(),
        json={
            "lot_id": "lot_0198a000-0000-7000-8000-000000000001",
            "period": "2026-07",
            "owner_party_id": "pty_0198a000-0000-7000-8000-000000000002",
            "pledgee_id": "bnk_0198a000-0000-7000-8000-000000000001",
            "approved_fact_id": approved_ownership["approved_fact_id"],
        },
    )
    assert conflict.status_code == 422
    assert "ownership" in conflict.json()["detail"]


def _approved_fact(
    api: TestClient,
    *,
    fact_type: str,
    subject_id: str,
    value: dict[str, str],
) -> dict[str, object]:
    candidate = _candidate_fact(api, fact_type=fact_type, subject_id=subject_id, value=value)
    approved = api.post(
        f"/api/v1/evidence/candidate-facts/{candidate['candidate_fact_id']}/approve",
        headers=auth_headers(),
        json={},
    )
    assert approved.status_code == 201, approved.text
    return cast(dict[str, object], approved.json())


def _candidate_fact(
    api: TestClient,
    *,
    fact_type: str,
    subject_id: str,
    value: dict[str, str],
) -> dict[str, object]:
    document = cast(
        dict[str, object],
        api.post(
            "/api/v1/evidence/documents",
            headers=auth_headers(),
            json={
                "filename": f"{fact_type}.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(f"{fact_type} bytes\n".encode()).decode(),
            },
        ).json(),
    )
    candidate = api.post(
        "/api/v1/evidence/candidate-facts",
        headers=auth_headers(),
        json={
            "fact_type": fact_type,
            "subject_id": subject_id,
            "period": "2026-07",
            "value": value,
            "document_version_id": document["document_version_id"],
            "document_byte_digest": document["byte_digest"],
            "page_region": "page=1;box=10,20,300,80",
            "extraction_method": "deterministic_template",
            "extractor_version": f"{fact_type}-template-v1",
            "raw_value": next(iter(value.values())),
            "normalized_value": next(iter(value.values())),
        },
    )
    assert candidate.status_code == 201, candidate.text
    return cast(dict[str, object], candidate.json())


def _policy_bundle_with_required_fact(
    *, fact_type: str, subject_id: str, period: str
) -> VersionBundle:
    return VersionBundle.build(
        resource_id="pol_0198a000-0000-7000-8000-000000000900",
        bundle_type=BundleType.POLICY,
        schema_version="1.0",
        payload={
            "critical_fact_requirements": [
                {
                    "fact_type": fact_type,
                    "subject_id": subject_id,
                    "period": period,
                }
            ]
        },
        created_by="act_0198a000-0000-7000-8000-000000000001",
        created_at=datetime(2026, 7, 10, 9, tzinfo=UTC),
    )


def _single_policy_loader(policy: VersionBundle) -> Callable[[str], VersionBundle | None]:
    def load_policy_bundle(resource_id: str) -> VersionBundle | None:
        if resource_id == policy.resource_id:
            return policy
        return None

    return load_policy_bundle


def _snapshot_body(
    inputs: list[dict[str, object]],
    *,
    policy_bundle: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "as_of": "2026-06-21T17:00:00.000000Z",
        "market_bundle": {
            "resource_id": "mkt_0198a000-0000-7000-8000-000000000001",
            "digest": "sha256:" + "a" * 64,
        },
        "policy_bundle": policy_bundle or {
            "resource_id": "pol_0198a000-0000-7000-8000-000000000001",
            "digest": "sha256:" + "b" * 64,
        },
        "legal_interpretation_bundle": {
            "resource_id": "leg_0198a000-0000-7000-8000-000000000001",
            "digest": "sha256:" + "d" * 64,
        },
        "computation_bundle": {
            "resource_id": "cmp_0198a000-0000-7000-8000-000000000001",
            "digest": "sha256:" + "c" * 64,
        },
        "inputs": inputs,
    }
