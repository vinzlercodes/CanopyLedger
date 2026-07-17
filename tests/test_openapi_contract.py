"""Contract tests for the checked-in OpenAPI v1 artifact."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app
from canopyledger.api.openapi import render_openapi_json

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_ARTIFACT = ROOT / "docs" / "api" / "openapi-v1.json"


def test_protected_operations_use_bearer_security() -> None:
    schema = create_app().openapi()

    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert "security" not in schema["paths"]["/health"]["get"]
    for path, item in schema["paths"].items():
        if path == "/health":
            continue
        for operation in item.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert all(
                parameter["name"].lower() != "authorization"
                for parameter in operation.get("parameters", [])
            )


def test_operation_ids_are_explicit_stable_and_unique() -> None:
    schema = create_app().openapi()
    operation_ids = {
        operation["operationId"]
        for item in schema["paths"].values()
        for method, operation in item.items()
        if method in {"get", "post", "patch"}
    }

    assert operation_ids == {
        "approveCandidateFact",
        "approveApprovalRequest",
        "approveDecisionOverride",
        "askAnalyticsQuestion",
        "getAgentRun",
        "buildCbbCertificateDemo",
        "createCandidateFact",
        "createApprovalRequest",
        "createDecisionOverride",
        "createRecommendationOverride",
        "createFacility",
        "createRecommendation",
        "evaluateHedgeLiquidityDemo",
        "extractEvidenceDocument",
        "freezeFacility",
        "generateDecisionReport",
        "getCandidateFactReview",
        "getCandidateFactExtractionProvenance",
            "getClimateTraceabilityProjection",
        "getCreditEarlyWarningProjection",
            "getDecisionOverride",
        "downloadReportArtifact",
        "getDecisionOverrideQueue",
        "getEvidenceDocumentRendition",
        "getEvidenceDocumentExtraction",
        "getEvidenceReviewQueue",
        "getFacility",
        "getHedgeLabProjection",
        "getHedgeLiquidityAssessment",
        "getFinalDecision",
        "getGovernanceTimeline",
        "getInternalRiskCapacityAssessment",
        "getApprovalQueue",
        "listAgentRuns",
        "listAgentCapabilities",
        "listDecisionReports",
        "getApprovalRequest",
        "getRecommendation",
        "getScenarioAssessment",
        "getScenarioLabProjection",
        "getSnapshotCollateral",
        "getSnapshotDecisionPack",
        "getSnapshotManifest",
        "healthCheck",
        "rejectCandidateFact",
        "rejectApprovalRequest",
        "recordOwnershipClaim",
        "recordWarehouseReceiptEvidence",
        "reconcileLotQuantity",
        "runM1BPipelineDemo",
        "startAgentRun",
        "supersedeApprovedFact",
        "updateFacility",
        "uploadEvidenceDocument",
    }


def test_success_and_problem_responses_have_typed_schemas() -> None:
    schema = create_app().openapi()
    create = schema["paths"]["/api/v1/facilities"]["post"]

    assert create["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FacilityResponse"
    }
    assert create["responses"]["401"]["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetails"
    }
    assert create["responses"]["422"]["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetails"
    }


def test_climate_traceability_projection_is_a_typed_contract() -> None:
    schema = create_app().openapi()["components"]["schemas"]

    assert schema["ClimateTraceabilityProjectionResponse"]["properties"]["result"] == {
        "$ref": "#/components/schemas/ClimateTraceabilityResultResponse"
    }
    assert "TraceabilityLotResponse" in schema


def test_request_validation_uses_problem_details() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/facilities",
        headers={
            "Authorization": "Bearer analyst-demo-token",
            "Idempotency-Key": "invalid-facility",
        },
        json={"legal_name": "", "currency": "euro", "facility_commitment": "0"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["trace_id"].startswith("trc_")
    assert body["errors"]
    assert {error["field"][-1] for error in body["errors"]} == {
        "currency",
        "facility_commitment",
        "legal_name",
    }


def test_checked_in_openapi_matches_deterministic_generation() -> None:
    assert OPENAPI_ARTIFACT.read_bytes() == render_openapi_json(create_app())


def test_every_local_schema_reference_resolves() -> None:
    document = json.loads(OPENAPI_ARTIFACT.read_text())
    schemas = document["components"]["schemas"]

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                assert reference.removeprefix("#/components/schemas/") in schemas
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(document)


def test_openapi_artifact_is_valid_json_with_a_trailing_newline() -> None:
    artifact = OPENAPI_ARTIFACT.read_bytes()
    assert artifact.endswith(b"\n")
    assert json.loads(artifact)["info"]["version"] == "1.0.0"


def test_typescript_client_preserves_nullable_openapi_fields() -> None:
    generated = (ROOT / "typescript" / "generated" / "index.ts").read_text()
    assert "readonly final_decision?: GovernanceResourceResponse | null;" in generated
    assert "readonly recommendation?: RecommendationDetailResponse | null;" in generated


def test_m7_extraction_contract_exposes_candidate_only_provenance() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/evidence/documents/{document_version_id}/extractions"][
        "post"
    ]
    response = schema["components"]["schemas"]["DocumentExtractionResponse"]

    assert operation["operationId"] == "extractEvidenceDocument"
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DocumentExtractionResponse"
    }
    required_provenance = {
        "document_byte_digest",
        "classification_method",
        "extractor_version",
        "text_digest",
    }
    assert required_provenance.issubset(response["properties"])
    assert "approved_fact_id" not in response["properties"]
