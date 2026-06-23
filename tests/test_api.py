"""API v1 contract tests for the first runnable vertical slice."""

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app


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
