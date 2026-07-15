"""Executable contract for the opt-in seeded workspace demonstration."""

import pytest
from fastapi.testclient import TestClient

from canopyledger.demo.workspace import FACILITY_ID, SNAPSHOT_ID, create_demo_app

ANALYST = {"Authorization": "Bearer analyst-demo-token"}
APPROVER = {"Authorization": "Bearer approver-demo-token"}


@pytest.mark.parametrize(
    "path",
    (
        f"/api/v1/facilities/{FACILITY_ID}",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/manifest",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/collateral",
        "/api/v1/evidence/review-queue",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/hedge-lab",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/scenario-lab",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/climate-traceability",
        "/api/v1/approval-requests",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/override-requests",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/governance-timeline",
    ),
)
def test_seeded_workspace_demo_requires_a_valid_bearer_for_every_workspace_read(path: str) -> None:
    api = TestClient(create_demo_app())

    assert api.get(path).status_code == 401
    assert api.get(path, headers={"Authorization": "Bearer not-a-demo-token"}).status_code == 401


@pytest.mark.parametrize(
    "path",
    (
        f"/api/v1/facilities/{FACILITY_ID}",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/manifest",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/collateral?section=inventory",
        "/api/v1/evidence/review-queue",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/hedge-lab",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/scenario-lab",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/climate-traceability",
    ),
)
def test_seeded_workspace_demo_allows_both_read_roles_to_inspect_published_state(path: str) -> None:
    api = TestClient(create_demo_app())

    assert api.get(path, headers=ANALYST).status_code == 200
    assert api.get(path, headers=APPROVER).status_code == 200


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/facilities/fac_0198a000-0000-7000-8000-000000000802",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/manifest",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/decision-pack",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/collateral",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/hedge-lab",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/scenario-lab",
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/climate-traceability",
    ),
)
def test_seeded_workspace_demo_rejects_unknown_context_without_a_server_error(path: str) -> None:
    response = TestClient(create_demo_app()).get(path, headers=ANALYST)

    assert response.status_code == 404, response.text


def test_seeded_workspace_demo_fences_every_approver_workspace_route() -> None:
    api = TestClient(create_demo_app())
    approver_only_paths = (
        "/api/v1/approval-requests",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/override-requests",
        f"/api/v1/snapshots/{SNAPSHOT_ID}/governance-timeline",
    )

    for path in approver_only_paths:
        assert api.get(path, headers=ANALYST).status_code == 403
        assert api.get(path, headers=APPROVER).status_code == 200


def test_seeded_workspace_demo_exposes_real_fastapi_context_and_role_boundaries() -> None:
    api = TestClient(create_demo_app())

    facility = api.get(f"/api/v1/facilities/{FACILITY_ID}", headers=ANALYST)
    assert facility.status_code == 200, facility.text
    assert facility.json()["legal_name"] == "Fixture Coffee Trader"

    manifest = api.get(f"/api/v1/snapshots/{SNAPSHOT_ID}/manifest", headers=ANALYST)
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["facility_id"] == FACILITY_ID

    cockpit = api.get(f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack", headers=ANALYST)
    assert cockpit.status_code == 200, cockpit.text
    assert cockpit.json()["snapshot_id"] == SNAPSHOT_ID

    evidence = api.get("/api/v1/evidence/review-queue", headers=ANALYST)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["items"][0]["fact_type"] == "warehouse_receipt"

    assert api.get("/api/v1/approval-requests", headers=ANALYST).status_code == 403
    approval_queue = api.get("/api/v1/approval-requests", headers=APPROVER)
    assert approval_queue.status_code == 200, approval_queue.text
    assert approval_queue.json()["items"][0]["approval_request_id"].startswith("arq_")

    missing = api.get(
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000802/decision-pack",
        headers=ANALYST,
    )
    assert missing.status_code == 404


def test_seeded_decision_pack_surfaces_evidence_readiness_without_a_legal_conclusion() -> None:
    response = TestClient(create_demo_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/decision-pack", headers=ANALYST
    )

    assert response.status_code == 200, response.text
    climate = response.json()["climate_traceability"]
    assert climate["eudr_evidence_state"] == "review_required"
    assert climate["legal_interpretation_bundle_digest"] == "sha256:" + "c" * 64
    assert "compliant" not in str(climate).lower()


def test_seeded_workspace_demo_allows_an_independent_approver_to_record_a_decision() -> None:
    api = TestClient(create_demo_app())
    approval_request_id = "arq_0198a000-0000-7000-8000-000000000801"

    response = api.post(
        f"/api/v1/approval-requests/{approval_request_id}/approve",
        headers=APPROVER,
        json={
            "approval_action_id": "apa_0198a000-0000-7000-8000-000000000801",
            "final_decision_id": "fdc_0198a000-0000-7000-8000-000000000801",
            "reason": "Independent review of synthetic collateral and margin stress.",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "APPROVED"
    assert api.get("/api/v1/approval-requests", headers=APPROVER).json() == {"items": []}


def test_seeded_workspace_demo_enforces_evidence_and_final_decision_boundaries() -> None:
    candidate_fact_id = "caf_0198a000-0000-7000-8000-000000000801"
    approval_request_id = "arq_0198a000-0000-7000-8000-000000000801"

    invalid_rejection = TestClient(create_demo_app()).post(
        f"/api/v1/evidence/candidate-facts/{candidate_fact_id}/reject",
        headers=ANALYST,
        json={"reason": ""},
    )
    assert invalid_rejection.status_code == 422, invalid_rejection.text
    assert invalid_rejection.json()["code"] == "VALIDATION_FAILED"

    evidence_api = TestClient(create_demo_app())
    approved_fact = evidence_api.post(
        f"/api/v1/evidence/candidate-facts/{candidate_fact_id}/approve",
        headers=ANALYST,
    )
    assert approved_fact.status_code == 201, approved_fact.text
    assert evidence_api.get("/api/v1/evidence/review-queue", headers=ANALYST).json() == {
        "items": []
    }

    analyst_final_approval = TestClient(create_demo_app()).post(
        f"/api/v1/approval-requests/{approval_request_id}/approve",
        headers=ANALYST,
        json={
            "approval_action_id": "apa_0198a000-0000-7000-8000-000000000802",
            "final_decision_id": "fdc_0198a000-0000-7000-8000-000000000802",
            "reason": "An analyst cannot record this final decision.",
        },
    )
    assert analyst_final_approval.status_code == 403, analyst_final_approval.text
    assert analyst_final_approval.json()["code"] == "FORBIDDEN"

    approver_api = TestClient(create_demo_app())
    rejected = approver_api.post(
        f"/api/v1/approval-requests/{approval_request_id}/reject",
        headers=APPROVER,
        json={
            "approval_action_id": "apa_0198a000-0000-7000-8000-000000000802",
            "final_decision_id": "fdc_0198a000-0000-7000-8000-000000000802",
            "reason": "Independent review rejects this synthetic request.",
        },
    )
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    assert approver_api.get("/api/v1/approval-requests", headers=APPROVER).json() == {
        "items": []
    }
