"""Deterministic contractual borrowing-base certificate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from canopyledger.domain.money import Money
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest

from .calculation import (
    CollateralContribution,
    ContractualBorrowingBaseAssessment,
    ContractualReserve,
)


class CbbCertificateError(ValueError):
    """Raised when CBB certificate inputs violate contract."""


class DuplicateCollateralError(CbbCertificateError):
    """Raised when the same collateral source would be counted twice."""


@dataclass(frozen=True)
class ContractualUsage:
    current_principal: Money
    lc_exposure: Money
    other_contractual_usage: Money


@dataclass(frozen=True)
class CbbCertificate:
    certificate_id: str
    snapshot_id: str
    facility_id: str
    assessment: ContractualBorrowingBaseAssessment
    contributions: tuple[CollateralContribution, ...]
    reserves: tuple[ContractualReserve, ...]
    usage: ContractualUsage
    contractual_exposure_limit: Money
    contractual_availability: Money
    reason_codes: tuple[str, ...]
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        payload = _certificate_payload(self, include_digest=False)
        payload["output_digest"] = self.output_digest
        return payload


def build_cbb_certificate(
    *,
    certificate_id: str,
    snapshot_id: str,
    facility_id: str,
    assessment: ContractualBorrowingBaseAssessment,
    contributions: tuple[CollateralContribution, ...],
    reserves: tuple[ContractualReserve, ...],
    usage: ContractualUsage,
    reason_codes: tuple[str, ...],
) -> CbbCertificate:
    """Build a replayable CBB certificate with duplicate and usage controls."""
    currency = assessment.currency
    _validate_unique_contributions(contributions)
    _validate_currency(currency, assessment, contributions, reserves, usage)
    _validate_usage(usage)

    exposure_limit = Money(
        min(
            assessment.facility_limit.amount,
            assessment.contractual_borrowing_base.amount,
        ),
        currency,
    ).quantized()
    usage_total = (
        usage.current_principal.amount
        + usage.lc_exposure.amount
        + usage.other_contractual_usage.amount
    )
    availability = Money(max(Decimal(0), exposure_limit.amount - usage_total), currency).quantized()
    draft = CbbCertificate(
        certificate_id=certificate_id,
        snapshot_id=snapshot_id,
        facility_id=facility_id,
        assessment=assessment,
        contributions=contributions,
        reserves=reserves,
        usage=usage,
        contractual_exposure_limit=exposure_limit,
        contractual_availability=availability,
        reason_codes=reason_codes,
        output_digest="",
    )
    digest = domain_digest("cbb_certificate", 1, canonical_json_bytes(_certificate_payload(draft)))
    return CbbCertificate(
        certificate_id=certificate_id,
        snapshot_id=snapshot_id,
        facility_id=facility_id,
        assessment=assessment,
        contributions=contributions,
        reserves=reserves,
        usage=usage,
        contractual_exposure_limit=exposure_limit,
        contractual_availability=availability,
        reason_codes=reason_codes,
        output_digest=digest,
    )


def _validate_unique_contributions(contributions: tuple[CollateralContribution, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for contribution in contributions:
        key = (contribution.source_type, contribution.source_id)
        if key in seen:
            raise DuplicateCollateralError("duplicate collateral source")
        seen.add(key)


def _validate_currency(
    currency: str,
    assessment: ContractualBorrowingBaseAssessment,
    contributions: tuple[CollateralContribution, ...],
    reserves: tuple[ContractualReserve, ...],
    usage: ContractualUsage,
) -> None:
    amounts = (
        assessment.facility_limit,
        assessment.gross_eligible_contribution,
        assessment.total_reserves,
        assessment.contractual_borrowing_base,
        usage.current_principal,
        usage.lc_exposure,
        usage.other_contractual_usage,
        *(contribution.amount for contribution in contributions),
        *(reserve.amount for reserve in reserves),
    )
    if any(amount.currency != currency for amount in amounts):
        raise CbbCertificateError("all certificate amounts must use assessment currency")


def _validate_usage(usage: ContractualUsage) -> None:
    if (
        usage.current_principal.amount < 0
        or usage.lc_exposure.amount < 0
        or usage.other_contractual_usage.amount < 0
    ):
        raise CbbCertificateError("contractual usage cannot be negative")


def _money(amount: Money) -> str:
    return f"{amount.quantized().amount:.2f}"


def _certificate_payload(
    certificate: CbbCertificate, *, include_digest: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "certificate_id": certificate.certificate_id,
        "snapshot_id": certificate.snapshot_id,
        "facility_id": certificate.facility_id,
        "schema_version": "cbb-certificate-v1",
        "result": {
            "currency": certificate.assessment.currency,
            "facility_limit": _money(certificate.assessment.facility_limit),
            "gross_eligible_contribution": _money(
                certificate.assessment.gross_eligible_contribution
            ),
            "total_reserves": _money(certificate.assessment.total_reserves),
            "contractual_borrowing_base": _money(
                certificate.assessment.contractual_borrowing_base
            ),
            "contractual_exposure_limit": _money(certificate.contractual_exposure_limit),
            "current_principal": _money(certificate.usage.current_principal),
            "lc_exposure": _money(certificate.usage.lc_exposure),
            "other_contractual_usage": _money(certificate.usage.other_contractual_usage),
            "contractual_availability": _money(certificate.contractual_availability),
            "contributions": [
                {
                    "source_type": contribution.source_type,
                    "source_id": contribution.source_id,
                    "amount": _money(contribution.amount),
                }
                for contribution in certificate.contributions
            ],
            "reserves": [
                {
                    "reserve_type": reserve.reserve_type,
                    "amount": _money(reserve.amount),
                }
                for reserve in certificate.reserves
            ],
        },
        "reason_codes": list(certificate.reason_codes),
    }
    if include_digest:
        payload["output_digest"] = certificate.output_digest
    return payload
