"""FastAPI application and first functional facility endpoints."""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine

from canopyledger.application.integrity import (
    BundleReferenceRejected,
    CreateFacilityCommand,
    FacilityCommandError,
    FacilityNotFound,
    FreezeFacilityCommand,
    IntegrityService,
    PreconditionFailed,
    SnapshotAlreadyFrozen,
    UpdateFacilityCommand,
)
from canopyledger.application.models import CommandResponse
from canopyledger.borrowing_base.calculation import (
    BorrowingBaseError,
    CollateralContribution,
    ContractualReserve,
    calculate_contractual_borrowing_base,
)
from canopyledger.borrowing_base.certificate import (
    CbbCertificateError,
    ContractualUsage,
    build_cbb_certificate,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
    run_initial_domain_pipeline,
)
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
from canopyledger.market.snapshot import FxRate, MarketSnapshot, PriceObservation
from canopyledger.persistence.postgres import PostgresIntegrityStore


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


class MoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    def to_money(self) -> Money:
        return Money(self.amount, self.currency).quantized()


class CbbContributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=100)
    amount: MoneyInput


class CbbReserveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reserve_type: str = Field(min_length=1, max_length=80)
    amount: MoneyInput


class ContractualUsageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_principal: MoneyInput
    lc_exposure: MoneyInput
    other_contractual_usage: MoneyInput


class CbbCertificateDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    certificate_id: str = Field(
        pattern=r"^cbb_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    snapshot_id: str = Field(
        pattern=r"^snp_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    facility_id: str = Field(
        pattern=r"^fac_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    facility_limit: MoneyInput
    contributions: tuple[CbbContributionInput, ...] = Field(min_length=1)
    reserves: tuple[CbbReserveInput, ...] = ()
    usage: ContractualUsageInput
    reason_codes: tuple[str, ...] = ()


class CbbCertificateContributionResponse(BaseModel):
    source_type: str
    source_id: str
    amount: str


class CbbCertificateReserveResponse(BaseModel):
    reserve_type: str
    amount: str


class CbbCertificateResultResponse(BaseModel):
    currency: str
    facility_limit: str
    gross_eligible_contribution: str
    total_reserves: str
    contractual_borrowing_base: str
    contractual_exposure_limit: str
    current_principal: str
    lc_exposure: str
    other_contractual_usage: str
    contractual_availability: str
    contributions: tuple[CbbCertificateContributionResponse, ...]
    reserves: tuple[CbbCertificateReserveResponse, ...]


class CbbCertificateResponse(BaseModel):
    certificate_id: str
    snapshot_id: str
    facility_id: str
    schema_version: str
    result: CbbCertificateResultResponse
    reason_codes: tuple[str, ...]
    output_digest: str


class PriceObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=30)
    price: Decimal
    unit: str = Field(min_length=1, max_length=30)
    observed_at: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=80)


class FxRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: str = Field(min_length=3, max_length=20)
    rate: Decimal
    observed_at: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=80)


class MarketSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=100)
    as_of: str = Field(min_length=1, max_length=40)
    prices: tuple[PriceObservationInput, ...] = Field(min_length=1)
    fx_rates: tuple[FxRateInput, ...] = Field(min_length=1)

    def to_market_snapshot(self) -> MarketSnapshot:
        return MarketSnapshot(
            snapshot_id=self.snapshot_id,
            as_of=self.as_of,
            prices=tuple(
                PriceObservation(
                    symbol=price.symbol,
                    price=price.price,
                    unit=price.unit,
                    observed_at=price.observed_at,
                    source=price.source,
                )
                for price in self.prices
            ),
            fx_rates=tuple(
                FxRate(
                    pair=rate.pair,
                    rate=rate.rate,
                    observed_at=rate.observed_at,
                    source=rate.source,
                )
                for rate in self.fx_rates
            ),
        )


class InventoryLotPipelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=100)
    quantity: Decimal
    quantity_unit: str = Field(min_length=1, max_length=30)
    benchmark_symbol: str = Field(min_length=1, max_length=30)
    physical_differential_usd_per_mt: Decimal
    selling_cost_usd_per_mt: Decimal
    liquidation_cost: MoneyInput
    advance_rate: Decimal
    reason_codes: tuple[str, ...] = ()


class ReceivablePipelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receivable_id: str = Field(min_length=1, max_length=100)
    obligor_id: str = Field(min_length=1, max_length=100)
    invoice_amount: MoneyInput
    credit_note_amount: MoneyInput
    fx_pair: str = Field(min_length=3, max_length=20)
    age_days: int = Field(ge=0)
    advance_rate: Decimal
    max_age_days: int = Field(ge=0)
    delivery_evidence_approved: bool


class M1BPipelineDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=100)
    facility_id: str = Field(min_length=1, max_length=100)
    certificate_id: str = Field(min_length=1, max_length=100)
    facility_limit: MoneyInput
    current_principal: MoneyInput
    lc_exposure: MoneyInput
    other_contractual_usage: MoneyInput
    market_snapshot: MarketSnapshotInput
    inventory_lots: tuple[InventoryLotPipelineInput, ...] = ()
    receivables: tuple[ReceivablePipelineInput, ...] = ()
    reserves: tuple[CbbReserveInput, ...] = ()
    market_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str


class StageOutputResponse(BaseModel):
    stage_output_id: str
    snapshot_id: str
    stage: str
    stage_version: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    result: dict[str, Any]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    output_digest: str


class M1BPipelineDemoResponse(BaseModel):
    stage_outputs: tuple[StageOutputResponse, ...]
    certificate: CbbCertificateResponse


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
    schema_version: str
    as_of: str
    market_bundle: BundleReference
    policy_bundle: BundleReference
    legal_interpretation_bundle: BundleReference
    computation_bundle: BundleReference
    inputs: tuple[SnapshotInputReference, ...]
    created_by: str
    created_at: str
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


def create_app(
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    integrity_service: IntegrityService | None = None,
) -> FastAPI:
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
        return "act_0198a000-0000-7000-8000-000000000001"

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

    @app.exception_handler(FacilityNotFound)
    async def handle_facility_not_found(request: Request, exc: FacilityNotFound) -> JSONResponse:
        return _problem_response(request, 404, "RESOURCE_NOT_FOUND", str(exc))

    @app.exception_handler(PreconditionFailed)
    async def handle_precondition_failed(request: Request, exc: PreconditionFailed) -> JSONResponse:
        return _problem_response(request, 412, "PRECONDITION_FAILED", str(exc))

    @app.exception_handler(SnapshotAlreadyFrozen)
    async def handle_snapshot_already_frozen(
        request: Request, exc: SnapshotAlreadyFrozen
    ) -> JSONResponse:
        return _problem_response(request, 409, "SNAPSHOT_ALREADY_FROZEN", str(exc))

    @app.exception_handler(BundleReferenceRejected)
    async def handle_bundle_reference_rejected(
        request: Request, exc: BundleReferenceRejected
    ) -> JSONResponse:
        return _problem_response(request, 422, "BUNDLE_REFERENCE_REJECTED", str(exc))

    @app.exception_handler(FacilityCommandError)
    async def handle_facility_command_error(
        request: Request, exc: FacilityCommandError
    ) -> JSONResponse:
        return _problem_response(request, 422, "VALIDATION_FAILED", str(exc))

    @app.exception_handler(BorrowingBaseError)
    async def handle_borrowing_base_error(
        request: Request, exc: BorrowingBaseError
    ) -> JSONResponse:
        return _problem_response(request, 422, "VALIDATION_FAILED", str(exc))

    @app.exception_handler(CbbCertificateError)
    async def handle_cbb_error(request: Request, exc: CbbCertificateError) -> JSONResponse:
        return _problem_response(request, 422, "VALIDATION_FAILED", str(exc))

    @app.get("/health", operation_id="healthCheck", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/api/v1/cbb-certificates/demo",
        operation_id="buildCbbCertificateDemo",
        response_model=CbbCertificateResponse,
        responses=_problem_responses(401, 422),
    )
    def build_cbb_certificate_demo(
        command: CbbCertificateDemoRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> CbbCertificateResponse:
        del actor
        contributions = tuple(
            CollateralContribution(
                item.source_type,
                item.source_id,
                item.amount.to_money(),
            )
            for item in command.contributions
        )
        reserves = tuple(
            ContractualReserve(item.reserve_type, item.amount.to_money())
            for item in command.reserves
        )
        assessment = calculate_contractual_borrowing_base(
            facility_limit=command.facility_limit.to_money(),
            contributions=contributions,
            reserves=reserves,
        )
        certificate = build_cbb_certificate(
            certificate_id=command.certificate_id,
            snapshot_id=command.snapshot_id,
            facility_id=command.facility_id,
            assessment=assessment,
            contributions=contributions,
            reserves=reserves,
            usage=ContractualUsage(
                current_principal=command.usage.current_principal.to_money(),
                lc_exposure=command.usage.lc_exposure.to_money(),
                other_contractual_usage=command.usage.other_contractual_usage.to_money(),
            ),
            reason_codes=command.reason_codes,
        )
        return CbbCertificateResponse.model_validate(certificate.to_canonical_dict())

    @app.post(
        "/api/v1/m1b/pipeline/demo",
        operation_id="runM1BPipelineDemo",
        response_model=M1BPipelineDemoResponse,
        responses=_problem_responses(401, 422),
    )
    def run_m1b_pipeline_demo(
        command: M1BPipelineDemoRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> M1BPipelineDemoResponse:
        del actor
        result = run_initial_domain_pipeline(
            M1BPipelineInput(
                snapshot_id=command.snapshot_id,
                facility_id=command.facility_id,
                certificate_id=command.certificate_id,
                facility_limit=command.facility_limit.to_money(),
                current_principal=command.current_principal.to_money(),
                lc_exposure=command.lc_exposure.to_money(),
                other_contractual_usage=command.other_contractual_usage.to_money(),
                market_snapshot=command.market_snapshot.to_market_snapshot(),
                inventory_lots=tuple(
                    InventoryLotInput(
                        lot_id=lot.lot_id,
                        quantity=lot.quantity,
                        quantity_unit=lot.quantity_unit,
                        benchmark_symbol=lot.benchmark_symbol,
                        physical_differential_usd_per_mt=lot.physical_differential_usd_per_mt,
                        selling_cost_usd_per_mt=lot.selling_cost_usd_per_mt,
                        liquidation_cost=lot.liquidation_cost.to_money(),
                        advance_rate=lot.advance_rate,
                        reason_codes=lot.reason_codes,
                    )
                    for lot in command.inventory_lots
                ),
                receivables=tuple(
                    ReceivableInput(
                        receivable_id=receivable.receivable_id,
                        obligor_id=receivable.obligor_id,
                        invoice_amount=receivable.invoice_amount.to_money(),
                        credit_note_amount=receivable.credit_note_amount.to_money(),
                        fx_pair=receivable.fx_pair,
                        age_days=receivable.age_days,
                        advance_rate=receivable.advance_rate,
                        max_age_days=receivable.max_age_days,
                        delivery_evidence_approved=receivable.delivery_evidence_approved,
                    )
                    for receivable in command.receivables
                ),
                reserves=tuple(
                    ReserveInput(reserve.reserve_type, reserve.amount.to_money())
                    for reserve in command.reserves
                ),
                market_bundle_digest=command.market_bundle_digest,
                policy_bundle_digest=command.policy_bundle_digest,
                computation_bundle_digest=command.computation_bundle_digest,
            )
        )
        return M1BPipelineDemoResponse(
            stage_outputs=tuple(
                StageOutputResponse.model_validate(output.to_canonical_dict())
                for output in result.stage_outputs
            ),
            certificate=CbbCertificateResponse.model_validate(
                result.certificate.to_canonical_dict()
            ),
        )

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
        if integrity_service is not None:
            return _command_http_response(
                integrity_service.create_facility(
                    CreateFacilityCommand(
                        actor_id=actor,
                        idempotency_key=idempotency_key,
                        legal_name=command.legal_name,
                        currency=command.currency,
                        facility_commitment=f"{command.facility_commitment:.2f}",
                        correlation_id=new_resource_id("cor"),
                    )
                )
            )
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
        idempotency.register(scope, fingerprint, stored, now=clock())
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
        if integrity_service is not None:
            result = integrity_service.get_facility(facility_id)
            if result is None:
                raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
            return _command_http_response(result)
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
        if if_match is None:
            raise _Problem(428, "PRECONDITION_REQUIRED", "If-Match is required")
        if integrity_service is not None:
            return _command_http_response(
                integrity_service.update_facility(
                    UpdateFacilityCommand(
                        actor_id=actor,
                        facility_id=facility_id,
                        idempotency_key=idempotency_key,
                        if_match=if_match,
                        legal_name=command.legal_name,
                        reason=command.reason,
                        correlation_id=new_resource_id("cor"),
                    )
                )
            )
        record = facilities.get(facility_id)
        if record is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
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
        idempotency.register(scope, fingerprint, stored, now=clock())
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
        if if_match is None:
            raise _Problem(428, "PRECONDITION_REQUIRED", "If-Match is required")
        if integrity_service is not None:
            return _command_http_response(
                integrity_service.freeze_facility(
                    FreezeFacilityCommand(
                        actor_id=actor,
                        facility_id=facility_id,
                        idempotency_key=idempotency_key,
                        if_match=if_match,
                        as_of=command.as_of,
                        market_bundle=command.market_bundle,
                        policy_bundle=command.policy_bundle,
                        legal_interpretation_bundle=command.legal_interpretation_bundle,
                        computation_bundle=command.computation_bundle,
                        inputs=command.inputs,
                        correlation_id=new_resource_id("cor"),
                    )
                )
            )
        record = facilities.get(facility_id)
        if record is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Facility not found")
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
            schema_version="1.0",
            as_of=command.as_of,
            market_bundle=command.market_bundle,
            policy_bundle=command.policy_bundle,
            legal_interpretation_bundle=command.legal_interpretation_bundle,
            computation_bundle=command.computation_bundle,
            inputs=command.inputs,
            created_by=actor,
            created_at=clock(),
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
        idempotency.register(scope, fingerprint, stored, now=clock())
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
    ) -> Response | dict[str, object]:
        del actor
        if integrity_service is not None:
            result = integrity_service.get_snapshot_manifest(snapshot_id)
            if result is None:
                raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
            return Response(
                content=result.body,
                status_code=result.status,
                media_type="application/json",
                headers=dict(result.headers),
            )
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        return _snapshot_representation(snapshot)

    return app


def create_postgres_app(
    database_url: str,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Create production-style API wiring backed by PostgreSQL integrity services."""
    engine = create_engine(database_url)
    service = IntegrityService(PostgresIntegrityStore(engine), clock=clock)
    return create_app(clock=clock, integrity_service=service)


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


def _command_http_response(result: CommandResponse) -> Response:
    headers = dict(result.headers)
    if result.replayed:
        headers["Idempotency-Replayed"] = "true"
    return Response(
        content=result.body,
        status_code=result.status,
        media_type="application/json",
        headers=headers,
    )


def _snapshot_representation(snapshot: SnapshotManifest) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "facility_id": snapshot.facility_id,
        "facility_working_version": snapshot.facility_working_version,
        "schema_version": snapshot.schema_version,
        "as_of": snapshot.as_of.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "market_bundle": snapshot.market_bundle.model_dump(),
        "policy_bundle": snapshot.policy_bundle.model_dump(),
        "legal_interpretation_bundle": snapshot.legal_interpretation_bundle.model_dump(),
        "computation_bundle": snapshot.computation_bundle.model_dump(),
        "inputs": [item.model_dump() for item in snapshot.inputs],
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "digest": snapshot.digest,
    }
