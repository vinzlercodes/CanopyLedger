"""FastAPI application and first functional facility endpoints."""

import base64
import binascii
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from html import escape
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import create_engine

from canopyledger.application.evidence import (
    EvidenceReviewPacket,
    EvidenceService,
    InMemoryEvidenceStore,
    OwnershipClaimRecord,
    QuantityReconciliationRecord,
    WarehouseReceiptRecord,
)
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
from canopyledger.evidence.controls import (
    ApprovedFact,
    CandidateFact,
    DocumentVersion,
    EvidenceControlError,
    FactIdentity,
    RejectedFact,
    approved_fact_digest,
)
from canopyledger.hedge.engine import (
    ExchangeContractSpecification,
    ExerciseStyle,
    FuturesPosition,
    HedgeLiquidityError,
    HedgeLiquidityInput,
    OptionPosition,
    OptionType,
    PhysicalExposure,
    evaluate_hedge_and_liquidity,
)
from canopyledger.hedge.postgres import (
    PostgresHedgeLiquidityInputStore,
    PostgresHedgeLiquidityRunner,
)
from canopyledger.initial_domain.pipeline import (
    InventoryLotInput,
    M1BPipelineInput,
    ReceivableInput,
    ReserveInput,
    run_initial_domain_pipeline,
)
from canopyledger.integrity.bundles import BundleType, VersionBundle
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
from canopyledger.persistence.postgres import PostgresEvidenceStore, PostgresIntegrityStore


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


class EvidenceDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1)


class EvidenceDocumentResponse(BaseModel):
    document_id: str
    document_version_id: str
    version: int
    filename: str
    content_type: str
    byte_digest: str
    size_bytes: int
    created_by: str
    created_at: str


class EvidenceCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str = Field(min_length=1, max_length=80)
    subject_id: str = Field(min_length=1, max_length=100)
    period: str = Field(min_length=1, max_length=40)
    value: dict[str, Any]
    document_version_id: str = Field(min_length=1, max_length=80)
    document_byte_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    page_region: str = Field(min_length=1, max_length=200)
    extraction_method: str = Field(min_length=1, max_length=80)
    extractor_version: str = Field(min_length=1, max_length=120)
    raw_value: str = Field(min_length=1, max_length=1000)
    normalized_value: str = Field(min_length=1, max_length=1000)


class EvidenceLineageResponse(BaseModel):
    candidate_fact_id: str | None = None
    document_version_id: str
    document_byte_digest: str


class CandidateFactResponse(BaseModel):
    candidate_fact_id: str
    approval_state: str
    fact_type: str
    subject_id: str
    period: str
    value: dict[str, Any]
    page_region: str
    extraction_method: str
    extractor_version: str
    raw_value: str
    normalized_value: str
    lineage: EvidenceLineageResponse


class ApprovedFactResponse(BaseModel):
    approved_fact_id: str
    approval_state: str
    digest: str
    lineage: EvidenceLineageResponse


class RejectCandidateFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=1000)


class SupersedeApprovedFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_fact_id: str = Field(min_length=1, max_length=40)


class RejectedFactResponse(BaseModel):
    rejected_fact_id: str
    candidate_fact_id: str
    approval_state: str
    reason: str


class EvidenceReviewPacketResponse(BaseModel):
    document: EvidenceDocumentResponse
    candidate_fact: CandidateFactResponse
    conflicts: tuple[str, ...]
    approval_history: tuple[ApprovedFactResponse, ...]
    supersession_chain: tuple[str, ...]


class WarehouseReceiptEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_number: str = Field(min_length=1, max_length=100)
    warehouse_id: str = Field(min_length=1, max_length=40)
    lot_id: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=80)
    approved_fact_id: str = Field(min_length=1, max_length=40)


class WarehouseReceiptEvidenceResponse(BaseModel):
    receipt_evidence_id: str
    receipt_number: str
    warehouse_id: str
    lot_id: str
    quantity: str
    approved_fact_id: str


class OwnershipClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=40)
    period: str = Field(min_length=1, max_length=40)
    owner_party_id: str = Field(min_length=1, max_length=40)
    pledgee_id: str = Field(min_length=1, max_length=40)
    approved_fact_id: str = Field(min_length=1, max_length=40)


class OwnershipClaimResponse(BaseModel):
    ownership_claim_id: str
    lot_id: str
    period: str
    owner_party_id: str
    pledgee_id: str
    approved_fact_id: str


class QuantityReconciliationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=40)
    expected_quantity: str = Field(min_length=1, max_length=80)


class QuantityReconciliationResponse(BaseModel):
    reconciliation_issue_id: str | None
    issue_state: str
    lot_id: str
    expected_quantity: str
    receipt_quantity: str
    difference: str


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


class HedgeUnitFactorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_unit: str = Field(min_length=1, max_length=40)
    output_unit: str = Field(min_length=1, max_length=40)
    factor: Decimal = Field(gt=0)


class ExchangeContractSpecificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(min_length=1, max_length=40)
    product_code: str = Field(min_length=1, max_length=20)
    contract_symbol: str = Field(min_length=1, max_length=30)
    contract_size: Decimal = Field(gt=0)
    contract_size_unit: str = Field(min_length=1, max_length=40)
    price_unit: str = Field(min_length=1, max_length=40)
    price_unit_factor: Decimal = Field(gt=0)
    tick_size: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    exercise_style: ExerciseStyle
    settlement_rule: str = Field(min_length=1, max_length=80)
    calendar_version: str = Field(min_length=1, max_length=80)
    delivery_months: tuple[str, ...] = Field(min_length=1)
    effective_from: str = Field(min_length=1, max_length=40)
    effective_to: str = Field(min_length=1, max_length=40)
    source_document_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def to_contract_specification(self) -> ExchangeContractSpecification:
        return ExchangeContractSpecification(**self.model_dump())


class PhysicalExposureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str = Field(min_length=1, max_length=20)
    delivery_month: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(ge=0)
    quantity_unit: str = Field(min_length=1, max_length=40)

    def to_physical_exposure(self) -> PhysicalExposure:
        return PhysicalExposure(**self.model_dump())


class FuturesPositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_specification: ExchangeContractSpecificationInput
    contracts: Decimal
    delivery_month: str = Field(min_length=1, max_length=20)
    entry_futures_price: Decimal
    current_futures_price: Decimal

    def to_futures_position(self) -> FuturesPosition:
        return FuturesPosition(
            contract_specification=self.contract_specification.to_contract_specification(),
            contracts=self.contracts,
            delivery_month=self.delivery_month,
            entry_futures_price=self.entry_futures_price,
            current_futures_price=self.current_futures_price,
        )


class OptionPositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_specification: ExchangeContractSpecificationInput
    contracts: Decimal
    delivery_month: str = Field(min_length=1, max_length=20)
    option_type: OptionType
    strike: Decimal = Field(gt=0)
    futures_price: Decimal = Field(ge=0)
    volatility: Decimal = Field(ge=0)
    risk_free_rate: Decimal
    time_to_expiry: Decimal = Field(ge=0)
    lattice_steps: int = Field(default=200, ge=2, le=2000)
    entry_option_price: Decimal | None = None

    def to_option_position(self) -> OptionPosition:
        return OptionPosition(
            contract_specification=self.contract_specification.to_contract_specification(),
            contracts=self.contracts,
            delivery_month=self.delivery_month,
            option_type=self.option_type,
            strike=self.strike,
            futures_price=self.futures_price,
            volatility=self.volatility,
            risk_free_rate=self.risk_free_rate,
            time_to_expiry=self.time_to_expiry,
            lattice_steps=self.lattice_steps,
            entry_option_price=self.entry_option_price,
        )


class HedgeLiquidityDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(min_length=1, max_length=100)
    snapshot_id: str = Field(min_length=1, max_length=100)
    as_of: date
    cbb_output_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    market_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    computation_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    exposure_unit: str = Field(min_length=1, max_length=40)
    unit_conversion_factors: tuple[HedgeUnitFactorInput, ...] = ()
    physical_exposure: tuple[PhysicalExposureInput, ...] = ()
    purchase_commitments: tuple[PhysicalExposureInput, ...] = ()
    sales_commitments: tuple[PhysicalExposureInput, ...] = ()
    futures_positions: tuple[FuturesPositionInput, ...] = ()
    option_positions: tuple[OptionPositionInput, ...] = ()
    fx_exposure: MoneyInput
    basis_exposure: Decimal
    available_cash: MoneyInput
    undrawn_contractual_availability: MoneyInput
    one_day_futures_moves: dict[str, Decimal]
    multi_day_futures_moves: dict[str, Decimal]
    fx_rates_to_facility: dict[str, Decimal] = Field(default_factory=dict)
    required_liquidity_coverage_ratio: Decimal = Field(default=Decimal("1"), gt=0)

    def to_hedge_liquidity_input(self) -> HedgeLiquidityInput:
        from canopyledger.domain.units import UnitConversionTable

        return HedgeLiquidityInput(
            assessment_id=self.assessment_id,
            snapshot_id=self.snapshot_id,
            as_of=self.as_of,
            cbb_output_digest=self.cbb_output_digest,
            market_bundle_digest=self.market_bundle_digest,
            policy_bundle_digest=self.policy_bundle_digest,
            computation_bundle_digest=self.computation_bundle_digest,
            exposure_unit=self.exposure_unit,
            unit_conversion_table=UnitConversionTable(
                version="m3-request-unit-table-v1",
                factors={
                    (factor.input_unit, factor.output_unit): factor.factor
                    for factor in self.unit_conversion_factors
                },
            ),
            physical_exposure=tuple(item.to_physical_exposure() for item in self.physical_exposure),
            purchase_commitments=tuple(
                item.to_physical_exposure() for item in self.purchase_commitments
            ),
            sales_commitments=tuple(item.to_physical_exposure() for item in self.sales_commitments),
            futures_positions=tuple(item.to_futures_position() for item in self.futures_positions),
            option_positions=tuple(item.to_option_position() for item in self.option_positions),
            fx_exposure=self.fx_exposure.to_money(),
            basis_exposure=self.basis_exposure,
            available_cash=self.available_cash.to_money(),
            undrawn_contractual_availability=self.undrawn_contractual_availability.to_money(),
            one_day_futures_moves=self.one_day_futures_moves,
            multi_day_futures_moves=self.multi_day_futures_moves,
            fx_rates_to_facility=self.fx_rates_to_facility,
            required_liquidity_coverage_ratio=self.required_liquidity_coverage_ratio,
        )


class HedgeLiquidityPreviewResponse(BaseModel):
    """A calculation sandbox response that cannot be mistaken for a published S5 output."""

    assessment_id: str
    snapshot_id: str
    result: dict[str, Any]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    authoritativeness: Literal["preview"]


class HedgeLiquidityStageOutputResponse(BaseModel):
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
    started_at: datetime
    completed_at: datetime
    output_digest: str


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
    evidence_service: EvidenceService | None = None,
    policy_bundle_loader: Callable[[str], VersionBundle | None] | None = None,
    hedge_output_loader: Callable[[str], dict[str, object] | None] | None = None,
) -> FastAPI:
    """Create an isolated application instance with functional in-memory adapters."""
    app = FastAPI(title="CanopyLedger API", version="1.0.0")
    facilities: dict[str, FacilityRecord] = {}
    snapshots: dict[str, SnapshotManifest] = {}
    pipeline_start_outbox: list[str] = []
    evidence = evidence_service or EvidenceService(
        store=InMemoryEvidenceStore(),
        clock=clock,
        id_factory=new_resource_id,
    )
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

    @app.exception_handler(ValidationError)
    async def handle_domain_validation(request: Request, exc: ValidationError) -> JSONResponse:
        first_error = exc.errors()[0]["msg"] if exc.errors() else "Domain validation failed"
        return _problem_response(request, 422, "VALIDATION_FAILED", str(first_error))

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

    @app.exception_handler(EvidenceControlError)
    async def handle_evidence_control_error(
        request: Request, exc: EvidenceControlError
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

    @app.exception_handler(HedgeLiquidityError)
    async def handle_hedge_liquidity_error(
        request: Request, exc: HedgeLiquidityError
    ) -> JSONResponse:
        return _problem_response(request, 422, "VALIDATION_FAILED", str(exc))

    @app.get("/health", operation_id="healthCheck", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/api/v1/evidence/documents",
        status_code=201,
        operation_id="uploadEvidenceDocument",
        response_model=EvidenceDocumentResponse,
        responses=_problem_responses(401, 422),
    )
    def upload_evidence_document(
        command: EvidenceDocumentCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> EvidenceDocumentResponse:
        try:
            content = base64.b64decode(command.content_base64, validate=True)
        except binascii.Error as exc:
            raise _Problem(422, "VALIDATION_FAILED", "content_base64 is invalid") from exc
        document = evidence.upload_document(
            filename=command.filename,
            content_type=command.content_type,
            content=content,
            actor_id=actor,
        )
        return _evidence_document_response(document)

    @app.post(
        "/api/v1/evidence/candidate-facts",
        status_code=201,
        operation_id="createCandidateFact",
        response_model=CandidateFactResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def create_candidate_fact(
        command: EvidenceCandidateCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> CandidateFactResponse:
        del actor
        candidate = evidence.create_candidate_fact(
            fact_type=command.fact_type,
            subject_id=command.subject_id,
            period=command.period,
            value=command.value,
            document_version_id=command.document_version_id,
            document_byte_digest=command.document_byte_digest,
            page_region=command.page_region,
            extraction_method=command.extraction_method,
            extractor_version=command.extractor_version,
            raw_value=command.raw_value,
            normalized_value=command.normalized_value,
        )
        return _candidate_fact_response(candidate)

    @app.get(
        "/api/v1/evidence/candidate-facts/{candidate_fact_id}/review",
        operation_id="getCandidateFactReview",
        response_model=EvidenceReviewPacketResponse,
        responses=_problem_responses(401, 404),
    )
    def get_candidate_fact_review(
        candidate_fact_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> EvidenceReviewPacketResponse:
        del actor
        packet = evidence.review_packet(candidate_fact_id)
        return EvidenceReviewPacketResponse(
            document=_evidence_document_response(packet.document),
            candidate_fact=_candidate_fact_response(packet.candidate),
            conflicts=packet.conflicts,
            approval_history=tuple(
                _approved_fact_response(fact) for fact in packet.approval_history
            ),
            supersession_chain=packet.supersession_chain,
        )

    @app.get(
        "/api/v1/evidence/candidate-facts/{candidate_fact_id}/review-page",
        include_in_schema=False,
        responses=_problem_responses(401, 404),
    )
    def get_candidate_fact_review_page(
        candidate_fact_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> HTMLResponse:
        del actor
        return _evidence_review_page(evidence.review_packet(candidate_fact_id))

    @app.post(
        "/api/v1/evidence/candidate-facts/{candidate_fact_id}/approve",
        status_code=201,
        operation_id="approveCandidateFact",
        response_model=ApprovedFactResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def approve_candidate_fact(
        candidate_fact_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ApprovedFactResponse:
        return _approved_fact_response(
            evidence.approve_candidate_fact(candidate_fact_id, reviewer_id=actor)
        )

    @app.post(
        "/api/v1/evidence/candidate-facts/{candidate_fact_id}/reject",
        status_code=201,
        operation_id="rejectCandidateFact",
        response_model=RejectedFactResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def reject_candidate_fact(
        candidate_fact_id: str,
        command: RejectCandidateFactRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> RejectedFactResponse:
        rejected = evidence.reject_candidate_fact(
            candidate_fact_id,
            reviewer_id=actor,
            reason=command.reason,
        )
        return _rejected_fact_response(rejected)

    @app.post(
        "/api/v1/evidence/approved-facts/{approved_fact_id}/supersede",
        status_code=201,
        operation_id="supersedeApprovedFact",
        response_model=ApprovedFactResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def supersede_approved_fact(
        approved_fact_id: str,
        command: SupersedeApprovedFactRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ApprovedFactResponse:
        replacement = evidence.supersede_approved_fact(
            approved_fact_id,
            candidate_fact_id=command.candidate_fact_id,
            reviewer_id=actor,
        )
        return _approved_fact_response(replacement)

    @app.post(
        "/api/v1/evidence/warehouse-receipts",
        status_code=201,
        operation_id="recordWarehouseReceiptEvidence",
        response_model=WarehouseReceiptEvidenceResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def record_warehouse_receipt_evidence(
        command: WarehouseReceiptEvidenceCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> WarehouseReceiptEvidenceResponse:
        del actor
        record = evidence.record_warehouse_receipt(
            receipt_number=command.receipt_number,
            warehouse_id=command.warehouse_id,
            lot_id=command.lot_id,
            quantity=command.quantity,
            approved_fact_id=command.approved_fact_id,
        )
        return _warehouse_receipt_response(record)

    @app.post(
        "/api/v1/evidence/ownership-claims",
        status_code=201,
        operation_id="recordOwnershipClaim",
        response_model=OwnershipClaimResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def record_ownership_claim(
        command: OwnershipClaimCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> OwnershipClaimResponse:
        del actor
        record = evidence.record_ownership_claim(
            lot_id=command.lot_id,
            period=command.period,
            owner_party_id=command.owner_party_id,
            pledgee_id=command.pledgee_id,
            approved_fact_id=command.approved_fact_id,
        )
        return _ownership_claim_response(record)

    @app.post(
        "/api/v1/evidence/quantity-reconciliations",
        status_code=201,
        operation_id="reconcileLotQuantity",
        response_model=QuantityReconciliationResponse,
        responses=_problem_responses(401, 422),
    )
    def reconcile_lot_quantity(
        command: QuantityReconciliationCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> QuantityReconciliationResponse:
        del actor
        record = evidence.reconcile_lot_quantity(
            lot_id=command.lot_id,
            expected_quantity=command.expected_quantity,
        )
        return _quantity_reconciliation_response(record)

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
        "/api/v1/hedge-liquidity/demo",
        operation_id="evaluateHedgeLiquidityDemo",
        response_model=HedgeLiquidityPreviewResponse,
        description="Non-authoritative preview only; does not publish an S5 stage output.",
        responses=_problem_responses(401, 422),
    )
    def evaluate_hedge_liquidity_demo(
        command: HedgeLiquidityDemoRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> HedgeLiquidityPreviewResponse:
        del actor
        assessment = evaluate_hedge_and_liquidity(command.to_hedge_liquidity_input())
        return HedgeLiquidityPreviewResponse(
            assessment_id=assessment.assessment_id,
            snapshot_id=assessment.snapshot_id,
            result=assessment.result,
            warnings=assessment.warnings,
            reason_codes=assessment.reason_codes,
            authoritativeness="preview",
        )

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/hedge-liquidity",
        operation_id="getHedgeLiquidityAssessment",
        response_model=HedgeLiquidityStageOutputResponse,
        responses=_problem_responses(401, 404),
    )
    def get_hedge_liquidity_assessment(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> HedgeLiquidityStageOutputResponse:
        del actor
        if hedge_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Hedge/liquidity assessment not found")
        output = hedge_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Hedge/liquidity assessment not found")
        return HedgeLiquidityStageOutputResponse.model_validate(output)

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
        expanded_inputs = _expand_policy_required_evidence_inputs(
            command.inputs,
            evidence,
            command.policy_bundle,
            policy_bundle_loader,
        )
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
                        inputs=expanded_inputs,
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
            body={
                **command.model_dump(mode="json"),
                "inputs": [item.model_dump() for item in expanded_inputs],
            },
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
            inputs=expanded_inputs,
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
    store = PostgresIntegrityStore(engine)
    hedge_input_store = PostgresHedgeLiquidityInputStore(engine)
    integrity = IntegrityService(
        store,
        clock=clock,
        snapshot_input_validators={
            "hedge_liquidity_input": hedge_input_store.validate_snapshot_reference,
        },
    )
    evidence = EvidenceService(
        store=PostgresEvidenceStore(engine),
        clock=clock,
        id_factory=new_resource_id,
    )
    hedge_runner = PostgresHedgeLiquidityRunner(
        engine,
        store,
        hedge_input_store,
        clock=clock,
    )
    return create_app(
        clock=clock,
        integrity_service=integrity,
        evidence_service=evidence,
        policy_bundle_loader=store.load_bundle,
        hedge_output_loader=hedge_runner.load_published_output,
    )


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
            "model": ProblemDetails,
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


def _evidence_document_response(document: DocumentVersion) -> EvidenceDocumentResponse:
    return EvidenceDocumentResponse(
        document_id=document.document_id,
        document_version_id=document.resource_id,
        version=document.version,
        filename=document.filename,
        content_type=document.content_type,
        byte_digest=document.byte_digest,
        size_bytes=document.size_bytes,
        created_by=document.created_by,
        created_at=document.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )


def _candidate_fact_response(candidate: CandidateFact) -> CandidateFactResponse:
    return CandidateFactResponse(
        candidate_fact_id=candidate.fact_id,
        approval_state="candidate",
        fact_type=candidate.identity.fact_type,
        subject_id=candidate.identity.subject_id,
        period=candidate.identity.period,
        value=candidate.value,
        page_region=candidate.page_region or "",
        extraction_method=candidate.extraction_method or "",
        extractor_version=candidate.extractor_version or "",
        raw_value=candidate.raw_value or "",
        normalized_value=candidate.normalized_value or "",
        lineage=EvidenceLineageResponse(
            candidate_fact_id=candidate.fact_id,
            document_version_id=candidate.document_version_id,
            document_byte_digest=candidate.document_byte_digest,
        ),
    )


def _approved_fact_response(fact: ApprovedFact) -> ApprovedFactResponse:
    return ApprovedFactResponse(
        approved_fact_id=fact.fact_id,
        approval_state="approved",
        digest=approved_fact_digest(fact),
        lineage=EvidenceLineageResponse(
            candidate_fact_id=fact.candidate_fact_id,
            document_version_id=fact.document_version_id,
            document_byte_digest=fact.document_byte_digest,
        ),
    )


def _rejected_fact_response(fact: RejectedFact) -> RejectedFactResponse:
    return RejectedFactResponse(
        rejected_fact_id=fact.fact_id,
        candidate_fact_id=fact.candidate_fact_id,
        approval_state="rejected",
        reason=fact.reason,
    )


def _evidence_review_page(packet: EvidenceReviewPacket) -> HTMLResponse:
    candidate = packet.candidate
    document = packet.document
    candidate_id = candidate.fact_id
    fact_type = _html(candidate.identity.fact_type)
    period = _html(candidate.identity.period)
    extractor = (
        f"{_html(candidate.extraction_method or '')} {_html(candidate.extractor_version or '')}"
    )
    approve_url = f"/api/v1/evidence/candidate-facts/{candidate_id}/approve"
    reject_url = f"/api/v1/evidence/candidate-facts/{candidate_id}/reject"
    value_json = json.dumps(candidate.value, indent=2, sort_keys=True)
    conflicts = _review_list(packet.conflicts)
    history = _review_list(
        tuple(
            f"{fact.fact_id} | {approved_fact_digest(fact)} | reviewer {fact.approved_by}"
            for fact in packet.approval_history
        )
    )
    chain = _review_list(packet.supersession_chain)
    rejection = (
        f'<p class="warning">Rejected: {_html(packet.rejection.reason)}</p>'
        if packet.rejection is not None
        else ""
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Evidence Review {_html(candidate_id)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5f6b76;
      --line: #d8dee6;
      --surface: #f7f9fb;
      --accent: #146c5d;
      --danger: #a3312a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
      line-height: 1.45;
    }}
    main {{ width: min(1120px, calc(100vw - 32px)); margin: 24px auto 48px; }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.2; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 16px; letter-spacing: 0; }}
    code, pre {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 13px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }}
    dl {{
      display: grid;
      grid-template-columns: minmax(140px, 220px) 1fr;
      gap: 8px 16px;
      margin: 0;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    section {{ padding: 22px 0; border-bottom: 1px solid var(--line); }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
    .panel {{
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    button {{
      min-height: 38px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 0 14px;
      font: inherit;
      cursor: pointer;
    }}
    button[data-action="approve"] {{ background: var(--accent); color: white; }}
    button[data-action="reject"] {{
      background: white;
      color: var(--danger);
      border-color: var(--danger);
    }}
    textarea {{ width: min(520px, 100%); min-height: 76px; resize: vertical; font: inherit; }}
    ul {{ margin: 0; padding-left: 18px; }}
    .muted {{ color: var(--muted); }}
    .warning {{ color: var(--danger); font-weight: 600; }}
    #review-status {{ min-height: 22px; color: var(--muted); }}
    @media (max-width: 760px) {{
      header, .grid {{ display: block; }}
      .panel + .panel {{ margin-top: 16px; }}
      dl {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Evidence Review</h1>
      <p class="muted">{fact_type} · {period}</p>
    </div>
    <code>{_html(candidate_id)}</code>
  </header>

  <section class="grid">
    <div class="panel">
      <h2>Original Document</h2>
      <dl>
        <dt>Filename</dt><dd>{_html(document.filename)}</dd>
        <dt>Content Type</dt><dd>{_html(document.content_type)}</dd>
        <dt>Document Version</dt><dd>{_html(document.resource_id)}</dd>
        <dt>Byte Digest</dt><dd>{_html(document.byte_digest)}</dd>
        <dt>Size</dt><dd>{document.size_bytes} bytes</dd>
      </dl>
    </div>
    <div class="panel">
      <h2>Candidate Fact</h2>
      <dl>
        <dt>Subject</dt><dd>{_html(candidate.identity.subject_id)}</dd>
        <dt>Page/Region</dt><dd>{_html(candidate.page_region or "")}</dd>
        <dt>Extractor</dt><dd>{extractor}</dd>
        <dt>Raw Value</dt><dd>{_html(candidate.raw_value or "")}</dd>
        <dt>Normalized Value</dt><dd>{_html(candidate.normalized_value or "")}</dd>
      </dl>
    </div>
  </section>

  <section>
    <h2>Candidate Value</h2>
    <pre>{_html(value_json)}</pre>
  </section>

  <section class="grid">
    <div>
      <h2>Conflicts</h2>
      {conflicts}
    </div>
    <div>
      <h2>Approval History</h2>
      {history}
    </div>
  </section>

  <section>
    <h2>Supersession Chain</h2>
    {chain}
    {rejection}
  </section>

  <section>
    <h2>Review Actions</h2>
    <div class="actions">
      <button type="button" data-action="approve"
        onclick="submitReview('approve', '{approve_url}')">Approve</button>
      <button type="button" data-action="reject"
        onclick="submitReview('reject', '{reject_url}')">Reject</button>
      <textarea id="reject-reason" placeholder="Required rejection reason"></textarea>
    </div>
    <p id="review-status" role="status"></p>
  </section>
</main>
<script>
async function submitReview(action, url) {{
  const status = document.getElementById("review-status");
  const headers = {{
    "Authorization": "Bearer analyst-demo-token",
    "Content-Type": "application/json"
  }};
  const options = {{ method: "POST", headers, body: "{{}}" }};
  if (action === "reject") {{
    const reason = document.getElementById("reject-reason").value.trim();
    options.body = JSON.stringify({{ reason: reason || "Human reviewer rejected candidate fact" }});
  }}
  status.textContent = action === "approve"
    ? "approveCandidateFact pending"
    : "rejectCandidateFact pending";
  const response = await fetch(url, options);
  status.textContent = response.ok
    ? (action === "approve" ? "approveCandidateFact complete" : "rejectCandidateFact complete")
    : await response.text();
}}
</script>
</body>
</html>
"""
    return HTMLResponse(html)


def _review_list(items: tuple[str, ...]) -> str:
    if not items:
        return '<p class="muted">None</p>'
    return "<ul>" + "".join(f"<li>{_html(item)}</li>" for item in items) + "</ul>"


def _html(value: object) -> str:
    return escape(str(value), quote=True)


def _warehouse_receipt_response(
    record: WarehouseReceiptRecord,
) -> WarehouseReceiptEvidenceResponse:
    return WarehouseReceiptEvidenceResponse(
        receipt_evidence_id=record.resource_id,
        receipt_number=record.receipt.receipt_number,
        warehouse_id=record.receipt.warehouse_id,
        lot_id=record.receipt.lot_id,
        quantity=record.receipt.quantity,
        approved_fact_id=record.receipt.approved_fact_id,
    )


def _ownership_claim_response(record: OwnershipClaimRecord) -> OwnershipClaimResponse:
    return OwnershipClaimResponse(
        ownership_claim_id=record.resource_id,
        lot_id=record.claim.lot_id,
        period=record.claim.period,
        owner_party_id=record.claim.owner_party_id,
        pledgee_id=record.claim.pledgee_id,
        approved_fact_id=record.claim.approved_fact_id,
    )


def _quantity_reconciliation_response(
    record: QuantityReconciliationRecord,
) -> QuantityReconciliationResponse:
    return QuantityReconciliationResponse(
        reconciliation_issue_id=record.resource_id,
        issue_state=record.issue_state,
        lot_id=record.issue.lot_id,
        expected_quantity=record.issue.expected_quantity,
        receipt_quantity=record.issue.receipt_quantity,
        difference=record.issue.difference,
    )


def _validate_evidence_snapshot_inputs(
    inputs: tuple[SnapshotInputReference, ...],
    evidence: EvidenceService,
) -> None:
    for item in inputs:
        if item.resource_type != "approved_fact":
            continue
        actual_digest = evidence.active_approved_fact_digest(item.resource_id)
        if item.digest != actual_digest:
            raise EvidenceControlError("approved fact snapshot input digest mismatch")


def _expand_policy_required_evidence_inputs(
    inputs: tuple[SnapshotInputReference, ...],
    evidence: EvidenceService,
    policy_bundle: BundleReference,
    policy_bundle_loader: Callable[[str], VersionBundle | None] | None,
) -> tuple[SnapshotInputReference, ...]:
    _validate_evidence_snapshot_inputs(inputs, evidence)
    if policy_bundle_loader is None:
        return inputs
    policy = policy_bundle_loader(policy_bundle.resource_id)
    if policy is None:
        return inputs
    if policy.bundle_type is not BundleType.POLICY:
        raise BundleReferenceRejected("policy bundle reference does not point to a policy bundle")
    if policy.digest != policy_bundle.digest:
        raise BundleReferenceRejected("policy bundle digest mismatch")

    expanded = list(inputs)
    existing_approved_ids = {
        item.resource_id for item in expanded if item.resource_type == "approved_fact"
    }
    for identity in _critical_fact_requirements(policy):
        reference = evidence.active_approved_fact_reference(identity)
        if reference.resource_id in existing_approved_ids:
            continue
        expanded.append(
            SnapshotInputReference(
                resource_type="approved_fact",
                resource_id=reference.resource_id,
                digest=reference.digest,
            )
        )
        existing_approved_ids.add(reference.resource_id)
    return tuple(expanded)


def _critical_fact_requirements(policy: VersionBundle) -> tuple[FactIdentity, ...]:
    payload = policy.payload
    if not isinstance(payload, dict):
        return ()
    raw_requirements = payload.get("critical_fact_requirements", ())
    if raw_requirements in (None, ()):
        return ()
    if not isinstance(raw_requirements, list):
        raise EvidenceControlError("policy critical_fact_requirements must be a list")
    requirements: list[FactIdentity] = []
    for raw in raw_requirements:
        if not isinstance(raw, dict):
            raise EvidenceControlError("policy critical fact requirement must be an object")
        fact_type = raw.get("fact_type")
        subject_id = raw.get("subject_id")
        period = raw.get("period")
        if (
            not isinstance(fact_type, str)
            or not isinstance(subject_id, str)
            or not isinstance(period, str)
            or not fact_type
            or not subject_id
            or not period
        ):
            raise EvidenceControlError(
                "policy critical fact requirement must include fact_type, subject_id, and period"
            )
        requirements.append(FactIdentity(fact_type=fact_type, subject_id=subject_id, period=period))
    return tuple(requirements)


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
