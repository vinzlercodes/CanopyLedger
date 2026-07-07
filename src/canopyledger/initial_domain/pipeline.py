"""Pure M1B initial-domain stage graph."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from canopyledger.borrowing_base.calculation import (
    CollateralContribution,
    ContractualReserve,
    calculate_contractual_borrowing_base,
)
from canopyledger.borrowing_base.certificate import (
    CbbCertificate,
    ContractualUsage,
    build_cbb_certificate,
)
from canopyledger.collateral.eligibility import EligibilityStatus, contribution_from_valuation
from canopyledger.collateral.valuation import InventoryValuationInput, value_inventory_lot
from canopyledger.domain.money import Money
from canopyledger.domain.units import Quantity, UnitConversionTable, normalize_quantity
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.market.snapshot import MarketSnapshot
from canopyledger.receivables.eligibility import (
    ReceivableEligibilityPolicy,
    ReceivableStatus,
    assess_receivable_eligibility,
)
from canopyledger.receivables.valuation import ReceivableValuationInput, value_receivable


class M1BPipelineError(ValueError):
    """Raised when M1B pipeline inputs violate contract."""


class ReserveInput(ContractualReserve):
    """Typed reserve input for M1B pipeline calls."""


DEFAULT_UNIT_CONVERSION_TABLE = UnitConversionTable(
    version="coffee-units-v1",
    factors={
        ("bag_60kg", "metric_tonne"): Decimal("0.06"),
        ("lb", "metric_tonne"): Decimal("0.00045359237"),
        ("pound", "metric_tonne"): Decimal("0.00045359237"),
    },
)


@dataclass(frozen=True)
class InventoryLotInput:
    lot_id: str
    quantity: Decimal
    quantity_unit: str
    benchmark_symbol: str
    physical_differential_usd_per_mt: Decimal
    selling_cost_usd_per_mt: Decimal
    liquidation_cost: Money
    advance_rate: Decimal
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReceivableInput:
    receivable_id: str
    obligor_id: str
    invoice_amount: Money
    credit_note_amount: Money
    fx_pair: str
    age_days: int
    advance_rate: Decimal
    max_age_days: int
    delivery_evidence_approved: bool
    status: ReceivableStatus = ReceivableStatus.CURRENT


@dataclass(frozen=True)
class M1BPipelineInput:
    snapshot_id: str
    facility_id: str
    certificate_id: str
    facility_limit: Money
    current_principal: Money
    lc_exposure: Money
    other_contractual_usage: Money
    market_snapshot: MarketSnapshot
    inventory_lots: tuple[InventoryLotInput, ...]
    receivables: tuple[ReceivableInput, ...]
    reserves: tuple[ReserveInput, ...]
    market_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    unit_conversion_table: UnitConversionTable = DEFAULT_UNIT_CONVERSION_TABLE


class M1BStage(StrEnum):
    MARKET_NORMALIZATION = "market_normalization"
    COLLATERAL_VALUATION = "collateral_valuation"
    ELIGIBILITY_AND_RESERVES = "eligibility_and_reserves"
    CONTRACTUAL_BORROWING_BASE = "contractual_borrowing_base"


@dataclass(frozen=True)
class StageOutput:
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

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "stage_output_id": self.stage_output_id,
            "snapshot_id": self.snapshot_id,
            "stage": self.stage,
            "stage_version": self.stage_version,
            "input_digests": list(self.input_digests),
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "result": self.result,
            "warnings": list(self.warnings),
            "reason_codes": list(self.reason_codes),
            "output_digest": self.output_digest,
        }


@dataclass(frozen=True)
class M1BPipelineResult:
    stage_outputs: tuple[StageOutput, ...]
    certificate: CbbCertificate


def run_initial_domain_pipeline(value: M1BPipelineInput) -> M1BPipelineResult:
    """Run S1-S4 for the deterministic M1B domain pipeline."""
    _validate_input(value)
    market_output = _stage_output(
        value,
        M1BStage.MARKET_NORMALIZATION,
        input_digests=(value.market_snapshot.digest,),
        result={
            "market_snapshot_id": value.market_snapshot.snapshot_id,
            "market_snapshot_digest": value.market_snapshot.digest,
            "as_of": value.market_snapshot.as_of,
        },
        reason_codes=(),
    )

    inventory_valuations = []
    inventory_contributions: list[CollateralContribution] = []
    reason_codes: list[str] = []
    for lot in value.inventory_lots:
        price = value.market_snapshot.price(lot.benchmark_symbol)
        fx = value.market_snapshot.fx_rate("EUR/USD")
        normalized_quantity = normalize_quantity(
            Quantity(lot.quantity, lot.quantity_unit),
            output_unit="metric_tonne",
            table=value.unit_conversion_table,
        )
        inventory_valuation = value_inventory_lot(
            InventoryValuationInput(
                lot_id=lot.lot_id,
                quantity_mt=normalized_quantity.output_value,
                benchmark_price_usd_per_mt=price.price,
                physical_differential_usd_per_mt=lot.physical_differential_usd_per_mt,
                selling_cost_usd_per_mt=lot.selling_cost_usd_per_mt,
                fx_eur_per_usd=fx.rate,
                liquidation_cost_eur=lot.liquidation_cost.amount,
            )
        )
        inventory_contribution = contribution_from_valuation(
            inventory_valuation,
            status=EligibilityStatus.ELIGIBLE,
            base_advance_rate=lot.advance_rate,
            reason_codes=lot.reason_codes,
        )
        inventory_valuations.append(
            {
                "lot_id": lot.lot_id,
                "input_quantity": str(normalized_quantity.input_value),
                "input_quantity_unit": normalized_quantity.input_unit,
                "quantity": str(normalized_quantity.output_value),
                "quantity_unit": normalized_quantity.output_unit,
                "unit_conversion_table_version": normalized_quantity.conversion_table_version,
                "gross_market_value": _money(inventory_valuation.gross_market_value),
                "net_recovery_value": _money(inventory_valuation.net_recovery_value),
                "advanced_value": _money(inventory_contribution.amount),
            }
        )
        inventory_contributions.append(
            CollateralContribution("inventory", lot.lot_id, inventory_contribution.amount)
        )
        reason_codes.extend(lot.reason_codes)

    receivable_valuations = []
    receivable_contributions: list[CollateralContribution] = []
    for receivable in value.receivables:
        fx = value.market_snapshot.fx_rate(receivable.fx_pair)
        receivable_valuation = value_receivable(
            ReceivableValuationInput(
                receivable_id=receivable.receivable_id,
                invoice_amount=receivable.invoice_amount,
                credit_note_amount=receivable.credit_note_amount,
                facility_currency=value.facility_limit.currency,
                fx_facility_per_invoice=fx.rate,
            )
        )
        receivable_contribution = assess_receivable_eligibility(
            receivable_valuation,
            policy=ReceivableEligibilityPolicy(
                max_age_days=receivable.max_age_days,
                advance_rate=receivable.advance_rate,
            ),
            age_days=receivable.age_days,
            status=receivable.status,
            delivery_evidence_approved=receivable.delivery_evidence_approved,
            obligor_id=receivable.obligor_id,
        )
        receivable_valuations.append(
            {
                "receivable_id": receivable.receivable_id,
                "open_amount": _money(receivable_valuation.open_amount),
                "facility_value": _money(receivable_valuation.facility_value),
                "advanced_value": _money(receivable_contribution.amount),
                "reason_codes": list(receivable_contribution.reason_codes),
            }
        )
        receivable_contributions.append(
            CollateralContribution(
                "receivable", receivable.receivable_id, receivable_contribution.amount
            )
        )
        reason_codes.extend(receivable_contribution.reason_codes)

    valuation_output = _stage_output(
        value,
        M1BStage.COLLATERAL_VALUATION,
        input_digests=(market_output.output_digest,),
        result={
            "inventory": inventory_valuations,
            "receivables": receivable_valuations,
        },
        reason_codes=tuple(reason_codes),
    )

    contributions = tuple(inventory_contributions + receivable_contributions)
    reserves = tuple(ContractualReserve(item.reserve_type, item.amount) for item in value.reserves)
    eligibility_output = _stage_output(
        value,
        M1BStage.ELIGIBILITY_AND_RESERVES,
        input_digests=(valuation_output.output_digest,),
        result={
            "contributions": [
                {
                    "source_type": contribution.source_type,
                    "source_id": contribution.source_id,
                    "amount": _money(contribution.amount),
                }
                for contribution in contributions
            ],
            "reserves": [
                {
                    "reserve_type": reserve.reserve_type,
                    "amount": _money(reserve.amount),
                }
                for reserve in reserves
            ],
        },
        reason_codes=tuple(reason_codes),
    )

    assessment = calculate_contractual_borrowing_base(
        facility_limit=value.facility_limit,
        contributions=contributions,
        reserves=reserves,
    )
    certificate = build_cbb_certificate(
        certificate_id=value.certificate_id,
        snapshot_id=value.snapshot_id,
        facility_id=value.facility_id,
        assessment=assessment,
        contributions=contributions,
        reserves=reserves,
        usage=ContractualUsage(
            current_principal=value.current_principal,
            lc_exposure=value.lc_exposure,
            other_contractual_usage=value.other_contractual_usage,
        ),
        reason_codes=tuple(reason_codes),
    )
    cbb_output = _stage_output(
        value,
        M1BStage.CONTRACTUAL_BORROWING_BASE,
        input_digests=(eligibility_output.output_digest,),
        result=certificate.to_canonical_dict()["result"],
        reason_codes=tuple(reason_codes),
    )
    return M1BPipelineResult(
        stage_outputs=(market_output, valuation_output, eligibility_output, cbb_output),
        certificate=certificate,
    )


def _validate_input(value: M1BPipelineInput) -> None:
    if not value.snapshot_id or not value.facility_id or not value.certificate_id:
        raise M1BPipelineError("snapshot, facility, and certificate ids are required")
    if not value.inventory_lots and not value.receivables:
        raise M1BPipelineError("at least one collateral input is required")
    if value.facility_limit.amount < 0:
        raise M1BPipelineError("facility limit cannot be negative")


def _stage_output(
    value: M1BPipelineInput,
    stage: M1BStage,
    *,
    input_digests: tuple[str, ...],
    result: dict[str, Any],
    reason_codes: tuple[str, ...],
    output_digest: str | None = None,
) -> StageOutput:
    stage_output_id = f"out_{stage.value}_{value.snapshot_id.removeprefix('snp_')}"
    draft = {
        "stage_output_id": stage_output_id,
        "snapshot_id": value.snapshot_id,
        "stage": stage.value,
        "stage_version": "1.0.0",
        "input_digests": list(input_digests),
        "policy_bundle_digest": value.policy_bundle_digest,
        "computation_bundle_digest": value.computation_bundle_digest,
        "result": result,
        "warnings": [],
        "reason_codes": list(reason_codes),
    }
    digest = output_digest or domain_digest("pipeline_stage_output", 1, canonical_json_bytes(draft))
    return StageOutput(
        stage_output_id=stage_output_id,
        snapshot_id=value.snapshot_id,
        stage=stage.value,
        stage_version="1.0.0",
        input_digests=input_digests,
        policy_bundle_digest=value.policy_bundle_digest,
        computation_bundle_digest=value.computation_bundle_digest,
        result=result,
        warnings=(),
        reason_codes=reason_codes,
        output_digest=digest,
    )


def _money(value: Money) -> str:
    return f"{value.quantized().amount:.2f}"
