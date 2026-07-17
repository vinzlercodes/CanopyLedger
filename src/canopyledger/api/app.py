"""FastAPI application and first functional facility endpoints."""

import base64
import binascii
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from html import escape
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import create_engine

from canopyledger.agents.core import (
    AgentCapabilityDenied,
    AgentError,
    AgentRole,
    AgentRun,
    AgentRunner,
    AgentRunStore,
    DeterministicReplayPlanner,
    InMemoryAgentRunStore,
    Principal,
    default_capability_registry,
)
from canopyledger.agents.postgres import PostgresAgentRunStore
from canopyledger.analytics.copilot import (
    AnalyticsAnswer,
    AnalyticsCopilotService,
    AnalyticsExecution,
    AnalyticsQueryRefused,
    InMemoryAnalyticsExecutor,
)
from canopyledger.analytics.postgres import PostgresAnalyticsExecutor, PostgresAnalyticsRunStore
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
from canopyledger.climate.postgres import (
    PostgresClimateEudrInputStore,
    PostgresClimateEudrRunner,
)
from canopyledger.credit.postgres import (
    PostgresCreditEarlyWarningInputStore,
    PostgresCreditEarlyWarningRunner,
)
from canopyledger.document_intelligence.engine import DocumentIntelligenceError
from canopyledger.document_intelligence.postgres import PostgresDocumentIntelligenceStore
from canopyledger.document_intelligence.service import (
    DocumentExtraction,
    DocumentIntelligenceService,
    InMemoryDocumentIntelligenceStore,
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
from canopyledger.governance.core import (
    DecisionContext,
    DecisionOverride,
    GovernanceError,
    GovernanceService,
    RecommendationClass,
)
from canopyledger.governance.postgres import PostgresGovernanceService
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
from canopyledger.integrity.canonical import (
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)
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
from canopyledger.reporting.core import ReportCompileInput, ReportModelCompiler, ReportPackageKind
from canopyledger.reporting.postgres import PostgresReportService
from canopyledger.reporting.service import (
    InMemoryReportService,
    ReportPackage,
    reference_renderer_manifest,
    reference_report_renderer,
    reference_report_service,
)
from canopyledger.scenario.postgres import (
    PostgresScenarioCapacityInputStore,
    PostgresScenarioCapacityRunner,
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


class EvidenceDocumentRenditionResponse(BaseModel):
    document_version_id: str
    filename: str
    content_type: str
    byte_digest: str
    preview_status: Literal["available", "unsupported"]
    preview_text: str | None
    truncated: bool


class CandidateReconciliationIssueResponse(BaseModel):
    code: str
    lot_id: str
    expected_quantity: str
    receipt_quantity: str
    difference: str
    blocks_freeze: bool


class ExtractedCandidateProvenanceResponse(BaseModel):
    candidate_fact_id: str
    extraction_id: str
    confidence: str
    approval_state: Literal["candidate"]


class DocumentExtractionResponse(BaseModel):
    extraction_id: str
    document_version_id: str
    document_byte_digest: str
    status: Literal["completed"]
    document_type: str
    classification_method: str
    classifier_version: str
    extractor_version: str
    text_digest: str
    candidates: tuple[ExtractedCandidateProvenanceResponse, ...]
    reconciliation_issue: CandidateReconciliationIssueResponse | None
    completed_at: str


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
    is_active: bool
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


class AnalyticsQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1_000)
    snapshot_id: str = Field(min_length=1, max_length=40)
    comparison_snapshot_id: str | None = Field(default=None, min_length=1, max_length=40)


class AnalyticsPlanResponse(BaseModel):
    template_id: str
    facility_id: str
    snapshot_id: str | None
    comparison_snapshot_id: str | None
    row_limit: int


class AnalyticsAnswerResponse(BaseModel):
    query_run_id: str
    question: str
    scope: dict[str, str]
    plan: AnalyticsPlanResponse
    result: tuple[dict[str, Any], ...]
    units: dict[str, str]
    assumptions: tuple[str, ...]
    referenced_views: tuple[str, ...]
    query_digest: str
    lineage: tuple[str, ...]
    data_cutoff: str
    warnings: tuple[str, ...]


class AgentRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(pattern=r"^agr_[a-z0-9-]+$")
    agent_role: AgentRole
    goal: str = Field(min_length=1, max_length=2_000)


class AgentTaskResponse(BaseModel):
    resource_id: str
    title: str
    capability: str
    status: str
    completed_at: datetime | None = None


class AgentTaskPlanResponse(BaseModel):
    resource_id: str
    planner_type: str
    planner_version: str
    goal: str
    planned_capabilities: tuple[str, ...]
    created_at: datetime
    digest: str


class AgentToolCallResponse(BaseModel):
    resource_id: str
    task_id: str
    capability: str
    inputs: dict[str, str]
    authorization: str
    authorization_reason: str
    occurred_at: datetime
    output_digest: str | None = None


class AgentToolResultResponse(BaseModel):
    resource_id: str
    call_id: str
    output_schema: str
    status: str
    output: dict[str, object]
    output_digest: str
    occurred_at: datetime


class AgentHandoffResponse(BaseModel):
    resource_id: str
    source_role: AgentRole
    target_role: str
    approval_request_id: str
    created_at: datetime


class AgentTraceEventResponse(BaseModel):
    sequence: int
    event_type: str
    occurred_at: datetime
    detail: str


class AgentRunResponse(BaseModel):
    resource_id: str
    facility_id: str
    snapshot_id: str
    principal_id: str
    agent_role: AgentRole
    planner_type: str
    planner_version: str
    status: str
    created_at: datetime
    digest: str
    task_plan: AgentTaskPlanResponse | None = None
    tasks: tuple[AgentTaskResponse, ...]
    tool_calls: tuple[AgentToolCallResponse, ...]
    tool_results: tuple[AgentToolResultResponse, ...]
    handoffs: tuple[AgentHandoffResponse, ...]
    trace: tuple[AgentTraceEventResponse, ...]


class AgentRunListResponse(BaseModel):
    items: tuple[AgentRunResponse, ...]


class AgentCapabilityResponse(BaseModel):
    name: str
    risk_level: str
    allowed_agent_roles: tuple[AgentRole, ...]
    allowed_principal_roles: tuple[str, ...]
    input_fields: tuple[str, ...]
    output_schema: str
    requires_human_approval: bool


class AgentCapabilityListResponse(BaseModel):
    items: tuple[AgentCapabilityResponse, ...]


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


class ScenarioCapacityStageOutputResponse(BaseModel):
    stage_output_id: str
    snapshot_id: str
    stage: str
    stage_version: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    scenario: dict[str, Any]
    internal_risk_capacity: dict[str, Any]
    reason_codes: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    output_digest: str


class RecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_id: str
    requested_amount: MoneyInput
    recommendation_class: RecommendationClass
    conditions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    expires_at: datetime
    cbb: MoneyInput | None = None
    contractual_availability: MoneyInput | None = None
    internal_risk_capacity: MoneyInput | None = None
    liquidity_cap: MoneyInput | None = None
    facility_commitment: MoneyInput | None = None
    policy_caps: tuple[MoneyInput, ...] = ()
    outstanding_exposure: MoneyInput | None = None
    approved_unfunded_exposure: MoneyInput | None = None
    cbb_output_digest: str | None = None
    hedge_liquidity_output_digest: str | None = None
    irc_output_digest: str | None = None
    policy_bundle_digest: str | None = None


class ApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_request_id: str
    expires_at: datetime


class ApprovalActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_action_id: str
    final_decision_id: str
    reason: str = Field(min_length=3, max_length=1000)


class OverrideRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    override_id: str
    proposed_exposure_cap: MoneyInput
    reason: str = Field(min_length=3, max_length=1000)
    policy_basis: str = Field(min_length=3, max_length=200)
    expires_at: datetime
    requires_dual_control: Literal[True] = True


class OverrideApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_action_id: str
    reason: str = Field(min_length=3, max_length=1000)


class GovernanceResourceResponse(BaseModel):
    resource_id: str
    digest: str
    kind: str
    status: str | None = None
    superseded_by: str | None = None


class MoneyResponse(BaseModel):
    amount: str
    currency: str


class HedgeContractSpecificationResponse(BaseModel):
    exchange: str
    product_code: str
    contract_symbol: str
    contract_size: str
    contract_size_unit: str
    contract_size_in_exposure_unit: str
    exposure_unit: str
    price_unit: str
    price_unit_factor: str
    tick_size: str
    currency: str
    exercise_style: str
    settlement_rule: str
    calendar_version: str
    delivery_months: tuple[str, ...]
    effective_from: str
    effective_to: str
    source_document_digest: str


class HedgeFuturesPositionResponse(BaseModel):
    product_code: str
    delivery_month: str
    contracts: str
    delta_exposure: str
    pnl: MoneyResponse


class HedgeOptionPositionResponse(BaseModel):
    product_code: str
    delivery_month: str
    option_type: str
    contracts: str
    black76_reference_price: str
    authoritative_price: str
    delta_exposure: str
    value: MoneyResponse
    pnl: MoneyResponse
    delta: str
    gamma: str
    vega: str
    theta: str
    rho: str


class HedgeDeliveryMonthResponse(BaseModel):
    delivery_month: str
    physical_exposure: str
    hedge_delta_exposure: str
    net_price_exposure: str


class HedgeConcentrationResponse(BaseModel):
    delivery_month: str
    physical_concentration: str


class HedgeExposureResponse(BaseModel):
    exposure_unit: str
    gross_physical_exposure: str
    purchase_commitment_exposure: str
    sales_commitment_exposure: str
    net_physical_exposure: str
    futures_exposure: str
    option_delta_equivalent: str
    net_price_exposure: str
    hedge_ratio: str | None
    under_hedge_amount: str
    over_hedge_amount: str
    fx_exposure: MoneyResponse
    fx_exposure_source: MoneyResponse
    basis_exposure: str
    delivery_month_mismatch: tuple[HedgeDeliveryMonthResponse, ...]
    concentration_by_month: tuple[HedgeConcentrationResponse, ...]


class HedgeValuationResponse(BaseModel):
    futures_pnl: MoneyResponse
    option_value: MoneyResponse
    option_pnl: MoneyResponse
    aggregate_greeks: dict[str, str]


class HedgeLiquidityResponse(BaseModel):
    available_cash: MoneyResponse
    undrawn_contractual_availability: MoneyResponse
    total_liquidity_available: MoneyResponse
    one_day_margin_stress: MoneyResponse
    multi_day_margin_stress: MoneyResponse
    timing_mismatch: MoneyResponse
    margin_call_shortfall: MoneyResponse
    liquidity_coverage_ratio: str | None
    required_liquidity_reserve: MoneyResponse
    required_liquidity_coverage_ratio: str


class HedgeLabProjectionResponse(BaseModel):
    stage_output_id: str
    snapshot_id: str
    stage: Literal["hedge_liquidity"]
    stage_version: str
    output_digest: str
    completed_at: datetime
    reason_codes: tuple[str, ...]
    contract_specifications: tuple[HedgeContractSpecificationResponse, ...]
    futures_positions: tuple[HedgeFuturesPositionResponse, ...]
    option_positions: tuple[HedgeOptionPositionResponse, ...]
    exposure: HedgeExposureResponse
    valuation: HedgeValuationResponse
    liquidity: HedgeLiquidityResponse


class ScenarioRegimeResponse(BaseModel):
    name: str
    weight: str


class ScenarioThresholdStabilityResponse(BaseModel):
    lower_confidence_level: str
    upper_confidence_level: str
    lower_value_at_risk: MoneyResponse
    upper_value_at_risk: MoneyResponse
    band_width: MoneyResponse


class HedgeEffectivenessDistributionResponse(BaseModel):
    minimum: str
    median: str
    p95: str
    maximum: str


class ScenarioMonteCarloResponse(BaseModel):
    prng_family: str
    seed_derivation: str
    distribution_assumption: str
    regime_mixture: tuple[ScenarioRegimeResponse, ...]
    seed: int
    path_count: int
    time_steps: int
    thread_count: int
    confidence_level: str
    correlation: str
    correlation_matrix: tuple[tuple[str, ...], ...]
    value_at_risk: MoneyResponse
    expected_shortfall: MoneyResponse
    cbb_deficiency_probability: str
    margin_liquidity_shortfall_probability: str
    expected_collateral_shortfall: MoneyResponse
    expected_margin_liquidity_shortfall: MoneyResponse
    threshold_stability: ScenarioThresholdStabilityResponse
    tail_contribution_by_factor: dict[str, str]
    hedge_effectiveness_distribution: HedgeEffectivenessDistributionResponse


class DeterministicScenarioResponse(BaseModel):
    scenario_id: str
    family: str
    stressed_cbb: MoneyResponse
    cbb_deficiency: MoneyResponse
    margin_liquidity_shortfall: MoneyResponse
    loss: MoneyResponse


class WorstScenarioFamilyResponse(BaseModel):
    family: str
    loss: MoneyResponse


class InternalRiskCapacityResponse(BaseModel):
    risk_buffer: MoneyResponse
    tail_loss_buffer: MoneyResponse
    liquidity_buffer: MoneyResponse
    counterparty_buffer: MoneyResponse
    climate_evidence_buffer: MoneyResponse
    uncapped_irc: MoneyResponse
    irc: MoneyResponse
    cbb: MoneyResponse
    facility_commitment: MoneyResponse


class ScenarioLabProjectionResponse(BaseModel):
    stage_output_id: str
    snapshot_id: str
    stage: Literal["scenario_capacity"]
    stage_version: str
    output_digest: str
    completed_at: datetime
    reason_codes: tuple[str, ...]
    scenario_version: str
    monte_carlo: ScenarioMonteCarloResponse
    deterministic_scenarios: tuple[DeterministicScenarioResponse, ...]
    worst_scenario_families: tuple[WorstScenarioFamilyResponse, ...]
    internal_risk_capacity: InternalRiskCapacityResponse


class ClimateResponse(BaseModel):
    """Strict public schema for frozen M5 projections."""

    model_config = ConfigDict(extra="forbid")


class PointGeometryResponse(ClimateResponse):
    type: Literal["Point"]
    crs: Literal["EPSG:4326"]
    coordinates: tuple[str, str]


class PolygonGeometryResponse(ClimateResponse):
    type: Literal["Polygon"]
    crs: Literal["EPSG:4326"]
    coordinates: tuple[tuple[str, str], ...]


class EvidenceGraphNodeResponse(ClimateResponse):
    node_id: str
    node_type: str
    approved_fact_id: str
    approved_fact_digest: str
    document_version_id: str
    document_byte_digest: str


class EvidenceGraphEdgeResponse(ClimateResponse):
    source_id: str
    target_id: str


class TraceabilityEvidenceGraphResponse(ClimateResponse):
    nodes: tuple[EvidenceGraphNodeResponse, ...]
    edges: tuple[EvidenceGraphEdgeResponse, ...]


class TraceabilityLotResponse(ClimateResponse):
    lot_id: str
    origin_country: str
    geometry: PointGeometryResponse | PolygonGeometryResponse
    geometry_state: Literal["valid"]
    production_date: str | None
    production_date_class: Literal["before_cutoff", "on_or_after_cutoff", "not_reviewed"]
    country_risk_reference: str | None
    evidence_document_digest: str
    evidence_recorded_at: datetime
    freshness_state: Literal["current", "stale"]
    missing_links: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_graph: TraceabilityEvidenceGraphResponse


class OriginConcentrationResponse(ClimateResponse):
    origin_country: str
    lot_count: str
    concentration: str


class TraceabilityResponse(ClimateResponse):
    lots: tuple[TraceabilityLotResponse, ...]
    origin_concentration: tuple[OriginConcentrationResponse, ...]


class ClimateIndicatorResponse(ClimateResponse):
    origin_country: str
    indicator: str
    value: str
    unit: str
    observed_at: str
    provider_id: str
    source_digest: str


class ClimateScenarioResponse(ClimateResponse):
    scenario_id: str
    family: str
    yield_shock: str
    quality_shock: str
    shipment_delay_days: int
    evidence_cost: str
    currency: str


class FinancedEmissionsResponse(ClimateResponse):
    attribution_factor: str
    scope_1: str
    scope_2: str
    scope_3: str | None
    total_available: str
    data_quality_score: int = Field(ge=1, le=5)
    source_period: str
    estimation_method: str
    methodology_version: str
    restatement_lineage: str | None
    missing_data_warnings: tuple[str, ...]


class LegalInterpretationResponse(ClimateResponse):
    bundle_version: str
    production_cutoff: str
    country_risk_reference_version: str
    disclaimer: Literal[
        "Evidence readiness is an operational state, not a legal compliance conclusion."
    ]


class ClimateTraceabilityResultResponse(ClimateResponse):
    eudr_evidence_state: Literal[
        "complete", "incomplete", "conflicting", "stale", "not_reviewed", "review_required"
    ]
    legal_interpretation: LegalInterpretationResponse
    traceability: TraceabilityResponse
    climate_indicators: tuple[ClimateIndicatorResponse, ...]
    climate_scenarios: tuple[ClimateScenarioResponse, ...]
    financed_emissions: FinancedEmissionsResponse


class ClimateTraceabilityProjectionResponse(BaseModel):
    """Published M5 evidence-readiness values, never a compliance conclusion."""

    stage_output_id: str
    snapshot_id: str
    stage: Literal["climate_eudr"]
    stage_version: str
    input_digests: tuple[str, ...]
    legal_interpretation_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    output_digest: str
    completed_at: datetime
    eudr_evidence_state: Literal[
        "complete", "incomplete", "conflicting", "stale", "not_reviewed", "review_required"
    ]
    reason_codes: tuple[str, ...]
    result: ClimateTraceabilityResultResponse


class ClimateTraceabilitySummaryResponse(BaseModel):
    stage_output_id: str
    output_digest: str
    completed_at: datetime
    eudr_evidence_state: Literal[
        "complete", "incomplete", "conflicting", "stale", "not_reviewed", "review_required"
    ]
    reason_codes: tuple[str, ...]
    legal_interpretation_bundle_digest: str


class CreditEarlyWarningProjectionResponse(BaseModel):
    """Published M6 advisory signal; this schema intentionally contains no capacity values."""

    stage_output_id: str
    snapshot_id: str
    stage: Literal["credit_early_warning"]
    stage_version: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    output_digest: str
    completed_at: datetime
    signal_type: Literal["synthetic_deterioration_likelihood"]
    horizon_days: Literal[90]
    probability: str
    band: Literal["low", "moderate", "high"]
    top_reason_codes: tuple[str, ...]
    missing_feature_codes: tuple[str, ...]
    hard_rule_codes: tuple[str, ...]
    model_bundle_digest: str
    advisory_only: Literal[True]
    as_of: datetime


class RecommendationDetailResponse(BaseModel):
    recommendation_id: str
    snapshot_id: str
    author_id: str
    requested_amount: MoneyResponse
    contractual_availability: MoneyResponse
    internal_risk_capacity: MoneyResponse
    recommended_exposure_cap: MoneyResponse
    recommended_incremental_draw: MoneyResponse
    compared_limits: dict[str, str]
    binding_constraint: str
    recommendation_class: str
    conditions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    output_digests: tuple[str, ...]
    policy_bundle_digest: str
    expires_at: datetime
    created_at: datetime
    digest: str


class ApprovalRequestDetailResponse(BaseModel):
    approval_request_id: str
    recommendation: RecommendationDetailResponse
    author_id: str
    requested_by: str
    expires_at: datetime
    created_at: datetime
    digest: str
    expired: bool
    self_approval_prohibited: bool


class ApprovalQueueResponse(BaseModel):
    items: tuple[ApprovalRequestDetailResponse, ...]


class DecisionOverrideDetailResponse(BaseModel):
    override_id: str
    original_decision_id: str
    recommendation_id: str
    requester_id: str
    proposed_exposure_cap: MoneyResponse
    reason: str
    policy_basis: str
    expires_at: datetime
    created_at: datetime
    digest: str
    requires_dual_control: bool
    approval_count: int
    approvals_required: int
    expired: bool


class DecisionOverrideQueueResponse(BaseModel):
    items: tuple[DecisionOverrideDetailResponse, ...]


class DecisionPackResponse(BaseModel):
    snapshot_id: str
    contractual_borrowing_base: MoneyResponse
    contractual_availability: MoneyResponse
    internal_risk_capacity: MoneyResponse
    liquidity_cap: MoneyResponse
    facility_commitment: MoneyResponse
    outstanding_exposure: MoneyResponse
    approved_unfunded_exposure: MoneyResponse
    policy_caps: tuple[MoneyResponse, ...]
    cbb_output_digest: str
    hedge_liquidity_output_digest: str
    irc_output_digest: str
    policy_bundle_digest: str
    hedge_liquidity: dict[str, Any]
    scenario: dict[str, Any]
    climate_traceability: ClimateTraceabilitySummaryResponse
    blockers: tuple[str, ...]
    recommendation: RecommendationDetailResponse | None = None
    final_decision: GovernanceResourceResponse | None = None


class ReportGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(pattern=r"^rpt_[0-9a-f-]+$")
    package_kind: Literal["CURRENT_OFFICIAL", "HISTORICAL_AUDIT"] = "CURRENT_OFFICIAL"


class ReportModelResponse(BaseModel):
    resource_id: str
    package_kind: Literal["CURRENT_OFFICIAL", "HISTORICAL_AUDIT"]
    snapshot_id: str
    decision_id: str
    sections: dict[str, dict[str, Any]]
    artifact_manifest: dict[str, Any]
    digest: str


class ReportArtifactResponse(BaseModel):
    format: Literal["HTML", "PDF"]
    report_model_digest: str
    digest: str
    metadata: dict[str, str]


class ReportPackageResponse(BaseModel):
    package_kind: Literal["CURRENT_OFFICIAL", "HISTORICAL_AUDIT"]
    report_model: ReportModelResponse
    artifacts: tuple[ReportArtifactResponse, ...]


class CollateralLineageResponse(BaseModel):
    collateral_valuation_stage_output_id: str
    collateral_valuation_stage_version: str
    collateral_valuation_output_digest: str
    eligibility_stage_output_id: str
    eligibility_stage_version: str
    eligibility_output_digest: str


class CollateralPageResponse(BaseModel):
    limit: int
    next_cursor: str | None
    total_count: int


class InventoryCollateralRowResponse(BaseModel):
    lot_id: str
    input_quantity: str
    input_quantity_unit: str
    quantity: str
    quantity_unit: str
    unit_conversion_table_version: str
    gross_market_value: MoneyResponse
    net_recovery_value: MoneyResponse
    advanced_value: MoneyResponse


class ReceivableCollateralRowResponse(BaseModel):
    receivable_id: str
    open_amount: MoneyResponse
    facility_value: MoneyResponse
    advanced_value: MoneyResponse
    reason_codes: tuple[str, ...]


class CollateralContributionRowResponse(BaseModel):
    source_type: str
    source_id: str
    amount: MoneyResponse


class CollateralReserveRowResponse(BaseModel):
    reserve_type: str
    amount: MoneyResponse


class CollateralWorkspaceResponse(BaseModel):
    snapshot_id: str
    section: Literal["inventory", "receivables", "contributions", "reserves"]
    inventory_items: tuple[InventoryCollateralRowResponse, ...]
    receivable_items: tuple[ReceivableCollateralRowResponse, ...]
    contribution_items: tuple[CollateralContributionRowResponse, ...]
    reserve_items: tuple[CollateralReserveRowResponse, ...]
    page: CollateralPageResponse
    lineage: CollateralLineageResponse
    reason_codes: tuple[str, ...]


class GovernanceTimelineEventResponse(BaseModel):
    resource_id: str
    resource_type: str
    action: str
    actor_id: str
    occurred_at: datetime
    digest: str
    reason: str | None = None
    status: str | None = None


class GovernanceTimelineResponse(BaseModel):
    snapshot_id: str
    items: tuple[GovernanceTimelineEventResponse, ...]


class EvidenceQueueItemResponse(BaseModel):
    candidate_fact_id: str
    approval_state: str
    fact_type: str
    subject_id: str
    period: str
    normalized_value: str
    document_version_id: str
    document_byte_digest: str
    page_region: str
    extraction_method: str
    extractor_version: str
    conflicts: tuple[str, ...]


class EvidenceReviewQueueResponse(BaseModel):
    items: tuple[EvidenceQueueItemResponse, ...]


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
    document_intelligence_service: DocumentIntelligenceService | None = None,
    analytics_copilot_service: AnalyticsCopilotService | None = None,
    policy_bundle_loader: Callable[[str], VersionBundle | None] | None = None,
    hedge_output_loader: Callable[[str], dict[str, object] | None] | None = None,
    scenario_output_loader: Callable[[str], dict[str, object] | None] | None = None,
    climate_output_loader: Callable[[str], dict[str, object] | None] | None = None,
    credit_early_warning_output_loader: Callable[[str], dict[str, object] | None] | None = None,
    collateral_output_loader: Callable[[str], dict[str, object] | None] | None = None,
    governance_service: GovernanceService | PostgresGovernanceService | None = None,
    report_service: InMemoryReportService | PostgresReportService | None = None,
    agent_runner: AgentRunner | None = None,
    agent_store: AgentRunStore | None = None,
    decision_context_loader: Callable[[str], DecisionContext] | None = None,
    initial_facilities: tuple[FacilityRecord, ...] = (),
    initial_snapshots: tuple[SnapshotManifest, ...] = (),
) -> FastAPI:
    """Create an isolated application instance with functional in-memory adapters."""
    app = FastAPI(title="CanopyLedger API", version="1.0.0")
    facilities: dict[str, FacilityRecord] = {
        facility.resource_id: facility for facility in initial_facilities
    }
    snapshots: dict[str, SnapshotManifest] = {
        snapshot.snapshot_id: snapshot for snapshot in initial_snapshots
    }
    if any(snapshot.facility_id not in facilities for snapshot in snapshots.values()):
        raise ValueError("every seeded snapshot must reference a seeded facility")
    pipeline_start_outbox: list[str] = []
    evidence = evidence_service or EvidenceService(
        store=InMemoryEvidenceStore(),
        clock=clock,
        id_factory=new_resource_id,
    )
    document_intelligence = document_intelligence_service or DocumentIntelligenceService(
        evidence=evidence,
        store=InMemoryDocumentIntelligenceStore(),
        clock=clock,
        id_factory=new_resource_id,
    )
    analytics_copilot = analytics_copilot_service or AnalyticsCopilotService(
        executor=InMemoryAnalyticsExecutor(
            execution=AnalyticsExecution(rows=(), data_cutoff=clock(), lineage=())
        ),
        clock=clock,
    )
    idempotency = IdempotencyLedger()
    governance = governance_service or GovernanceService(clock=clock)
    reports = report_service or reference_report_service()
    bearer = HTTPBearer(auto_error=False)

    def govern(operation: Callable[[GovernanceService], Any]) -> Any:
        if isinstance(governance, PostgresGovernanceService):
            return governance.execute(operation)
        return operation(governance)

    def request_decision_context(
        snapshot_id: str, command: RecommendationCreate
    ) -> DecisionContext:
        values = (
            command.cbb,
            command.contractual_availability,
            command.internal_risk_capacity,
            command.liquidity_cap,
            command.facility_commitment,
            command.outstanding_exposure,
            command.approved_unfunded_exposure,
            command.cbb_output_digest,
            command.hedge_liquidity_output_digest,
            command.irc_output_digest,
            command.policy_bundle_digest,
        )
        if any(item is None for item in values):
            raise GovernanceError(
                "decision calculations are required unless an authoritative "
                "snapshot loader is wired"
            )
        assert command.cbb is not None
        assert command.contractual_availability is not None
        assert command.internal_risk_capacity is not None
        assert command.liquidity_cap is not None
        assert command.facility_commitment is not None
        assert command.outstanding_exposure is not None
        assert command.approved_unfunded_exposure is not None
        assert command.cbb_output_digest is not None
        assert command.hedge_liquidity_output_digest is not None
        assert command.irc_output_digest is not None
        assert command.policy_bundle_digest is not None
        return DecisionContext(
            snapshot_id=snapshot_id,
            cbb=command.cbb.to_money(),
            contractual_availability=command.contractual_availability.to_money(),
            internal_risk_capacity=command.internal_risk_capacity.to_money(),
            liquidity_cap=command.liquidity_cap.to_money(),
            facility_commitment=command.facility_commitment.to_money(),
            policy_caps=tuple(item.to_money() for item in command.policy_caps),
            outstanding_exposure=command.outstanding_exposure.to_money(),
            approved_unfunded_exposure=command.approved_unfunded_exposure.to_money(),
            cbb_output_digest=command.cbb_output_digest,
            hedge_liquidity_output_digest=command.hedge_liquidity_output_digest,
            irc_output_digest=command.irc_output_digest,
            policy_bundle_digest=command.policy_bundle_digest,
        )

    def current_actor(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _Problem(401, "UNAUTHENTICATED", "Valid demo bearer token required")
        actors = {
            "analyst-demo-token": "act_0198a000-0000-7000-8000-000000000001",
            "approver-demo-token": "apr_0198a000-0000-7000-8000-000000000001",
            "second-approver-demo-token": "apr_0198a000-0000-7000-8000-000000000002",
        }
        actor = actors.get(credentials.credentials)
        if actor is None:
            raise _Problem(401, "UNAUTHENTICATED", "Valid demo bearer token required")
        return actor

    def current_credit_approver(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        actor = current_actor(credentials)
        if not actor.startswith("apr_"):
            raise _Problem(403, "FORBIDDEN", "Credit-approver authority is required")
        return actor

    def snapshot_belongs_to_facility(snapshot_id: str, facility_id: str) -> bool:
        if integrity_service is not None:
            manifest = integrity_service.get_snapshot_manifest(snapshot_id)
            if manifest is None:
                return False
            representation = json.loads(manifest.body)
            return (
                isinstance(representation, dict)
                and representation.get("facility_id") == facility_id
            )
        snapshot = snapshots.get(snapshot_id)
        return snapshot is not None and snapshot.facility_id == facility_id

    def agent_snapshot_payload(snapshot_id: str) -> dict[str, object]:
        if integrity_service is not None:
            stored = integrity_service.get_snapshot_manifest(snapshot_id)
            if stored is None:
                raise AgentError("frozen snapshot is not available")
            payload = json.loads(stored.body)
            if not isinstance(payload, dict):
                raise AgentError("frozen snapshot has unsupported representation")
            return payload
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise AgentError("frozen snapshot is not available")
        return _snapshot_representation(snapshot)

    def report_snapshot_payload(snapshot_id: str) -> dict[str, object]:
        """Load the immutable snapshot manifest that can source a report package."""
        if integrity_service is not None:
            stored = integrity_service.get_snapshot_manifest(snapshot_id)
            if stored is None:
                raise _Problem(404, "RESOURCE_NOT_FOUND", "Frozen snapshot not found")
            payload = json.loads(stored.body)
            if not isinstance(payload, dict):
                raise _Problem(409, "STAGE_PUBLICATION_FENCED", "Snapshot manifest is malformed")
            return payload
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Frozen snapshot not found")
        return _snapshot_representation(snapshot)

    def agent_snapshot_read(inputs: Mapping[str, str]) -> Mapping[str, object]:
        payload = agent_snapshot_payload(inputs["snapshot_id"])
        return {
            "snapshot_id": payload["snapshot_id"],
            "facility_id": payload["facility_id"],
            "snapshot_digest": payload["digest"],
        }

    def agent_approved_evidence(inputs: Mapping[str, str]) -> Mapping[str, object]:
        payload = agent_snapshot_payload(inputs["snapshot_id"])
        raw_inputs = payload.get("inputs")
        if not isinstance(raw_inputs, list):
            raise AgentError("frozen snapshot input references are unavailable")
        references = [
            {"resource_id": item.get("resource_id"), "digest": item.get("digest")}
            for item in raw_inputs
            if isinstance(item, dict) and item.get("resource_type") == "approved_fact"
        ]
        return {"snapshot_id": inputs["snapshot_id"], "approved_fact_references": references}

    def agent_stage_output(inputs: Mapping[str, str]) -> Mapping[str, object]:
        loaders = {
            "hedge_liquidity": hedge_output_loader,
            "scenario_capacity": scenario_output_loader,
            "climate_traceability": climate_output_loader,
            "credit_early_warning": credit_early_warning_output_loader,
            "collateral_valuation": collateral_output_loader,
        }
        loader = loaders.get(inputs["stage"])
        if loader is None:
            raise AgentError("requested stage is not available through a typed agent tool")
        output = loader(inputs["snapshot_id"])
        if output is None:
            raise AgentError("requested published stage output is unavailable")
        return output

    def agent_pipeline_start(inputs: Mapping[str, str]) -> Mapping[str, object]:
        agent_snapshot_payload(inputs["snapshot_id"])
        if inputs["snapshot_id"] not in pipeline_start_outbox:
            pipeline_start_outbox.append(inputs["snapshot_id"])
        return {"snapshot_id": inputs["snapshot_id"], "state": "PIPELINE_START_REQUESTED"}

    def agent_pipeline_status(inputs: Mapping[str, str]) -> Mapping[str, object]:
        agent_snapshot_payload(inputs["snapshot_id"])
        return {
            "snapshot_id": inputs["snapshot_id"],
            "start_requested": inputs["snapshot_id"] in pipeline_start_outbox,
        }

    def agent_decision_pack_draft(inputs: Mapping[str, str]) -> Mapping[str, object]:
        recommendation = governance.get_current_recommendation(inputs["snapshot_id"])
        decision = governance.get_current_decision(inputs["snapshot_id"])
        return {
            "snapshot_id": inputs["snapshot_id"],
            "recommendation_id": recommendation.resource_id if recommendation else None,
            "final_decision_id": decision.resource_id if decision else None,
            "draft_only": True,
        }

    def agent_conflicts(inputs: Mapping[str, str]) -> Mapping[str, object]:
        payload = agent_snapshot_payload(inputs["snapshot_id"])
        raw_inputs = payload.get("inputs")
        if not isinstance(raw_inputs, list):
            raise AgentError("frozen snapshot input references are unavailable")
        return {
            "snapshot_id": inputs["snapshot_id"],
            "candidate_input_count": sum(
                1
                for item in raw_inputs
                if isinstance(item, dict) and item.get("resource_type") == "candidate_fact"
            ),
            "conflict_state": "review immutable evidence and pipeline reason codes",
        }

    agent_tools: dict[str, Callable[[Mapping[str, str]], Mapping[str, object]]] = {
        "snapshot.read": agent_snapshot_read,
        "evidence.approved.read": agent_approved_evidence,
        "pipeline.start": agent_pipeline_start,
        "pipeline.status": agent_pipeline_status,
        "stage-output.get": agent_stage_output,
        "decision-pack.draft": agent_decision_pack_draft,
        "approval.route": lambda inputs: {
            "approval_request_id": inputs["approval_request_id"],
            "authority": "human approval routing only",
        },
        "conflict.surface": agent_conflicts,
    }

    agents = agent_runner or AgentRunner(
        registry=default_capability_registry(),
        planner=DeterministicReplayPlanner(),
        store=agent_store or InMemoryAgentRunStore(),
        clock=clock,
        tools=agent_tools,
    )

    def agent_principal(actor: str) -> Principal:
        return Principal(
            actor_id=actor,
            roles=("credit_approver",) if actor.startswith("apr_") else ("analyst",),
        )

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

    @app.exception_handler(DocumentIntelligenceError)
    async def handle_document_intelligence_error(
        request: Request, exc: DocumentIntelligenceError
    ) -> JSONResponse:
        return _problem_response(request, 422, "DOCUMENT_PROCESSING_REJECTED", str(exc))

    @app.exception_handler(AnalyticsQueryRefused)
    async def handle_analytics_query_refused(
        request: Request, exc: AnalyticsQueryRefused
    ) -> JSONResponse:
        return _problem_response(request, 422, "QUERY_REJECTED", str(exc))

    @app.exception_handler(AgentCapabilityDenied)
    async def handle_agent_capability_denied(
        request: Request, exc: AgentCapabilityDenied
    ) -> JSONResponse:
        return _problem_response(request, 403, "AGENT_CAPABILITY_DENIED", str(exc))

    @app.exception_handler(AgentError)
    async def handle_agent_error(request: Request, exc: AgentError) -> JSONResponse:
        return _problem_response(request, 422, "AGENT_RUN_FAILED", str(exc))

    @app.exception_handler(GovernanceError)
    async def handle_governance_error(request: Request, exc: GovernanceError) -> JSONResponse:
        return _problem_response(request, 422, "GOVERNANCE_VALIDATION_FAILED", str(exc))

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
        "/api/v1/facilities/{facility_id}/analytics/answers",
        operation_id="askAnalyticsQuestion",
        response_model=AnalyticsAnswerResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def ask_analytics_question(
        facility_id: str,
        command: AnalyticsQuestionRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> AnalyticsAnswerResponse:
        if not snapshot_belongs_to_facility(command.snapshot_id, facility_id):
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        if command.comparison_snapshot_id is not None and not snapshot_belongs_to_facility(
            command.comparison_snapshot_id, facility_id
        ):
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        answer = analytics_copilot.answer_question(
            actor_id=actor,
            facility_id=facility_id,
            snapshot_id=command.snapshot_id,
            comparison_snapshot_id=command.comparison_snapshot_id,
            question=command.question,
        )
        return _analytics_answer_response(answer)

    @app.post(
        "/api/v1/facilities/{facility_id}/snapshots/{snapshot_id}/agent-runs",
        status_code=201,
        operation_id="startAgentRun",
        response_model=AgentRunResponse,
        responses=_problem_responses(401, 403, 404, 422),
    )
    def start_agent_run(
        facility_id: str,
        snapshot_id: str,
        command: AgentRunStartRequest,
        actor: Annotated[str, Depends(current_actor)],
    ) -> AgentRunResponse:
        if (integrity_service is not None or snapshots) and not snapshot_belongs_to_facility(
            snapshot_id, facility_id
        ):
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        run = agents.run(
            run_id=command.run_id,
            principal=agent_principal(actor),
            role=command.agent_role,
            facility_id=facility_id,
            snapshot_id=snapshot_id,
            goal=command.goal,
        )
        return _agent_run_response(run)

    @app.get(
        "/api/v1/agent-runs/{agent_run_id}",
        operation_id="getAgentRun",
        response_model=AgentRunResponse,
        responses=_problem_responses(401, 403, 404),
    )
    def get_agent_run(
        agent_run_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> AgentRunResponse:
        try:
            run = agents.store.get(agent_run_id)
        except KeyError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Agent run not found") from exc
        if run.principal.actor_id != actor and not actor.startswith("apr_"):
            raise _Problem(403, "FORBIDDEN", "Agent trace is not visible to this principal")
        return _agent_run_response(run)

    @app.get(
        "/api/v1/facilities/{facility_id}/snapshots/{snapshot_id}/agent-runs",
        operation_id="listAgentRuns",
        response_model=AgentRunListResponse,
        responses=_problem_responses(401, 403, 404),
    )
    def list_agent_runs(
        facility_id: str,
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> AgentRunListResponse:
        if (integrity_service is not None or snapshots) and not snapshot_belongs_to_facility(
            snapshot_id, facility_id
        ):
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        visible = tuple(
            run
            for run in agents.store.list_for_snapshot(snapshot_id)
            if run.facility_id == facility_id
            and (run.principal.actor_id == actor or actor.startswith("apr_"))
        )
        return AgentRunListResponse(items=tuple(_agent_run_response(run) for run in visible))

    @app.get(
        "/api/v1/agent-capabilities",
        operation_id="listAgentCapabilities",
        response_model=AgentCapabilityListResponse,
        responses=_problem_responses(401),
    )
    def list_agent_capabilities(
        actor: Annotated[str, Depends(current_actor)],
    ) -> AgentCapabilityListResponse:
        del actor
        return AgentCapabilityListResponse(
            items=tuple(
                AgentCapabilityResponse(
                    name=spec.name,
                    risk_level=spec.risk_level.value,
                    allowed_agent_roles=spec.allowed_agent_roles,
                    allowed_principal_roles=spec.allowed_principal_roles,
                    input_fields=spec.input_fields,
                    output_schema=spec.output_schema,
                    requires_human_approval=spec.requires_human_approval,
                )
                for spec in agents.registry.specifications()
            )
        )

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
        "/api/v1/evidence/documents/{document_version_id}/extractions",
        status_code=201,
        operation_id="extractEvidenceDocument",
        response_model=DocumentExtractionResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def extract_evidence_document(
        document_version_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> DocumentExtractionResponse:
        del actor
        try:
            extraction = document_intelligence.extract(document_version_id)
        except EvidenceControlError as exc:
            if str(exc) == "Document version not found":
                raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
            raise
        return _document_extraction_response(extraction)

    @app.get(
        "/api/v1/evidence/extractions/{extraction_id}",
        operation_id="getEvidenceDocumentExtraction",
        response_model=DocumentExtractionResponse,
        responses=_problem_responses(401, 404),
    )
    def get_evidence_document_extraction(
        extraction_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> DocumentExtractionResponse:
        del actor
        try:
            return _document_extraction_response(document_intelligence.get(extraction_id))
        except DocumentIntelligenceError as exc:
            if str(exc) == "document extraction not found":
                raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
            raise

    @app.get(
        "/api/v1/evidence/candidate-facts/{candidate_fact_id}/extraction-provenance",
        operation_id="getCandidateFactExtractionProvenance",
        response_model=ExtractedCandidateProvenanceResponse,
        responses=_problem_responses(401, 404),
    )
    def get_candidate_fact_extraction_provenance(
        candidate_fact_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ExtractedCandidateProvenanceResponse:
        del actor
        try:
            provenance = document_intelligence.candidate_provenance(candidate_fact_id)
        except DocumentIntelligenceError as exc:
            if str(exc) == "candidate has no document extraction provenance":
                raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
            raise
        return ExtractedCandidateProvenanceResponse(
            candidate_fact_id=provenance.candidate_fact_id,
            extraction_id=provenance.extraction_id,
            confidence=provenance.confidence,
            approval_state="candidate",
        )

    @app.get(
        "/api/v1/evidence/documents/{document_version_id}/rendition",
        operation_id="getEvidenceDocumentRendition",
        response_model=EvidenceDocumentRenditionResponse,
        responses=_problem_responses(401, 404, 422),
    )
    def get_evidence_document_rendition(
        document_version_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> EvidenceDocumentRenditionResponse:
        del actor
        document, content = evidence.original_document(document_version_id)
        return _evidence_document_rendition_response(document, content)

    @app.get(
        "/api/v1/evidence/documents/{document_version_id}/download",
        include_in_schema=False,
        responses=_problem_responses(401, 404, 422),
    )
    def download_evidence_document(
        document_version_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> Response:
        del actor
        document, content = evidence.original_document(document_version_id)
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_download_filename(document.filename)}"'
                ),
                "Content-Security-Policy": "sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

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
        "/api/v1/evidence/review-queue",
        operation_id="getEvidenceReviewQueue",
        response_model=EvidenceReviewQueueResponse,
        responses=_problem_responses(401, 422),
    )
    def get_evidence_review_queue(
        actor: Annotated[str, Depends(current_actor)],
        limit: int = 25,
    ) -> EvidenceReviewQueueResponse:
        del actor
        packets = evidence.review_queue(limit=limit)
        return EvidenceReviewQueueResponse(
            items=tuple(
                EvidenceQueueItemResponse(
                    candidate_fact_id=packet.candidate.fact_id,
                    approval_state="candidate",
                    fact_type=packet.candidate.identity.fact_type,
                    subject_id=packet.candidate.identity.subject_id,
                    period=packet.candidate.identity.period,
                    normalized_value=packet.candidate.normalized_value or "",
                    document_version_id=packet.candidate.document_version_id,
                    document_byte_digest=packet.candidate.document_byte_digest,
                    page_region=packet.candidate.page_region or "",
                    extraction_method=packet.candidate.extraction_method or "",
                    extractor_version=packet.candidate.extractor_version or "",
                    conflicts=packet.conflicts,
                )
                for packet in packets
            )
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

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/hedge-lab",
        operation_id="getHedgeLabProjection",
        response_model=HedgeLabProjectionResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_hedge_lab_projection(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> HedgeLabProjectionResponse:
        del actor
        if hedge_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Hedge/liquidity assessment not found")
        output = hedge_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Hedge/liquidity assessment not found")
        return _hedge_lab_projection_response(snapshot_id=snapshot_id, output=output)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/scenarios",
        operation_id="getScenarioAssessment",
        response_model=ScenarioCapacityStageOutputResponse,
        responses=_problem_responses(401, 404),
    )
    def get_scenario_assessment(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ScenarioCapacityStageOutputResponse:
        del actor
        if scenario_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Scenario assessment not found")
        output = scenario_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Scenario assessment not found")
        return ScenarioCapacityStageOutputResponse.model_validate(output)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/scenario-lab",
        operation_id="getScenarioLabProjection",
        response_model=ScenarioLabProjectionResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_scenario_lab_projection(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ScenarioLabProjectionResponse:
        del actor
        if scenario_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Scenario assessment not found")
        output = scenario_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Scenario assessment not found")
        return _scenario_lab_projection_response(snapshot_id=snapshot_id, output=output)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/climate-traceability",
        operation_id="getClimateTraceabilityProjection",
        response_model=ClimateTraceabilityProjectionResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_climate_traceability_projection(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ClimateTraceabilityProjectionResponse:
        del actor
        if climate_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Climate/traceability assessment not found")
        output = climate_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Climate/traceability assessment not found")
        return _climate_traceability_projection_response(snapshot_id=snapshot_id, output=output)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/credit-early-warning",
        operation_id="getCreditEarlyWarningProjection",
        response_model=CreditEarlyWarningProjectionResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_credit_early_warning_projection(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> CreditEarlyWarningProjectionResponse:
        del actor
        if credit_early_warning_output_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Credit early-warning assessment not found")
        output = credit_early_warning_output_loader(snapshot_id)
        if output is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Credit early-warning assessment not found")
        return _credit_early_warning_projection_response(snapshot_id=snapshot_id, output=output)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/decision-pack",
        operation_id="getSnapshotDecisionPack",
        response_model=DecisionPackResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_snapshot_decision_pack(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> DecisionPackResponse:
        del actor
        if initial_snapshots and snapshot_id not in snapshots:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        if decision_context_loader is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Published decision context is unavailable")
        context = decision_context_loader(snapshot_id)
        hedge = hedge_output_loader(snapshot_id) if hedge_output_loader is not None else None
        scenario = (
            scenario_output_loader(snapshot_id) if scenario_output_loader is not None else None
        )
        if hedge is None or scenario is None:
            raise _Problem(
                409,
                "STAGE_PUBLICATION_FENCED",
                "Required published hedge or scenario output is unavailable",
            )
        climate = climate_output_loader(snapshot_id) if climate_output_loader is not None else None
        if climate is None:
            raise _Problem(
                409,
                "STAGE_PUBLICATION_FENCED",
                "Required published climate/traceability output is unavailable",
            )
        climate_summary = _climate_traceability_summary_response(
            snapshot_id=snapshot_id, output=climate
        )
        decision = governance.get_current_decision(snapshot_id)
        recommendation = governance.get_current_recommendation(snapshot_id)
        return DecisionPackResponse(
            snapshot_id=snapshot_id,
            contractual_borrowing_base=_money_response(context.cbb),
            contractual_availability=_money_response(context.contractual_availability),
            internal_risk_capacity=_money_response(context.internal_risk_capacity),
            liquidity_cap=_money_response(context.liquidity_cap),
            facility_commitment=_money_response(context.facility_commitment),
            outstanding_exposure=_money_response(context.outstanding_exposure),
            approved_unfunded_exposure=_money_response(context.approved_unfunded_exposure),
            policy_caps=tuple(_money_response(value) for value in context.policy_caps),
            cbb_output_digest=context.cbb_output_digest,
            hedge_liquidity_output_digest=context.hedge_liquidity_output_digest,
            irc_output_digest=context.irc_output_digest,
            policy_bundle_digest=context.policy_bundle_digest,
            hedge_liquidity=hedge,
            scenario=scenario,
            climate_traceability=climate_summary,
            blockers=tuple(
                reason for reason in _reason_summary(hedge, scenario).split(", ") if reason
            ),
            recommendation=(
                _recommendation_detail_response(recommendation)
                if recommendation is not None
                else None
            ),
            final_decision=(_final_decision_response(decision) if decision is not None else None),
        )

    @app.post(
        "/api/v1/decisions/{decision_id}/reports",
        status_code=201,
        operation_id="generateDecisionReport",
        response_model=ReportPackageResponse,
        responses=_problem_responses(401, 403, 404, 409, 422),
    )
    def generate_decision_report(
        decision_id: str,
        command: ReportGenerationRequest,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> ReportPackageResponse:
        del actor
        decision = governance.assert_report_eligible(decision_id)
        snapshot = report_snapshot_payload(decision.snapshot_id)
        decision_pack = get_snapshot_decision_pack(decision.snapshot_id, actor="report-worker")
        if (
            decision_pack.final_decision is None
            or decision_pack.final_decision.resource_id != decision_id
        ):
            raise _Problem(
                409, "INVALID_STATE_TRANSITION", "Decision is not current for its snapshot"
            )
        collateral = (
            collateral_output_loader(decision.snapshot_id)
            if collateral_output_loader is not None
            else None
        )
        hedge = (
            hedge_output_loader(decision.snapshot_id) if hedge_output_loader is not None else None
        )
        scenario = (
            scenario_output_loader(decision.snapshot_id)
            if scenario_output_loader is not None
            else None
        )
        climate = (
            climate_output_loader(decision.snapshot_id)
            if climate_output_loader is not None
            else None
        )
        credit = (
            credit_early_warning_output_loader(decision.snapshot_id)
            if credit_early_warning_output_loader is not None
            else None
        )
        if any(item is None for item in (collateral, hedge, scenario, climate, credit)):
            raise _Problem(
                409,
                "STAGE_PUBLICATION_FENCED",
                "All published M1B, M3, M4, M5, and M6 outputs are required for reporting",
            )
        renderer = reference_renderer_manifest()
        source = ReportCompileInput(
            report_id=command.report_id,
            package_kind=ReportPackageKind(command.package_kind),
            decision={
                "resource_id": decision.resource_id,
                "snapshot_id": decision.snapshot_id,
                "status": decision.status.value,
                "superseded_by": decision.superseded_by,
                "digest": decision.digest,
            },
            snapshot=snapshot,
            decision_pack=decision_pack.model_dump(mode="json"),
            stage_outputs={
                "collateral": _report_stage_output("collateral", collateral),
                "hedge": _report_stage_output("hedge", hedge),
                "scenario": _report_stage_output("scenario", scenario),
                "climate": _report_stage_output("climate", climate),
                "credit": _report_stage_output("credit", credit),
            },
            template_version="committee-pack-v1",
            renderer_manifest={
                "renderer": str(renderer["renderer_version"]),
                "font_digest": str(renderer["font_digest"]),
                "locale": str(renderer["locale"]),
                "timezone": str(renderer["timezone"]),
            },
            created_at=clock(),
        )
        return _report_package_response(reports.generate(source))

    @app.get(
        "/api/v1/decisions/{decision_id}/reports",
        operation_id="listDecisionReports",
        response_model=tuple[ReportPackageResponse, ...],
        responses=_problem_responses(401, 404),
    )
    def list_decision_reports(
        decision_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> tuple[ReportPackageResponse, ...]:
        del actor
        return tuple(
            _report_package_response(item) for item in reports.list_for_decision(decision_id)
        )

    @app.get(
        "/api/v1/reports/{report_id}/artifacts/{artifact_format}",
        operation_id="downloadReportArtifact",
        responses=_problem_responses(401, 404),
    )
    def download_report_artifact(
        report_id: str,
        artifact_format: Literal["HTML", "PDF"],
        actor: Annotated[str, Depends(current_actor)],
    ) -> Response:
        del actor
        try:
            package = reports.get(report_id)
        except KeyError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Report package not found") from exc
        artifact = next(
            (item for item in package.artifacts if item.format.value == artifact_format), None
        )
        if artifact is None:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Report artifact not found")
        return Response(
            content=artifact.bytes,
            media_type=(
                "application/pdf" if artifact_format == "PDF" else "text/html; charset=utf-8"
            ),
            headers={"ETag": f'"{artifact.digest}"'},
        )

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/collateral",
        operation_id="getSnapshotCollateral",
        response_model=CollateralWorkspaceResponse,
        responses=_problem_responses(401, 404, 409),
    )
    def get_snapshot_collateral(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
        section: Literal["inventory", "receivables", "contributions", "reserves"] = "inventory",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> CollateralWorkspaceResponse:
        del actor
        if initial_snapshots and snapshot_id not in snapshots:
            raise _Problem(404, "RESOURCE_NOT_FOUND", "Snapshot not found")
        output = (
            collateral_output_loader(snapshot_id) if collateral_output_loader is not None else None
        )
        if output is None:
            raise _Problem(
                409,
                "STAGE_PUBLICATION_FENCED",
                "Published collateral output is unavailable for this snapshot",
            )
        return _collateral_workspace_response(
            snapshot_id=snapshot_id,
            output=output,
            section=section,
            cursor=cursor,
            limit=limit,
        )

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/irc",
        operation_id="getInternalRiskCapacityAssessment",
        response_model=ScenarioCapacityStageOutputResponse,
        responses=_problem_responses(401, 404),
    )
    def get_internal_risk_capacity_assessment(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ScenarioCapacityStageOutputResponse:
        return get_scenario_assessment(snapshot_id, actor)

    @app.post(
        "/api/v1/snapshots/{snapshot_id}/recommendations",
        status_code=201,
        operation_id="createRecommendation",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 403, 422),
    )
    def create_recommendation(
        snapshot_id: str,
        command: RecommendationCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> GovernanceResourceResponse:
        context = (
            decision_context_loader(snapshot_id)
            if decision_context_loader is not None
            else request_decision_context(snapshot_id, command)
        )
        result = govern(
            lambda service: service.create_recommendation(
                context=context,
                recommendation_id=command.recommendation_id,
                author_id=actor,
                requested_amount=command.requested_amount.to_money(),
                recommendation_class=command.recommendation_class,
                conditions=command.conditions,
                reason_codes=command.reason_codes,
                expires_at=command.expires_at,
            )
        )
        return GovernanceResourceResponse(
            resource_id=result.resource_id, digest=result.digest, kind="recommendation"
        )

    @app.post(
        "/api/v1/recommendations/{recommendation_id}/approval-requests",
        status_code=201,
        operation_id="createApprovalRequest",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 403, 422),
    )
    def create_approval_request(
        recommendation_id: str,
        command: ApprovalRequestCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> GovernanceResourceResponse:
        result = govern(
            lambda service: service.create_approval_request(
                approval_request_id=command.approval_request_id,
                recommendation_id=recommendation_id,
                requested_by=actor,
                expires_at=command.expires_at,
            )
        )
        return GovernanceResourceResponse(
            resource_id=result.resource_id, digest=result.digest, kind="approval_request"
        )

    @app.post(
        "/api/v1/approval-requests/{approval_request_id}/approve",
        status_code=201,
        operation_id="approveApprovalRequest",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 403, 422),
    )
    def approve_approval_request(
        approval_request_id: str,
        command: ApprovalActionCreate,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> GovernanceResourceResponse:
        result = govern(
            lambda service: service.approve(
                approval_action_id=command.approval_action_id,
                final_decision_id=command.final_decision_id,
                approval_request_id=approval_request_id,
                approver_id=actor,
                reason=command.reason,
            )
        )
        return GovernanceResourceResponse(
            resource_id=result.resource_id,
            digest=result.digest,
            kind="final_decision",
            status=result.status.value,
        )

    @app.post(
        "/api/v1/approval-requests/{approval_request_id}/reject",
        status_code=201,
        operation_id="rejectApprovalRequest",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 422),
    )
    def reject_approval_request(
        approval_request_id: str,
        command: ApprovalActionCreate,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> GovernanceResourceResponse:
        result = govern(
            lambda service: service.reject(
                approval_action_id=command.approval_action_id,
                final_decision_id=command.final_decision_id,
                approval_request_id=approval_request_id,
                approver_id=actor,
                reason=command.reason,
            )
        )
        return GovernanceResourceResponse(
            resource_id=result.resource_id,
            digest=result.digest,
            kind="final_decision",
            status=result.status.value,
        )

    @app.post(
        "/api/v1/decisions/{decision_id}/override-requests",
        status_code=201,
        operation_id="createDecisionOverride",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 422),
    )
    def create_decision_override(
        decision_id: str,
        command: OverrideRequestCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> GovernanceResourceResponse:
        result = govern(
            lambda service: service.create_override_request(
                override_id=command.override_id,
                original_decision_id=decision_id,
                requester_id=actor,
                proposed_exposure_cap=command.proposed_exposure_cap.to_money(),
                reason=command.reason,
                policy_basis=command.policy_basis,
                expires_at=command.expires_at,
                requires_dual_control=True,
            )
        )
        return GovernanceResourceResponse(
            resource_id=result.resource_id, digest=result.digest, kind="decision_override"
        )

    @app.post(
        "/api/v1/recommendations/{recommendation_id}/override-requests",
        status_code=201,
        operation_id="createRecommendationOverride",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 422),
    )
    def create_recommendation_override(
        recommendation_id: str,
        command: OverrideRequestCreate,
        actor: Annotated[str, Depends(current_actor)],
    ) -> GovernanceResourceResponse:
        recommendation = governance.get_recommendation(recommendation_id)
        decision = governance.get_current_decision(recommendation.snapshot_id)
        if decision is None or decision.recommendation_id != recommendation_id:
            raise GovernanceError(
                "recommendation does not have a current final decision to override"
            )
        return create_decision_override(decision.resource_id, command, actor)

    @app.post(
        "/api/v1/override-requests/{override_id}/approve",
        status_code=201,
        operation_id="approveDecisionOverride",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 422),
    )
    def approve_decision_override(
        override_id: str,
        command: OverrideApprovalCreate,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> GovernanceResourceResponse:
        result = govern(
            lambda service: service.approve_override(
                override_id, actor, command.reason, approval_action_id=command.approval_action_id
            )
        )
        if result is None:
            return GovernanceResourceResponse(
                resource_id=override_id,
                digest="",
                kind="decision_override",
                status="AWAITING_SECOND_APPROVAL",
            )
        return GovernanceResourceResponse(
            resource_id=result.resource_id,
            digest=result.digest,
            kind="final_decision",
            status=result.status.value,
        )

    @app.get(
        "/api/v1/recommendations/{recommendation_id}",
        operation_id="getRecommendation",
        response_model=RecommendationDetailResponse,
        responses=_problem_responses(401, 404),
    )
    def get_recommendation(
        recommendation_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> RecommendationDetailResponse:
        del actor
        try:
            return _recommendation_detail_response(governance.get_recommendation(recommendation_id))
        except GovernanceError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc

    @app.get(
        "/api/v1/approval-requests/{approval_request_id}",
        operation_id="getApprovalRequest",
        response_model=ApprovalRequestDetailResponse,
        responses=_problem_responses(401, 404),
    )
    def get_approval_request(
        approval_request_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> ApprovalRequestDetailResponse:
        del actor
        try:
            request = governance.get_approval_request(approval_request_id)
            recommendation = governance.get_recommendation(request.recommendation_id)
        except GovernanceError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
        return _approval_request_detail_response(request, recommendation, now=clock())

    @app.get(
        "/api/v1/approval-requests",
        operation_id="getApprovalQueue",
        response_model=ApprovalQueueResponse,
        responses=_problem_responses(401, 403),
    )
    def get_approval_queue(
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> ApprovalQueueResponse:
        del actor
        items: list[ApprovalRequestDetailResponse] = []
        for request in governance.list_approval_requests():
            recommendation = governance.get_recommendation(request.recommendation_id)
            current = governance.get_current_decision(recommendation.snapshot_id)
            if current is not None and current.recommendation_id == recommendation.resource_id:
                continue
            items.append(_approval_request_detail_response(request, recommendation, now=clock()))
        return ApprovalQueueResponse(items=tuple(items))

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/override-requests",
        operation_id="getDecisionOverrideQueue",
        response_model=DecisionOverrideQueueResponse,
        responses=_problem_responses(401, 403),
    )
    def get_decision_override_queue(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> DecisionOverrideQueueResponse:
        del actor
        items = []
        for override in governance.list_overrides():
            recommendation = governance.get_recommendation(override.recommendation_id)
            if recommendation.snapshot_id == snapshot_id:
                items.append(_decision_override_detail_response(override, now=clock()))
        return DecisionOverrideQueueResponse(items=tuple(items))

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/governance-timeline",
        operation_id="getGovernanceTimeline",
        response_model=GovernanceTimelineResponse,
        responses=_problem_responses(401, 403),
    )
    def get_governance_timeline(
        snapshot_id: str,
        actor: Annotated[str, Depends(current_credit_approver)],
    ) -> GovernanceTimelineResponse:
        del actor
        return GovernanceTimelineResponse(
            snapshot_id=snapshot_id,
            items=tuple(
                GovernanceTimelineEventResponse(
                    resource_id=item.resource_id,
                    resource_type=item.resource_type,
                    action=item.action,
                    actor_id=item.actor_id,
                    occurred_at=item.occurred_at,
                    digest=item.digest,
                    reason=item.reason,
                    status=item.status,
                )
                for item in governance.list_timeline_events(snapshot_id)
            ),
        )

    @app.get(
        "/api/v1/override-requests/{override_id}",
        operation_id="getDecisionOverride",
        response_model=DecisionOverrideDetailResponse,
        responses=_problem_responses(401, 404),
    )
    def get_decision_override(
        override_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> DecisionOverrideDetailResponse:
        del actor
        try:
            return _decision_override_detail_response(
                governance.get_override(override_id), now=clock()
            )
        except GovernanceError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc

    @app.get(
        "/api/v1/decisions/{decision_id}",
        operation_id="getFinalDecision",
        response_model=GovernanceResourceResponse,
        responses=_problem_responses(401, 404),
    )
    def get_final_decision(
        decision_id: str,
        actor: Annotated[str, Depends(current_actor)],
    ) -> GovernanceResourceResponse:
        del actor
        try:
            decision = governance.get_decision(decision_id)
        except GovernanceError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
        return GovernanceResourceResponse(
            resource_id=decision.resource_id,
            digest=decision.digest,
            kind="final_decision",
            status=decision.status.value,
            superseded_by=decision.superseded_by,
        )

    @app.get(
        "/ui/approval-workspace",
        include_in_schema=False,
        responses=_problem_responses(401),
    )
    def approval_workspace(
        actor: Annotated[str, Depends(current_actor)],
        recommendation_id: str | None = None,
        decision_id: str | None = None,
    ) -> HTMLResponse:
        del actor
        try:
            decision = governance.get_decision(decision_id) if decision_id is not None else None
            recommendation = (
                governance.get_recommendation(decision.recommendation_id)
                if decision is not None
                else (
                    governance.get_recommendation(recommendation_id)
                    if recommendation_id is not None
                    else None
                )
            )
            override = (
                governance.get_override(decision.override_id)
                if decision is not None and decision.override_id is not None
                else None
            )
        except GovernanceError as exc:
            raise _Problem(404, "RESOURCE_NOT_FOUND", str(exc)) from exc
        context = (
            decision_context_loader(recommendation.snapshot_id)
            if recommendation is not None and decision_context_loader is not None
            else None
        )
        hedge = (
            hedge_output_loader(recommendation.snapshot_id)
            if recommendation is not None and hedge_output_loader is not None
            else None
        )
        scenario = (
            scenario_output_loader(recommendation.snapshot_id)
            if recommendation is not None and scenario_output_loader is not None
            else None
        )
        return HTMLResponse(
            _approval_workspace_page(
                recommendation=recommendation,
                context=context,
                decision=decision,
                override=override,
                blockers=_reason_summary(hedge, scenario),
            )
        )

    @app.get("/ui/facility-cockpit", include_in_schema=False, responses=_problem_responses(401))
    def facility_cockpit(
        actor: Annotated[str, Depends(current_actor)],
        snapshot_id: str | None = None,
    ) -> HTMLResponse:
        del actor
        if snapshot_id is None:
            return HTMLResponse(_facility_cockpit_page())
        if decision_context_loader is None:
            return HTMLResponse(_facility_cockpit_page(error="No authoritative snapshot loader"))
        context = decision_context_loader(snapshot_id)
        decision = governance.get_current_decision(snapshot_id)
        recommendation = (
            governance.get_recommendation(decision.recommendation_id)
            if decision is not None
            else None
        )
        hedge = hedge_output_loader(snapshot_id) if hedge_output_loader is not None else None
        scenario = (
            scenario_output_loader(snapshot_id) if scenario_output_loader is not None else None
        )
        return HTMLResponse(
            _facility_cockpit_page(
                snapshot_id=snapshot_id,
                context=context,
                recommendation=recommendation,
                decision=decision,
                hedge=hedge,
                scenario=scenario,
            )
        )

    @app.get("/ui/collateral-workspace", include_in_schema=False, responses=_problem_responses(401))
    def collateral_workspace(
        actor: Annotated[str, Depends(current_actor)],
        snapshot_id: str | None = None,
    ) -> HTMLResponse:
        del actor
        output = (
            collateral_output_loader(snapshot_id)
            if (snapshot_id is not None and collateral_output_loader is not None)
            else None
        )
        return HTMLResponse(
            _analytical_workspace_page(
                title="Collateral workspace",
                snapshot_id=snapshot_id,
                output=output,
                description=(
                    "Inventory lots, receivables, eligibility, haircuts, reserves, "
                    "reconciliation issues, and evidence lineage."
                ),
            )
        )

    @app.get("/ui/hedge-lab", include_in_schema=False, responses=_problem_responses(401))
    def hedge_lab(
        actor: Annotated[str, Depends(current_actor)],
        snapshot_id: str | None = None,
    ) -> HTMLResponse:
        del actor
        output = (
            hedge_output_loader(snapshot_id)
            if (snapshot_id is not None and hedge_output_loader is not None)
            else None
        )
        return HTMLResponse(
            _analytical_workspace_page(
                title="Hedge Lab",
                snapshot_id=snapshot_id,
                output=output,
                description=(
                    "Physical exposure, futures/options hedge effects, variation margin, "
                    "and liquidity coverage."
                ),
            )
        )

    @app.get("/ui/scenario-lab", include_in_schema=False, responses=_problem_responses(401))
    def scenario_lab(
        actor: Annotated[str, Depends(current_actor)],
        snapshot_id: str | None = None,
    ) -> HTMLResponse:
        del actor
        output = (
            scenario_output_loader(snapshot_id)
            if (snapshot_id is not None and scenario_output_loader is not None)
            else None
        )
        return HTMLResponse(
            _analytical_workspace_page(
                title="Scenario Lab",
                snapshot_id=snapshot_id,
                output=output,
                description=(
                    "Deterministic stresses, Monte Carlo tail metrics, and Internal Risk Capacity."
                ),
            )
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
    scenario_input_store = PostgresScenarioCapacityInputStore(engine)
    climate_input_store = PostgresClimateEudrInputStore(engine)
    credit_input_store = PostgresCreditEarlyWarningInputStore(engine)
    integrity = IntegrityService(
        store,
        clock=clock,
        snapshot_input_validators={
            "hedge_liquidity_input": hedge_input_store.validate_snapshot_reference,
            "scenario_capacity_input": scenario_input_store.validate_snapshot_reference,
            "climate_eudr_input": climate_input_store.validate_snapshot_reference,
            "credit_early_warning_input": credit_input_store.validate_snapshot_reference,
        },
    )
    evidence = EvidenceService(
        store=PostgresEvidenceStore(engine),
        clock=clock,
        id_factory=new_resource_id,
    )
    document_intelligence = DocumentIntelligenceService(
        evidence=evidence,
        store=PostgresDocumentIntelligenceStore(engine),
        clock=clock,
        id_factory=new_resource_id,
    )
    analytics_copilot = AnalyticsCopilotService(
        executor=PostgresAnalyticsExecutor(engine, clock=clock),
        run_store=PostgresAnalyticsRunStore(engine),
        clock=clock,
    )
    hedge_runner = PostgresHedgeLiquidityRunner(
        engine,
        store,
        hedge_input_store,
        clock=clock,
    )
    scenario_runner = PostgresScenarioCapacityRunner(
        engine, store, scenario_input_store, clock=clock
    )
    climate_runner = PostgresClimateEudrRunner(engine, store, climate_input_store, clock=clock)
    credit_runner = PostgresCreditEarlyWarningRunner(engine, store, credit_input_store, clock=clock)
    governance = PostgresGovernanceService(engine, clock=clock)
    report_service = PostgresReportService(
        engine,
        compiler=ReportModelCompiler(),
        renderer=reference_report_renderer(),
    )
    return create_app(
        clock=clock,
        integrity_service=integrity,
        evidence_service=evidence,
        document_intelligence_service=document_intelligence,
        analytics_copilot_service=analytics_copilot,
        policy_bundle_loader=store.load_bundle,
        hedge_output_loader=hedge_runner.load_published_output,
        scenario_output_loader=scenario_runner.load_published_output,
        climate_output_loader=climate_runner.load_published_output,
        credit_early_warning_output_loader=credit_runner.load_published_output,
        collateral_output_loader=governance.load_collateral_view,
        governance_service=governance,
        report_service=report_service,
        decision_context_loader=governance.load_authoritative_context,
        agent_store=PostgresAgentRunStore(engine),
    )


class _Problem(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail


def _analytics_answer_response(answer: AnalyticsAnswer) -> AnalyticsAnswerResponse:
    return AnalyticsAnswerResponse(
        query_run_id=answer.query_run_id,
        question=answer.question,
        scope=dict(answer.scope),
        plan=AnalyticsPlanResponse(
            template_id=answer.plan.template_id,
            facility_id=answer.plan.facility_id,
            snapshot_id=answer.plan.snapshot_id,
            comparison_snapshot_id=answer.plan.comparison_snapshot_id,
            row_limit=answer.plan.row_limit,
        ),
        result=tuple(dict(row) for row in answer.result),
        units=dict(answer.units),
        assumptions=answer.assumptions,
        referenced_views=answer.referenced_views,
        query_digest=answer.query_digest,
        lineage=answer.lineage,
        data_cutoff=canonical_timestamp(answer.data_cutoff),
        warnings=answer.warnings,
    )


def _agent_run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        resource_id=run.resource_id,
        facility_id=run.facility_id,
        snapshot_id=run.snapshot_id,
        principal_id=run.principal.actor_id,
        agent_role=run.agent_role,
        planner_type=run.planner_type,
        planner_version=run.planner_version,
        status=run.status,
        created_at=run.created_at,
        digest=run.digest,
        task_plan=(
            AgentTaskPlanResponse(
                resource_id=run.task_plan.resource_id,
                planner_type=run.task_plan.planner_type,
                planner_version=run.task_plan.planner_version,
                goal=run.task_plan.goal,
                planned_capabilities=run.task_plan.planned_capabilities,
                created_at=run.task_plan.created_at,
                digest=run.task_plan.digest,
            )
            if run.task_plan is not None
            else None
        ),
        tasks=tuple(
            AgentTaskResponse(
                resource_id=item.resource_id,
                title=item.title,
                capability=item.capability,
                status=item.status,
                completed_at=item.completed_at,
            )
            for item in run.tasks
        ),
        tool_calls=tuple(
            AgentToolCallResponse(
                resource_id=item.resource_id,
                task_id=item.task_id,
                capability=item.capability,
                inputs=dict(item.inputs),
                authorization=item.authorization,
                authorization_reason=item.authorization_reason,
                occurred_at=item.occurred_at,
                output_digest=item.output_digest,
            )
            for item in run.tool_calls
        ),
        tool_results=tuple(
            AgentToolResultResponse(
                resource_id=item.resource_id,
                call_id=item.call_id,
                output_schema=item.output_schema,
                status=item.status,
                output=dict(item.output),
                output_digest=item.output_digest,
                occurred_at=item.occurred_at,
            )
            for item in run.tool_results
        ),
        handoffs=tuple(
            AgentHandoffResponse(
                resource_id=item.resource_id,
                source_role=item.source_role,
                target_role=item.target_role,
                approval_request_id=item.approval_request_id,
                created_at=item.created_at,
            )
            for item in run.handoffs
        ),
        trace=tuple(
            AgentTraceEventResponse(
                sequence=item.sequence,
                event_type=item.event_type,
                occurred_at=item.occurred_at,
                detail=item.detail,
            )
            for item in run.trace
        ),
    )


def _problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {
        status: {
            "description": "Problem Details",
            "model": ProblemDetails,
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


def _money_response(value: Money) -> MoneyResponse:
    return MoneyResponse(amount=f"{value.quantized().amount:.2f}", currency=value.currency)


def _collateral_workspace_response(
    *,
    snapshot_id: str,
    output: dict[str, object],
    section: Literal["inventory", "receivables", "contributions", "reserves"],
    cursor: str | None,
    limit: int,
) -> CollateralWorkspaceResponse:
    """Expose frozen M1B stage values as typed, server-paginated UI projections."""
    try:
        valuation = _collateral_stage(output, "collateral_valuation", snapshot_id)
        eligibility = _collateral_stage(output, "eligibility_and_reserves", snapshot_id)
        inventory = tuple(
            sorted(
                _collateral_rows(valuation["result"], "inventory", InventoryCollateralRowResponse),
                key=lambda item: item.lot_id,
            )
        )
        receivables = tuple(
            sorted(
                _collateral_rows(
                    valuation["result"], "receivables", ReceivableCollateralRowResponse
                ),
                key=lambda item: item.receivable_id,
            )
        )
        contributions = tuple(
            sorted(
                _collateral_rows(
                    eligibility["result"], "contributions", CollateralContributionRowResponse
                ),
                key=lambda item: (item.source_type, item.source_id),
            )
        )
        reserves = tuple(
            sorted(
                _collateral_rows(eligibility["result"], "reserves", CollateralReserveRowResponse),
                key=lambda item: item.reserve_type,
            )
        )
        reason_codes = tuple(
            sorted(
                set(_collateral_reason_codes(valuation))
                | set(_collateral_reason_codes(eligibility))
            )
        )
        lineage = CollateralLineageResponse(
            collateral_valuation_stage_output_id=_collateral_string(valuation, "stage_output_id"),
            collateral_valuation_stage_version=_collateral_string(valuation, "stage_version"),
            collateral_valuation_output_digest=_collateral_string(valuation, "output_digest"),
            eligibility_stage_output_id=_collateral_string(eligibility, "stage_output_id"),
            eligibility_stage_version=_collateral_string(eligibility, "stage_version"),
            eligibility_output_digest=_collateral_string(eligibility, "output_digest"),
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise _Problem(
            409,
            "STAGE_PUBLICATION_FENCED",
            "Published collateral output is incomplete or has an unsupported schema",
        ) from exc

    if section == "inventory":
        inventory_page_items, page = _collateral_page(inventory, cursor, limit)
        return CollateralWorkspaceResponse(
            snapshot_id=snapshot_id,
            section=section,
            inventory_items=inventory_page_items,
            receivable_items=(),
            contribution_items=(),
            reserve_items=(),
            page=page,
            lineage=lineage,
            reason_codes=reason_codes,
        )
    if section == "receivables":
        receivable_page_items, page = _collateral_page(receivables, cursor, limit)
        return CollateralWorkspaceResponse(
            snapshot_id=snapshot_id,
            section=section,
            inventory_items=(),
            receivable_items=receivable_page_items,
            contribution_items=(),
            reserve_items=(),
            page=page,
            lineage=lineage,
            reason_codes=reason_codes,
        )
    if section == "contributions":
        contribution_page_items, page = _collateral_page(contributions, cursor, limit)
        return CollateralWorkspaceResponse(
            snapshot_id=snapshot_id,
            section=section,
            inventory_items=(),
            receivable_items=(),
            contribution_items=contribution_page_items,
            reserve_items=(),
            page=page,
            lineage=lineage,
            reason_codes=reason_codes,
        )
    reserve_page_items, page = _collateral_page(reserves, cursor, limit)
    return CollateralWorkspaceResponse(
        snapshot_id=snapshot_id,
        section=section,
        inventory_items=(),
        receivable_items=(),
        contribution_items=(),
        reserve_items=reserve_page_items,
        page=page,
        lineage=lineage,
        reason_codes=reason_codes,
    )


def _collateral_stage(output: dict[str, object], stage: str, snapshot_id: str) -> dict[str, object]:
    value = output.get(stage)
    if not isinstance(value, dict) or value.get("stage") != stage:
        raise ValueError("missing frozen collateral stage")
    if value.get("snapshot_id") != snapshot_id:
        raise ValueError("collateral stage is not bound to selected snapshot")
    if not isinstance(value.get("result"), dict):
        raise ValueError("collateral stage result is missing")
    return value


def _collateral_rows[RowModel: BaseModel](
    result: object, field: str, model: type[RowModel]
) -> tuple[RowModel, ...]:
    if not isinstance(result, dict):
        raise ValueError("collateral result is missing")
    raw_rows = result.get(field)
    if not isinstance(raw_rows, list):
        raise ValueError("collateral row collection is missing")
    return tuple(model.model_validate(row) for row in raw_rows)


def _collateral_page[RowModel: BaseModel](
    items: tuple[RowModel, ...], cursor: str | None, limit: int
) -> tuple[tuple[RowModel, ...], CollateralPageResponse]:
    offset = _collateral_cursor_offset(cursor)
    if offset > len(items):
        raise _Problem(422, "INVALID_CURSOR", "Collateral cursor is outside this frozen section")
    page_items = items[offset : offset + limit]
    next_offset = offset + len(page_items)
    return page_items, CollateralPageResponse(
        limit=limit,
        next_cursor=str(next_offset) if next_offset < len(items) else None,
        total_count=len(items),
    )


def _collateral_reason_codes(stage: dict[str, object]) -> tuple[str, ...]:
    value = stage.get("reason_codes")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("collateral reason codes are missing")
    return tuple(value)


def _collateral_string(stage: dict[str, object], field: str) -> str:
    value = stage.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"collateral {field} is missing")
    return value


def _collateral_cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isdecimal():
        raise _Problem(422, "INVALID_CURSOR", "Collateral cursor must be a non-negative integer")
    return int(cursor)


def _hedge_lab_projection_response(
    *, snapshot_id: str, output: dict[str, object]
) -> HedgeLabProjectionResponse:
    """Present frozen S5 values in a typed read model without recalculation."""
    try:
        stage = _published_stage(output, snapshot_id, "hedge_liquidity")
        result = _published_mapping(stage, "result")
        exposure = _published_mapping(result, "exposure")
        valuation = _published_mapping(result, "valuation")
        liquidity = _published_mapping(result, "liquidity")
        valuation_currency = _published_string(valuation, "currency")
        liquidity_currency = _published_string(liquidity, "currency")
        source_currency = _published_string(exposure, "fx_exposure_source_currency")
        return HedgeLabProjectionResponse(
            stage_output_id=_published_string(stage, "stage_output_id"),
            snapshot_id=_published_string(stage, "snapshot_id"),
            stage="hedge_liquidity",
            stage_version=_published_string(stage, "stage_version"),
            output_digest=_published_string(stage, "output_digest"),
            completed_at=_published_datetime(stage, "completed_at"),
            reason_codes=_published_strings(stage, "reason_codes"),
            contract_specifications=tuple(
                HedgeContractSpecificationResponse.model_validate(item)
                for item in _published_rows(result, "contract_specifications")
            ),
            futures_positions=tuple(
                HedgeFuturesPositionResponse(
                    product_code=_published_string(item, "product_code"),
                    delivery_month=_published_string(item, "delivery_month"),
                    contracts=_published_string(item, "contracts"),
                    delta_exposure=_published_string(item, "delta_exposure"),
                    pnl=_published_money(item.get("pnl"), valuation_currency),
                )
                for item in _published_rows(result, "futures_positions")
            ),
            option_positions=tuple(
                HedgeOptionPositionResponse(
                    product_code=_published_string(item, "product_code"),
                    delivery_month=_published_string(item, "delivery_month"),
                    option_type=_published_string(item, "option_type"),
                    contracts=_published_string(item, "contracts"),
                    black76_reference_price=_published_string(item, "black76_reference_price"),
                    authoritative_price=_published_string(item, "authoritative_price"),
                    delta_exposure=_published_string(item, "delta_exposure"),
                    value=_published_money(item.get("value"), valuation_currency),
                    pnl=_published_money(item.get("pnl"), valuation_currency),
                    delta=_published_string(item, "delta"),
                    gamma=_published_string(item, "gamma"),
                    vega=_published_string(item, "vega"),
                    theta=_published_string(item, "theta"),
                    rho=_published_string(item, "rho"),
                )
                for item in _published_rows(result, "option_positions")
            ),
            exposure=HedgeExposureResponse(
                exposure_unit=_published_string(exposure, "exposure_unit"),
                gross_physical_exposure=_published_string(exposure, "gross_physical_exposure"),
                purchase_commitment_exposure=_published_string(
                    exposure, "purchase_commitment_exposure"
                ),
                sales_commitment_exposure=_published_string(exposure, "sales_commitment_exposure"),
                net_physical_exposure=_published_string(exposure, "net_physical_exposure"),
                futures_exposure=_published_string(exposure, "futures_exposure"),
                option_delta_equivalent=_published_string(exposure, "option_delta_equivalent"),
                net_price_exposure=_published_string(exposure, "net_price_exposure"),
                hedge_ratio=_published_optional_string(exposure, "hedge_ratio"),
                under_hedge_amount=_published_string(exposure, "under_hedge_amount"),
                over_hedge_amount=_published_string(exposure, "over_hedge_amount"),
                fx_exposure=_published_money(
                    exposure.get("fx_exposure"), _published_string(exposure, "fx_exposure_currency")
                ),
                fx_exposure_source=_published_money(
                    exposure.get("fx_exposure_source_amount"), source_currency
                ),
                basis_exposure=_published_string(exposure, "basis_exposure"),
                delivery_month_mismatch=tuple(
                    HedgeDeliveryMonthResponse.model_validate(item)
                    for item in _published_rows(exposure, "delivery_month_mismatch")
                ),
                concentration_by_month=tuple(
                    HedgeConcentrationResponse.model_validate(item)
                    for item in _published_rows(exposure, "concentration_by_month")
                ),
            ),
            valuation=HedgeValuationResponse(
                futures_pnl=_published_money(valuation.get("futures_pnl"), valuation_currency),
                option_value=_published_money(valuation.get("option_value"), valuation_currency),
                option_pnl=_published_money(valuation.get("option_pnl"), valuation_currency),
                aggregate_greeks=_published_string_mapping(valuation, "aggregate_greeks"),
            ),
            liquidity=HedgeLiquidityResponse(
                available_cash=_published_money(
                    liquidity.get("available_cash"), liquidity_currency
                ),
                undrawn_contractual_availability=_published_money(
                    liquidity.get("undrawn_contractual_availability"), liquidity_currency
                ),
                total_liquidity_available=_published_money(
                    liquidity.get("total_liquidity_available"), liquidity_currency
                ),
                one_day_margin_stress=_published_money(
                    liquidity.get("one_day_margin_stress"), liquidity_currency
                ),
                multi_day_margin_stress=_published_money(
                    liquidity.get("multi_day_margin_stress"), liquidity_currency
                ),
                timing_mismatch=_published_money(
                    liquidity.get("timing_mismatch"), liquidity_currency
                ),
                margin_call_shortfall=_published_money(
                    liquidity.get("margin_call_shortfall"), liquidity_currency
                ),
                liquidity_coverage_ratio=_published_optional_string(
                    liquidity, "liquidity_coverage_ratio"
                ),
                required_liquidity_reserve=_published_money(
                    liquidity.get("required_liquidity_reserve"), liquidity_currency
                ),
                required_liquidity_coverage_ratio=_published_string(
                    liquidity, "required_liquidity_coverage_ratio"
                ),
            ),
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise _Problem(
            409,
            "STAGE_PUBLICATION_FENCED",
            "Published hedge/liquidity output is incomplete or has an unsupported schema",
        ) from exc


def _scenario_lab_projection_response(
    *, snapshot_id: str, output: dict[str, object]
) -> ScenarioLabProjectionResponse:
    """Present frozen S6 values in a typed read model without recalculation."""
    try:
        stage = _published_stage(output, snapshot_id, "scenario_capacity")
        scenario = _published_mapping(stage, "scenario")
        monte_carlo = _published_mapping(scenario, "monte_carlo")
        threshold = _published_mapping(monte_carlo, "threshold_stability")
        irc = _published_mapping(scenario, "internal_risk_capacity")
        currency = _published_string(scenario, "currency")
        return ScenarioLabProjectionResponse(
            stage_output_id=_published_string(stage, "stage_output_id"),
            snapshot_id=_published_string(stage, "snapshot_id"),
            stage="scenario_capacity",
            stage_version=_published_string(stage, "stage_version"),
            output_digest=_published_string(stage, "output_digest"),
            completed_at=_published_datetime(stage, "completed_at"),
            reason_codes=_published_strings(stage, "reason_codes"),
            scenario_version=_published_string(scenario, "scenario_version"),
            monte_carlo=ScenarioMonteCarloResponse(
                prng_family=_published_string(monte_carlo, "prng_family"),
                seed_derivation=_published_string(monte_carlo, "seed_derivation"),
                distribution_assumption=_published_string(monte_carlo, "distribution_assumption"),
                regime_mixture=tuple(
                    ScenarioRegimeResponse.model_validate(item)
                    for item in _published_rows(monte_carlo, "regime_mixture")
                ),
                seed=_published_integer(monte_carlo, "seed"),
                path_count=_published_integer(monte_carlo, "path_count"),
                time_steps=_published_integer(monte_carlo, "time_steps"),
                thread_count=_published_integer(monte_carlo, "thread_count"),
                confidence_level=_published_string(monte_carlo, "confidence_level"),
                correlation=_published_string(monte_carlo, "correlation"),
                correlation_matrix=tuple(
                    tuple(item)
                    for item in _published_string_rows(monte_carlo, "correlation_matrix")
                ),
                value_at_risk=_published_money(monte_carlo.get("value_at_risk"), currency),
                expected_shortfall=_published_money(
                    monte_carlo.get("expected_shortfall"), currency
                ),
                cbb_deficiency_probability=_published_string(
                    monte_carlo, "cbb_deficiency_probability"
                ),
                margin_liquidity_shortfall_probability=_published_string(
                    monte_carlo, "margin_liquidity_shortfall_probability"
                ),
                expected_collateral_shortfall=_published_money(
                    monte_carlo.get("expected_collateral_shortfall"), currency
                ),
                expected_margin_liquidity_shortfall=_published_money(
                    monte_carlo.get("expected_margin_liquidity_shortfall"), currency
                ),
                threshold_stability=ScenarioThresholdStabilityResponse(
                    lower_confidence_level=_published_string(threshold, "lower_confidence_level"),
                    upper_confidence_level=_published_string(threshold, "upper_confidence_level"),
                    lower_value_at_risk=_published_money(
                        threshold.get("lower_value_at_risk"), currency
                    ),
                    upper_value_at_risk=_published_money(
                        threshold.get("upper_value_at_risk"), currency
                    ),
                    band_width=_published_money(threshold.get("band_width"), currency),
                ),
                tail_contribution_by_factor=_published_string_mapping(
                    monte_carlo, "tail_contribution_by_factor"
                ),
                hedge_effectiveness_distribution=HedgeEffectivenessDistributionResponse.model_validate(
                    _published_mapping(monte_carlo, "hedge_effectiveness_distribution")
                ),
            ),
            deterministic_scenarios=tuple(
                DeterministicScenarioResponse(
                    scenario_id=_published_string(item, "scenario_id"),
                    family=_published_string(item, "family"),
                    stressed_cbb=_published_money(item.get("stressed_cbb"), currency),
                    cbb_deficiency=_published_money(item.get("cbb_deficiency"), currency),
                    margin_liquidity_shortfall=_published_money(
                        item.get("margin_liquidity_shortfall"), currency
                    ),
                    loss=_published_money(item.get("loss"), currency),
                )
                for item in _published_rows(scenario, "deterministic_scenarios")
            ),
            worst_scenario_families=tuple(
                WorstScenarioFamilyResponse(
                    family=_published_string(item, "family"),
                    loss=_published_money(item.get("loss"), currency),
                )
                for item in _published_rows(scenario, "worst_scenario_families")
            ),
            internal_risk_capacity=InternalRiskCapacityResponse(
                risk_buffer=_published_money(irc.get("risk_buffer"), currency),
                tail_loss_buffer=_published_money(irc.get("tail_loss_buffer"), currency),
                liquidity_buffer=_published_money(irc.get("liquidity_buffer"), currency),
                counterparty_buffer=_published_money(irc.get("counterparty_buffer"), currency),
                climate_evidence_buffer=_published_money(
                    irc.get("climate_evidence_buffer"), currency
                ),
                uncapped_irc=_published_money(irc.get("uncapped_irc"), currency),
                irc=_published_money(irc.get("irc"), currency),
                cbb=_published_money(irc.get("cbb"), currency),
                facility_commitment=_published_money(irc.get("facility_commitment"), currency),
            ),
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise _Problem(
            409,
            "STAGE_PUBLICATION_FENCED",
            "Published scenario-capacity output is incomplete or has an unsupported schema",
        ) from exc


def _climate_traceability_projection_response(
    *, snapshot_id: str, output: dict[str, object]
) -> ClimateTraceabilityProjectionResponse:
    """Present frozen M5 evidence readiness without deriving legal conclusions."""
    try:
        stage = _published_stage(output, snapshot_id, "climate_eudr")
        result = ClimateTraceabilityResultResponse.model_validate(
            _published_mapping(stage, "result")
        )
        return ClimateTraceabilityProjectionResponse(
            stage_output_id=_published_string(stage, "stage_output_id"),
            snapshot_id=_published_string(stage, "snapshot_id"),
            stage="climate_eudr",
            stage_version=_published_string(stage, "stage_version"),
            input_digests=tuple(_published_strings(stage, "input_digests")),
            legal_interpretation_bundle_digest=_published_string(
                stage, "legal_interpretation_bundle_digest"
            ),
            policy_bundle_digest=_published_string(stage, "policy_bundle_digest"),
            computation_bundle_digest=_published_string(stage, "computation_bundle_digest"),
            output_digest=_published_string(stage, "output_digest"),
            completed_at=_published_datetime(stage, "completed_at"),
            eudr_evidence_state=result.eudr_evidence_state,
            reason_codes=tuple(_published_strings(stage, "reason_codes")),
            result=result,
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise _Problem(
            409,
            "STAGE_PUBLICATION_FENCED",
            "Published climate/traceability output is incomplete or has an unsupported schema",
        ) from exc


def _climate_traceability_summary_response(
    *, snapshot_id: str, output: dict[str, object]
) -> ClimateTraceabilitySummaryResponse:
    projection = _climate_traceability_projection_response(snapshot_id=snapshot_id, output=output)
    return ClimateTraceabilitySummaryResponse(
        stage_output_id=projection.stage_output_id,
        output_digest=projection.output_digest,
        completed_at=projection.completed_at,
        eudr_evidence_state=projection.eudr_evidence_state,
        reason_codes=projection.reason_codes,
        legal_interpretation_bundle_digest=projection.legal_interpretation_bundle_digest,
    )


def _credit_early_warning_projection_response(
    *, snapshot_id: str, output: dict[str, object]
) -> CreditEarlyWarningProjectionResponse:
    """Fence the UI to an immutable advisory result without deriving lending capacity."""
    try:
        stage = _published_stage(output, snapshot_id, "credit_early_warning")
        result = _published_mapping(stage, "result")
        return CreditEarlyWarningProjectionResponse(
            stage_output_id=_published_string(stage, "stage_output_id"),
            snapshot_id=_published_string(stage, "snapshot_id"),
            stage="credit_early_warning",
            stage_version=_published_string(stage, "stage_version"),
            input_digests=tuple(_published_strings(stage, "input_digests")),
            policy_bundle_digest=_published_string(stage, "policy_bundle_digest"),
            computation_bundle_digest=_published_string(stage, "computation_bundle_digest"),
            output_digest=_published_string(stage, "output_digest"),
            completed_at=_published_datetime(stage, "completed_at"),
            signal_type=_published_string(result, "signal_type"),  # type: ignore[arg-type]
            horizon_days=_published_integer(result, "horizon_days"),  # type: ignore[arg-type]
            probability=_published_string(result, "probability"),
            band=_published_string(result, "band"),  # type: ignore[arg-type]
            top_reason_codes=tuple(_published_strings(result, "top_reason_codes")),
            missing_feature_codes=tuple(_published_strings(result, "missing_feature_codes")),
            hard_rule_codes=tuple(_published_strings(result, "hard_rule_codes")),
            model_bundle_digest=_published_string(result, "model_bundle_digest"),
            advisory_only=True,
            as_of=_published_datetime(result, "as_of"),
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise _Problem(
            409,
            "STAGE_PUBLICATION_FENCED",
            "Published credit early-warning output is incomplete or has an unsupported schema",
        ) from exc


def _published_stage(output: dict[str, object], snapshot_id: str, stage: str) -> dict[str, object]:
    if output.get("snapshot_id") != snapshot_id or output.get("stage") != stage:
        raise ValueError("published stage is not bound to the selected snapshot")
    return output


def _published_mapping(value: dict[str, object], field: str) -> dict[str, object]:
    result = value.get(field)
    if not isinstance(result, dict):
        raise ValueError(f"published {field} is missing")
    return result


def _published_rows(value: dict[str, object], field: str) -> tuple[dict[str, object], ...]:
    rows = value.get(field)
    if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
        raise ValueError(f"published {field} rows are missing")
    return tuple(rows)


def _published_string_rows(value: dict[str, object], field: str) -> tuple[tuple[str, ...], ...]:
    rows = value.get(field)
    if not isinstance(rows, list) or not all(
        isinstance(row, list) and all(isinstance(item, str) for item in row) for row in rows
    ):
        raise ValueError(f"published {field} rows are missing")
    return tuple(tuple(row) for row in rows)


def _published_strings(value: dict[str, object], field: str) -> tuple[str, ...]:
    values = value.get(field)
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"published {field} is missing")
    return tuple(values)


def _published_string(value: dict[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"published {field} is missing")
    return result


def _published_optional_string(value: dict[str, object], field: str) -> str | None:
    result = value.get(field)
    if result is None:
        return None
    if not isinstance(result, str):
        raise ValueError(f"published {field} has an unsupported type")
    return result


def _published_integer(value: dict[str, object], field: str) -> int:
    result = value.get(field)
    if not isinstance(result, int):
        raise ValueError(f"published {field} is missing")
    return result


def _published_datetime(value: dict[str, object], field: str) -> datetime:
    result = value.get(field)
    if isinstance(result, str):
        try:
            result = datetime.fromisoformat(result.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"published {field} has an unsupported type") from exc
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError(f"published {field} has an unsupported type")
    return result.astimezone(UTC)


def _published_string_mapping(value: dict[str, object], field: str) -> dict[str, str]:
    result = _published_mapping(value, field)
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in result.items()):
        raise ValueError(f"published {field} has an unsupported type")
    return {
        key: item for key, item in result.items() if isinstance(key, str) and isinstance(item, str)
    }


def _published_money(value: object, currency: str) -> MoneyResponse:
    if not isinstance(value, str) or not value:
        raise ValueError("published monetary value is missing")
    return MoneyResponse(amount=value, currency=currency)


def _recommendation_detail_response(recommendation: Any) -> RecommendationDetailResponse:
    return RecommendationDetailResponse(
        recommendation_id=recommendation.resource_id,
        snapshot_id=recommendation.snapshot_id,
        author_id=recommendation.author_id,
        requested_amount=_money_response(recommendation.requested_amount),
        contractual_availability=_money_response(recommendation.contractual_availability),
        internal_risk_capacity=_money_response(recommendation.internal_risk_capacity),
        recommended_exposure_cap=_money_response(recommendation.recommended_exposure_cap),
        recommended_incremental_draw=_money_response(recommendation.recommended_incremental_draw),
        compared_limits=dict(recommendation.compared_limits),
        binding_constraint=recommendation.binding_constraint,
        recommendation_class=recommendation.recommendation_class.value,
        conditions=tuple(recommendation.conditions),
        reason_codes=tuple(recommendation.reason_codes),
        output_digests=tuple(recommendation.output_digests),
        policy_bundle_digest=recommendation.policy_bundle_digest,
        expires_at=recommendation.expires_at,
        created_at=recommendation.created_at,
        digest=recommendation.digest,
    )


def _final_decision_response(decision: Any) -> GovernanceResourceResponse:
    return GovernanceResourceResponse(
        resource_id=decision.resource_id,
        digest=decision.digest,
        kind="final_decision",
        status=decision.status.value,
        superseded_by=decision.superseded_by,
    )


def _approval_request_detail_response(
    request: Any, recommendation: Any, *, now: datetime
) -> ApprovalRequestDetailResponse:
    return ApprovalRequestDetailResponse(
        approval_request_id=request.resource_id,
        recommendation=_recommendation_detail_response(recommendation),
        author_id=recommendation.author_id,
        requested_by=request.requested_by,
        expires_at=request.expires_at,
        created_at=request.created_at,
        digest=request.digest,
        expired=request.expires_at <= now,
        self_approval_prohibited=True,
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


def _evidence_document_rendition_response(
    document: DocumentVersion, content: bytes
) -> EvidenceDocumentRenditionResponse:
    """Expose only a bounded plain-text rendition; originals remain attachment-only."""
    if document.content_type.lower() not in {"text/plain", "text/csv", "application/json"}:
        return EvidenceDocumentRenditionResponse(
            document_version_id=document.resource_id,
            filename=document.filename,
            content_type=document.content_type,
            byte_digest=document.byte_digest,
            preview_status="unsupported",
            preview_text=None,
            truncated=False,
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return EvidenceDocumentRenditionResponse(
            document_version_id=document.resource_id,
            filename=document.filename,
            content_type=document.content_type,
            byte_digest=document.byte_digest,
            preview_status="unsupported",
            preview_text=None,
            truncated=False,
        )
    preview_limit = 12_000
    preview = "".join(
        character
        for character in text[:preview_limit]
        if character in {"\n", "\r", "\t"} or ord(character) >= 32
    )
    return EvidenceDocumentRenditionResponse(
        document_version_id=document.resource_id,
        filename=document.filename,
        content_type=document.content_type,
        byte_digest=document.byte_digest,
        preview_status="available",
        preview_text=preview,
        truncated=len(text) > preview_limit,
    )


def _document_extraction_response(extraction: DocumentExtraction) -> DocumentExtractionResponse:
    issue = extraction.reconciliation_issue
    return DocumentExtractionResponse(
        extraction_id=extraction.resource_id,
        document_version_id=extraction.document_version_id,
        document_byte_digest=extraction.document_byte_digest,
        status="completed",
        document_type=extraction.document_type,
        classification_method=extraction.classification_method,
        classifier_version=extraction.classifier_version,
        extractor_version=extraction.extractor_version,
        text_digest=extraction.text_digest,
        candidates=tuple(
            ExtractedCandidateProvenanceResponse(
                candidate_fact_id=item.candidate_fact_id,
                extraction_id=item.extraction_id,
                confidence=item.confidence,
                approval_state="candidate",
            )
            for item in extraction.candidates
        ),
        reconciliation_issue=(
            None
            if issue is None
            else CandidateReconciliationIssueResponse(
                code=issue.code,
                lot_id=issue.lot_id,
                expected_quantity=issue.expected_quantity,
                receipt_quantity=issue.receipt_quantity,
                difference=issue.difference,
                blocks_freeze=issue.blocks_freeze,
            )
        ),
        completed_at=canonical_timestamp(extraction.completed_at),
    )


def _download_filename(filename: str) -> str:
    return (
        "".join(
            character if 32 <= ord(character) < 127 and character not in {'"', "\\", "/"} else "_"
            for character in filename
        )
        or "evidence-document"
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
        is_active=fact.is_active,
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


def _decision_override_detail_response(
    value: DecisionOverride,
    *,
    now: datetime,
) -> DecisionOverrideDetailResponse:
    approvals_required = 2 if value.requires_dual_control else 1
    return DecisionOverrideDetailResponse(
        override_id=value.resource_id,
        original_decision_id=value.original_decision_id,
        recommendation_id=value.recommendation_id,
        requester_id=value.requester_id,
        proposed_exposure_cap=_money_response(value.proposed_exposure_cap),
        reason=value.reason,
        policy_basis=value.policy_basis,
        expires_at=value.expires_at,
        created_at=value.created_at,
        digest=value.digest,
        requires_dual_control=value.requires_dual_control,
        approval_count=len(value.approval_actions),
        approvals_required=approvals_required,
        expired=value.expires_at <= now,
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


def _approval_workspace_page(
    *,
    recommendation: Any | None = None,
    context: DecisionContext | None = None,
    decision: Any | None = None,
    override: Any | None = None,
    blockers: str = "No recommendation selected",
) -> str:
    """Small authenticated UI for creating and recording governed M4B commands."""
    detail = _approval_workspace_detail(recommendation, context, decision, override, blockers)
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Approval workspace</title></head>
<body><main><h1>Approval workspace</h1>
<p>Recommendations, approvals, overrides, and final decisions remain separate
immutable resources.</p>
<p>CBB and IRC are independently calculated; production limits and lineage come
from the approved snapshot.</p>
__DECISION_DETAIL__
<h2>Governed action console</h2>
<p>Create immutable recommendation · Request approval · Record human decision
· Request dual-control override</p>
<form id="governed-command">
<label>Bearer token <input id="token" type="password" autocomplete="off" required></label>
<label>POST path <input id="path" required
placeholder="/api/v1/approval-requests/{id}/approve"></label>
<label>JSON command <textarea id="payload" required>{}</textarea></label>
<button>Create recommendation / record approval / request override</button></form>
<pre id="command-result" aria-live="polite"></pre></main>
<script>
const form=document.getElementById('governed-command');
form.onsubmit=async event=>{
event.preventDefault();
const path=document.getElementById('path').value;
const headers={Authorization:'Bearer '+document.getElementById('token').value,
'Content-Type':'application/json'};
const body=document.getElementById('payload').value;
const response=await fetch(path,{method:'POST',headers:headers,body:body});
document.getElementById('command-result').textContent=await response.text();
};
</script></body></html>"""
    return page.replace("__DECISION_DETAIL__", detail)


def _analytical_workspace_page(
    *,
    title: str,
    snapshot_id: str | None,
    output: dict[str, object] | None,
    description: str,
) -> str:
    """Render only frozen analytical output; these pages never accept trade entry."""
    if snapshot_id is None:
        return f"""<main><h1>{escape(title)}</h1><p>{escape(description)}</p>
<form method="get"><label>Approved snapshot ID <input name="snapshot_id" required></label>
<button>Load frozen analysis</button></form></main>"""
    if output is None:
        body = "No published analytical output is available for this approved snapshot."
    else:
        body = f"<pre>{escape(json.dumps(output, sort_keys=True, default=str, indent=2))}</pre>"
    return f"""<main><h1>{escape(title)}</h1><p>{escape(description)}</p>
<p>Approved snapshot: {escape(snapshot_id)}</p>{body}</main>"""


def _approval_workspace_detail(
    recommendation: Any | None,
    context: DecisionContext | None,
    decision: Any | None,
    override: Any | None,
    blockers: str,
) -> str:
    if recommendation is None:
        return """<p>Provide a <code>recommendation_id</code> or <code>decision_id</code>
in the page query to review governed decision details.</p>"""
    context_values = (
        f"<dt>CBB</dt><dd>{_money_display(context.cbb)}</dd>"
        f"<dt>IRC</dt><dd>{_money_display(context.internal_risk_capacity)}</dd>"
        if context is not None
        else "<dt>CBB / IRC</dt><dd>Authoritative source unavailable</dd>"
    )
    decision_status = decision.status.value if decision is not None else "AWAITING_APPROVAL"
    override_detail = (
        f"<h3>Override versus original recommendation</h3><dl>"
        f"<dt>Original recommendation</dt><dd>{escape(recommendation.resource_id)}</dd>"
        f"<dt>Proposed exposure cap</dt><dd>{_money_display(override.proposed_exposure_cap)}</dd>"
        f"<dt>Policy basis</dt><dd>{escape(override.policy_basis)}</dd>"
        f"<dt>Dual-control approvals</dt><dd>{len(override.approval_actions)} of 2</dd></dl>"
        if override is not None
        else ""
    )
    return f"""<section><h2>Recommendation review</h2><dl>
<dt>Recommendation</dt><dd>{escape(recommendation.resource_id)}</dd>
<dt>Requested amount</dt><dd>{_money_display(recommendation.requested_amount)}</dd>
<dt>Contractual availability</dt><dd>{_money_display(recommendation.contractual_availability)}</dd>
{context_values}
<dt>Conditions</dt><dd>{escape(", ".join(recommendation.conditions) or "None")}</dd>
<dt>Reason codes</dt><dd>{escape(", ".join(recommendation.reason_codes) or "None")}</dd>
<dt>Evidence/scenario blockers</dt><dd>{escape(blockers)}</dd>
<dt>Author</dt><dd>{escape(recommendation.author_id)}</dd>
<dt>Expiry</dt><dd>{escape(recommendation.expires_at.isoformat())}</dd>
<dt>Final decision</dt><dd>{escape(decision_status)}</dd></dl>{override_detail}</section>"""


def _facility_cockpit_page(
    *,
    snapshot_id: str | None = None,
    context: DecisionContext | None = None,
    recommendation: Any | None = None,
    decision: Any | None = None,
    hedge: dict[str, object] | None = None,
    scenario: dict[str, object] | None = None,
    error: str | None = None,
) -> str:
    """Render the key decision inputs without ever conflating CBB and IRC."""
    if snapshot_id is None:
        return """<main><h1>Facility Cockpit</h1>
<p>Contractual Borrowing Base and Internal Risk Capacity are shown separately.</p>
<form method="get"><label>Approved snapshot ID <input name="snapshot_id" required></label>
<button>Load governed facility decision</button></form></main>"""
    if error is not None:
        return f"<main><h1>Facility Cockpit</h1><p>{escape(error)}</p></main>"
    assert context is not None
    recommended_draw = (
        _money_display(recommendation.recommended_incremental_draw)
        if recommendation is not None
        else "No recommendation"
    )
    decision_status = decision.status.value if decision is not None else "No final decision"
    evidence_blockers = _reason_summary(hedge, scenario)
    return f"""<main><h1>Facility Cockpit</h1><p>Approved snapshot: {escape(snapshot_id)}</p>
<section><h2>Contractual Borrowing Base</h2><dl>
<dt>CBB</dt><dd>{_money_display(context.cbb)}</dd>
<dt>Contractual availability</dt><dd>{_money_display(context.contractual_availability)}</dd>
<dt>Commitment</dt><dd>{_money_display(context.facility_commitment)}</dd>
<dt>Current exposure</dt><dd>{_money_display(context.outstanding_exposure)}</dd></dl></section>
<section><h2>Internal Risk Capacity</h2><p>{_money_display(context.internal_risk_capacity)}</p>
<p>IRC is distinct from contractual CBB and is bound to the S6/IRC lineage.</p></section>
<section><h2>Decision</h2><dl><dt>Recommended draw</dt><dd>{recommended_draw}</dd>
<dt>Final decision</dt><dd>{escape(decision_status)}</dd></dl></section>
<section><h2>Hedge, scenario, and evidence blockers</h2><p>{escape(evidence_blockers)}</p></section>
</main>"""


def _money_display(value: Money) -> str:
    return f"{value.quantized().amount:.2f} {value.currency}"


def _report_stage_output(name: str, output: object) -> dict[str, Any]:
    """Retain a published output verbatim and expose an immutable source digest for M10."""
    if not isinstance(output, dict):
        raise ValueError(f"{name} output must be a mapping")
    existing_digest = output.get("output_digest")
    if isinstance(existing_digest, str) and existing_digest:
        return output
    return {
        "output_digest": domain_digest("report_source", 1, canonical_json_bytes(output)),
        "result": output,
    }


def _report_package_response(package: ReportPackage) -> ReportPackageResponse:
    """Map immutable reporting records to the typed public API without returning binary bytes."""
    model = package.report_model
    return ReportPackageResponse(
        package_kind=model.package_kind.value,
        report_model=ReportModelResponse(
            resource_id=model.resource_id,
            package_kind=model.package_kind.value,
            snapshot_id=model.snapshot_id,
            decision_id=model.decision_id,
            sections={name: dict(value) for name, value in model.sections.items()},
            artifact_manifest=dict(model.artifact_manifest),
            digest=model.digest,
        ),
        artifacts=tuple(
            ReportArtifactResponse(
                format=item.format.value,
                report_model_digest=item.report_model_digest,
                digest=item.digest,
                metadata=item.metadata,
            )
            for item in package.artifacts
        ),
    )


def _reason_summary(hedge: dict[str, object] | None, scenario: dict[str, object] | None) -> str:
    values: list[str] = []
    for output in (hedge, scenario):
        if output is None:
            continue
        reasons = output.get("reason_codes", ())
        if isinstance(reasons, (list, tuple)):
            values.extend(item for item in reasons if isinstance(item, str))
    return ", ".join(sorted(set(values))) or "No published blocker reason codes"


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
