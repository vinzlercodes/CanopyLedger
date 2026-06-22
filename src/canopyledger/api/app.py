"""FastAPI application and first functional facility endpoints."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.idempotency import (
    IdempotencyConflict,
    IdempotencyLedger,
    IdempotencyScope,
    StoredResponse,
    request_fingerprint,
)
from canopyledger.integrity.snapshot import (
    BundleReference,
    SnapshotInputReference,
    SnapshotManifest,
)


@dataclass(frozen=True)
class FacilityRecord:
    resource_id: str
    legal_name: str
    currency: str
    facility_commitment: str
    version: int

    @property
    def representation(self) -> dict[str, str | int]:
        return {
            "id": self.resource_id,
            "legal_name": self.legal_name,
            "currency": self.currency,
            "facility_commitment": self.facility_commitment,
            "version": self.version,
        }

    @property
    def etag(self) -> str:
        digest = domain_digest("facility", 1, canonical_json_bytes(self.representation))[7:]
        return f'"facility:{self.resource_id}:v{self.version}:{digest}"'


class CreateFacility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    facility_commitment: Decimal = Field(gt=0)

    @field_validator("facility_commitment")
    @classmethod
    def enforce_cent_scale(cls, value: Decimal) -> Decimal:
        quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if quantized != value:
            raise ValueError("facility commitment supports at most two decimal places")
        return quantized


class UpdateFacility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class FreezeFacility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    market_bundle: BundleReference
    policy_bundle: BundleReference
    legal_interpretation_bundle: BundleReference
    computation_bundle: BundleReference
    inputs: tuple[SnapshotInputReference, ...] = ()


class HealthResponse(BaseModel):
    status: str


class FacilityResponse(BaseModel):
    id: str
    legal_name: str
    currency: str
    facility_commitment: str
    version: int


class SnapshotManifestResponse(BaseModel):
    snapshot_id: str
    facility_id: str
    facility_working_version: int
    as_of: str
    market_bundle: BundleReference
    policy_bundle: BundleReference
    legal_interpretation_bundle: BundleReference
    computation_bundle: BundleReference
    inputs: tuple[SnapshotInputReference, ...]
    digest: str


class ProblemError(BaseModel):
    field: tuple[str | int, ...]
    message: str
    kind: str


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    trace_id: str
    errors: tuple[ProblemError, ...] | None = None


def create_app() -> FastAPI:
    """Create an isolated application instance with functional in-memory adapters."""
    app = FastAPI(title="CanopyLedger API", version="1.0.0")
    facilities: dict[str, FacilityRecord] = {}
    snapshots: dict[str, SnapshotManifest] = {}
    pipeline_start_outbox: list[str] = []
    idempotency = IdempotencyLedger()
    bearer = HTTPBearer(auto_error=False)

    def current_actor(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or credentials.credentials != "analyst-demo-token"
        ):
            raise _Problem(401, "UNAUTHENTICATED", "Valid demo bearer token required")
        return "act_analyst_demo"

    @app.exception_handler(_Problem)
    async def handle_problem(request: Request, exc: _Problem) -> JSONResponse:
        return _problem_response(request, exc.status, exc.code, exc.detail)

    @app.exception_handler(IdempotencyConflict)
    async def handle_idempotency_conflict(
        request: Request, exc: IdempotencyConflict
    ) -> JSONResponse:
        return _problem_response(request, 409, "IDEMPOTENCY_KEY_REUSED", str(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = tuple(
            ProblemError(
                field=tuple(item["loc"]),
                message=item["msg"],
                kind=item["type"],
            )
            for item in exc.errors()
        )
        return _problem_response(
            request,
            422,
            "VALIDATION_FAILED",
            "Request validation failed",
            errors=errors,
        )

    @app.get("/health", operation_id="healthCheck", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/api/v1/facilities",
        status_code=201,
        operation_id="createFacility",
        response_model=FacilityResponse,
        responses=_problem_responses(401, 409, 422),
    )
    def create_facility(
        command: CreateFacility,
        actor: Annotated[str, Depends(current_actor)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Response:
        scope = IdempotencyScope(actor, "create_facility", "facilities", idempotency_key)
        body = command.model_dump(mode="json")
        fingerprint = request_fingerprint(
            method="POST",
            path="/api/v1/facilities",
            schema_version="facility-create-v1",
            body=body,
        )
        replay = idempotency.lookup(scope, fingerprint)
        if replay is not None:
            return _stored_http_response(replay, replayed=True)

        resource_id = new_resource_id("fac")
        record = FacilityRecord(
            resource_id=resource_id,
            legal_name=command.legal_name,
            currency=command.currency,
            facility_commitment=f"{command.facility_commitment:.2f}",
            version=1,
        )
        facilities[resource_id] = record
        stored = StoredResponse(
            status=201,
            headers={"ETag": record.etag, "Location": f"/api/v1/facilities/{resource_id}"},
            body=json.dumps(record.representation, separators=(",", ":")).encode(),
        )
        idempotency.register(scope, fingerprint, stored, now=datetime.now(UTC))
        return _stored_http_response(stored, replayed=False)

    @app.get(
        "/api/v1/facilities/{facility_id}",
        operation_id="getFacility",
        response_model=FacilityResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def get_facility(
        facility_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> Response:
        del actor
        record = facilities.get(facility_id)
        if record is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
        return JSONResponse(record.representation, headers={"ETag": record.etag})

    @app.patch(
        "/api/v1/facilities/{facility_id}",
        operation_id="updateFacility",
        response_model=FacilityResponse,
        responses=_problem_responses(401, 404, 409, 412, 422, 428),
    )
    def update_facility(
        facility_id: str,
        command: UpdateFacility,
        actor: Annotated[str, Depends(current_actor)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> Response:
        record = facilities.get(facility_id)
        if record is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
        if if_match is None:
            raise _Problem(428, "PRECONDITION_REQUIRED", "If-Match is required")
        if if_match != record.etag:
            raise _Problem(412, "PRECONDITION_FAILED", "Strong ETag does not match")

        scope = IdempotencyScope(actor, "update_facility", facility_id, idempotency_key)
        fingerprint = request_fingerprint(
            method="PATCH",
            path=f"/api/v1/facilities/{facility_id}",
            schema_version="facility-update-v1",
            body=command.model_dump(mode="json"),
            relevant_headers={"if-match": if_match},
        )
        replay = idempotency.lookup(scope, fingerprint)
        if replay is not None:
            return _stored_http_response(replay, replayed=True)

        updated = replace(record, legal_name=command.legal_name, version=record.version + 1)
        facilities[facility_id] = updated
        stored = StoredResponse(
            status=200,
            headers={"ETag": updated.etag},
            body=json.dumps(updated.representation, separators=(",", ":")).encode(),
        )
        idempotency.register(scope, fingerprint, stored, now=datetime.now(UTC))
        return _stored_http_response(stored, replayed=False)

    @app.post(
        "/api/v1/facilities/{facility_id}/snapshots",
        status_code=201,
        operation_id="freezeFacility",
        response_model=SnapshotManifestResponse,
        responses=_problem_responses(401, 404, 409, 412, 422, 428),
    )
    def freeze_facility(
        facility_id: str,
        command: FreezeFacility,
        actor: Annotated[str, Depends(current_actor)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> Response:
        record = facilities.get(facility_id)
        if record is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
        if if_match is None:
            raise _Problem(428, "PRECONDITION_REQUIRED", "If-Match is required")
        if if_match != record.etag:
            raise _Problem(412, "PRECONDITION_FAILED", "Strong ETag does not match")

        scope = IdempotencyScope(actor, "freeze_facility", facility_id, idempotency_key)
        fingerprint = request_fingerprint(
            method="POST",
            path=f"/api/v1/facilities/{facility_id}/snapshots",
            schema_version="facility-freeze-v1",
            body=command.model_dump(mode="json"),
            relevant_headers={"if-match": if_match},
        )
        replay = idempotency.lookup(scope, fingerprint)
        if replay is not None:
            return _stored_http_response(replay, replayed=True)

        snapshot = SnapshotManifest(
            snapshot_id=new_resource_id("snp"),
            facility_id=facility_id,
            facility_working_version=record.version,
            as_of=command.as_of,
            market_bundle=command.market_bundle,
            policy_bundle=command.policy_bundle,
            legal_interpretation_bundle=command.legal_interpretation_bundle,
            computation_bundle=command.computation_bundle,
            inputs=command.inputs,
        )
        snapshots[snapshot.snapshot_id] = snapshot
        pipeline_start_outbox.append(snapshot.snapshot_id)
        representation = _snapshot_representation(snapshot)
        stored = StoredResponse(
            status=201,
            headers={
                "ETag": f'"snapshot:{snapshot.snapshot_id}:{snapshot.digest[7:]}"',
                "Location": f"/api/v1/snapshots/{snapshot.snapshot_id}",
            },
            body=json.dumps(representation, separators=(",", ":")).encode(),
        )
        idempotency.register(scope, fingerprint, stored, now=datetime.now(UTC))
        return _stored_http_response(stored, replayed=False)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/manifest",
        operation_id="getSnapshotManifest",
        response_model=SnapshotManifestResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def get_snapshot_manifest(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> dict[str, object]:
        del actor
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        return _snapshot_representation(snapshot)

    return app


class _Problem(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail


def _problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {
        status: {
            "description": "Problem Details",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for status in statuses
    }


def _problem_response(
    request: Request,
    status: int,
    code: str,
    detail: str,
    *,
    errors: tuple[ProblemError, ...] | None = None,
) -> JSONResponse:
    problem = ProblemDetails(
        type=f"https://canopyledger.example/problems/{code.lower()}",
        title=code.replace("_", " ").title(),
        status=status,
        detail=detail,
        instance=str(request.url.path),
        code=code,
        trace_id=new_resource_id("trc"),
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=problem.model_dump(mode="json", exclude_none=True),
    )


def _stored_http_response(stored: StoredResponse, *, replayed: bool) -> Response:
    headers = dict(stored.headers)
    if replayed:
        headers["Idempotency-Replayed"] = "true"
    return Response(
        content=stored.body,
        status_code=stored.status,
        media_type="application/json",
        headers=headers,
    )


def _snapshot_representation(snapshot: SnapshotManifest) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "facility_id": snapshot.facility_id,
        "facility_working_version": snapshot.facility_working_version,
        "as_of": snapshot.as_of.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "market_bundle": snapshot.market_bundle.model_dump(),
        "policy_bundle": snapshot.policy_bundle.model_dump(),
        "legal_interpretation_bundle": snapshot.legal_interpretation_bundle.model_dump(),
        "computation_bundle": snapshot.computation_bundle.model_dump(),
        "inputs": [item.model_dump() for item in snapshot.inputs],
        "digest": snapshot.digest,
    }
