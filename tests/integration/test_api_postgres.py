"""Durable FastAPI/PostgreSQL M1A acceptance tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from canopyledger.api.app import create_postgres_app
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.persistence.postgres import PostgresIntegrityStore

pytestmark = pytest.mark.postgres

ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"
NOW = datetime(2026, 6, 23, 12, tzinfo=UTC)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer analyst-demo-token"}


def publish_required_bundles(
    engine: Engine,
    *,
    policy_payload: object | None = None,
) -> list[dict[str, str]]:
    store = PostgresIntegrityStore(engine)
    references = []
    for bundle_type, prefix in (
        (BundleType.MARKET, "mkt"),
        (BundleType.POLICY, "pol"),
        (BundleType.LEGAL_INTERPRETATION, "leg"),
        (BundleType.COMPUTATION, "cmp"),
    ):
        resource_id = new_resource_id(prefix)
        bundle = VersionBundle.build(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version="1.0",
            payload=policy_payload
            if bundle_type is BundleType.POLICY and policy_payload is not None
            else {"resource_id": resource_id},
            created_by=ACTOR_ID,
            created_at=NOW,
        )
        store.publish_bundle(bundle)
        references.append(bundle.reference.model_dump())
    return references


def client(database_url: str) -> TestClient:
    return TestClient(create_postgres_app(database_url))


def test_facility_idempotency_and_snapshot_survive_app_restart(
    database_url: str,
    database_engine: Engine,
) -> None:
    first_client = client(database_url)
    run_key = new_resource_id("key")
    create_headers = {**auth_headers(), "Idempotency-Key": f"durable-create-{run_key}"}
    create_body = {
        "legal_name": "Durable Coffee Trading BV",
        "currency": "EUR",
        "facility_commitment": "12000000.00",
    }
    created = first_client.post("/api/v1/facilities", headers=create_headers, json=create_body)
    assert created.status_code == 201, created.text
    facility_id = created.json()["id"]

    restarted_client = client(database_url)
    replayed_create = restarted_client.post(
        "/api/v1/facilities", headers=create_headers, json=create_body
    )
    assert replayed_create.status_code == 201, replayed_create.text
    assert replayed_create.json() == created.json()
    assert replayed_create.headers["idempotency-replayed"] == "true"

    fetched = restarted_client.get(f"/api/v1/facilities/{facility_id}", headers=auth_headers())
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == created.json()
    assert fetched.headers["etag"] == created.headers["etag"]

    market, policy, legal, computation = publish_required_bundles(database_engine)
    freeze_headers = {
        **auth_headers(),
        "Idempotency-Key": f"durable-freeze-{run_key}",
        "If-Match": created.headers["etag"],
    }
    freeze_body = {
        "as_of": "2026-06-23T12:00:00.000000Z",
        "market_bundle": market,
        "policy_bundle": policy,
        "legal_interpretation_bundle": legal,
        "computation_bundle": computation,
        "inputs": [],
    }
    frozen = restarted_client.post(
        f"/api/v1/facilities/{facility_id}/snapshots",
        headers=freeze_headers,
        json=freeze_body,
    )
    assert frozen.status_code == 201, frozen.text
    assert frozen.json()["legal_interpretation_bundle"] == legal

    final_client = client(database_url)
    replayed_freeze = final_client.post(
        f"/api/v1/facilities/{facility_id}/snapshots",
        headers=freeze_headers,
        json=freeze_body,
    )
    assert replayed_freeze.status_code == 201, replayed_freeze.text
    assert replayed_freeze.json() == frozen.json()
    assert replayed_freeze.headers["idempotency-replayed"] == "true"

    manifest = final_client.get(
        f"/api/v1/snapshots/{frozen.json()['snapshot_id']}/manifest",
        headers=auth_headers(),
    )
    assert manifest.status_code == 200, manifest.text
    assert manifest.json() == frozen.json()
    assert json.dumps(manifest.json(), sort_keys=True)


def test_postgres_freeze_expands_policy_required_evidence(
    database_url: str,
    database_engine: Engine,
) -> None:
    api = client(database_url)
    lot_id = "lot_0198a000-0000-7000-8000-000000000001"
    policy_payload = {
        "critical_fact_requirements": [
            {"fact_type": "ownership", "subject_id": lot_id, "period": "2026-07"}
        ]
    }
    market, policy, legal, computation = publish_required_bundles(
        database_engine,
        policy_payload=policy_payload,
    )
    document = api.post(
        "/api/v1/evidence/documents",
        headers=auth_headers(),
        json={
            "filename": "ownership.pdf",
            "content_type": "application/pdf",
            "content_base64": "b3duZXJzaGlwCg==",
        },
    )
    assert document.status_code == 201, document.text
    candidate = api.post(
        "/api/v1/evidence/candidate-facts",
        headers=auth_headers(),
        json={
            "fact_type": "ownership",
            "subject_id": lot_id,
            "period": "2026-07",
            "value": {"owner_party_id": "pty_0198a000-0000-7000-8000-000000000001"},
            "document_version_id": document.json()["document_version_id"],
            "document_byte_digest": document.json()["byte_digest"],
            "page_region": "page=1;box=10,20,300,80",
            "extraction_method": "deterministic_template",
            "extractor_version": "ownership-template-v1",
            "raw_value": "pty_0198a000-0000-7000-8000-000000000001",
            "normalized_value": "pty_0198a000-0000-7000-8000-000000000001",
        },
    )
    assert candidate.status_code == 201, candidate.text
    approved = api.post(
        f"/api/v1/evidence/candidate-facts/{candidate.json()['candidate_fact_id']}/approve",
        headers=auth_headers(),
        json={},
    )
    assert approved.status_code == 201, approved.text
    created = api.post(
        "/api/v1/facilities",
        headers={**auth_headers(), "Idempotency-Key": "policy-freeze-create-0001"},
        json={
            "legal_name": "Policy Coffee Trading BV",
            "currency": "EUR",
            "facility_commitment": "12000000.00",
        },
    )
    assert created.status_code == 201, created.text

    frozen = api.post(
        f"/api/v1/facilities/{created.json()['id']}/snapshots",
            headers={
                **auth_headers(),
                "Idempotency-Key": "policy-freeze-0001",
                "If-Match": created.headers["etag"],
            },
        json={
            "as_of": "2026-06-23T12:00:00.000000Z",
            "market_bundle": market,
            "policy_bundle": policy,
            "legal_interpretation_bundle": legal,
            "computation_bundle": computation,
            "inputs": [],
        },
    )

    assert frozen.status_code == 201, frozen.text
    assert frozen.json()["inputs"] == [
        {
            "resource_type": "approved_fact",
            "resource_id": approved.json()["approved_fact_id"],
            "digest": approved.json()["digest"],
        }
    ]
