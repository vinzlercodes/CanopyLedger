"""Deterministic, advisory-only M6 credit early-warning inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


class CreditEarlyWarningError(ValueError):
    """Raised when an M6 model bundle or as-of feature observation is invalid."""


_PROBABILITY_QUANTUM: Final = Decimal("0.0001")


@dataclass(frozen=True)
class CreditFeatureDefinition:
    """One versioned, directional model feature permitted at inference."""

    name: str
    reason_code: str
    mean: Decimal
    scale: Decimal
    direction: int
    required: bool = True

    def __post_init__(self) -> None:
        if (
            not self.name
            or not self.reason_code
            or self.scale <= 0
            or self.direction not in (-1, 1)
        ):
            raise CreditEarlyWarningError("credit feature schema is invalid")
        if not self.mean.is_finite() or not self.scale.is_finite():
            raise CreditEarlyWarningError("credit feature schema values must be finite")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "reason_code": self.reason_code,
            "mean": str(self.mean),
            "scale": str(self.scale),
            "direction": self.direction,
            "required": self.required,
        }


@dataclass(frozen=True)
class CreditModelBundle:
    """An immutable, serializable computation artifact; never a credit decision."""

    bundle_id: str
    model_version: str
    horizon_days: int
    feature_schema: tuple[CreditFeatureDefinition, ...]
    intercept: Decimal
    weights: dict[str, Decimal]
    policy_thresholds: tuple[tuple[str, Decimal], ...]
    digest: str

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.feature_schema)
        if (
            not self.bundle_id.startswith("cmb_")
            or not self.model_version
            or self.horizon_days != 90
            or not names
            or len(names) != len(set(names))
            or set(self.weights) != set(names)
            or not self.intercept.is_finite()
            or not self.digest.startswith("sha256:")
        ):
            raise CreditEarlyWarningError("credit model bundle is invalid")
        if any(not weight.is_finite() for weight in self.weights.values()):
            raise CreditEarlyWarningError("credit model weights must be finite")
        thresholds = tuple(value for _, value in self.policy_thresholds)
        if not thresholds or any(value <= 0 or value >= 1 for value in thresholds):
            raise CreditEarlyWarningError("credit model thresholds are invalid")
        if tuple(sorted(thresholds)) != thresholds:
            raise CreditEarlyWarningError("credit model thresholds must be sorted")

    def canonical_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "model_version": self.model_version,
            "horizon_days": self.horizon_days,
            "feature_schema": [item.canonical_dict() for item in self.feature_schema],
            "intercept": str(self.intercept),
            "weights": {name: str(self.weights[name]) for name in sorted(self.weights)},
            "policy_thresholds": [[name, str(value)] for name, value in self.policy_thresholds],
        }


@dataclass(frozen=True)
class CreditFeatureObservation:
    """Feature values usable only when known on or before the declared as-of time."""

    borrower_id: str
    as_of: datetime
    values: dict[str, Decimal]
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.borrower_id.startswith("bor_") or self.as_of.tzinfo is None:
            raise CreditEarlyWarningError("borrower identity and timezone-aware as-of are required")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at > self.as_of
        ):
            raise CreditEarlyWarningError("credit feature observation contains a future value")
        if not self.values or any(not value.is_finite() for value in self.values.values()):
            raise CreditEarlyWarningError("credit feature values must be present and finite")


@dataclass(frozen=True)
class CreditEarlyWarningSignal:
    """Published advisory result; it has no CBB, IRC, approval, or decision field."""

    signal_type: str
    horizon_days: int
    probability: Decimal
    band: str
    top_reason_codes: tuple[str, ...]
    missing_feature_codes: tuple[str, ...]
    hard_rule_codes: tuple[str, ...]
    model_bundle_digest: str
    advisory_only: bool = True


@dataclass(frozen=True)
class CreditHardRule:
    """A policy-owned advisory escalation that always takes precedence over score banding."""

    feature_name: str
    minimum_value: Decimal
    reason_code: str

    def __post_init__(self) -> None:
        if not self.feature_name or not self.reason_code or not self.minimum_value.is_finite():
            raise CreditEarlyWarningError("credit hard rule is invalid")


def build_reference_bundle() -> CreditModelBundle:
    """Return the checked-in synthetic reference artifact used by local deterministic inference."""
    schema = (
        CreditFeatureDefinition(
            "liquidity_ratio", "LIQUIDITY_COVERAGE_DECLINE", Decimal("1.4"), Decimal("0.4"), -1
        ),
        CreditFeatureDefinition(
            "receivable_days", "RECEIVABLE_DAYS_RISING", Decimal("42"), Decimal("18"), 1
        ),
        CreditFeatureDefinition(
            "margin_coverage_ratio", "MARGIN_STRESS_INCREASE", Decimal("1.3"), Decimal("0.35"), -1
        ),
        CreditFeatureDefinition(
            "payment_delay_days", "PAYMENT_DELAYS_RISING", Decimal("4"), Decimal("8"), 1
        ),
    )
    reference_weights = {
        "liquidity_ratio": "0.7000",
        "margin_coverage_ratio": "0.6500",
        "payment_delay_days": "0.5500",
        "receivable_days": "0.6000",
    }
    draft = {
        "bundle_id": "cmb_reference_credit_early_warning_v1",
        "model_version": "reference-v1",
        "horizon_days": 90,
        "feature_schema": [item.canonical_dict() for item in schema],
        "intercept": "-1.1000",
        "weights": reference_weights,
        "policy_thresholds": [["moderate", "0.2500"], ["high", "0.5500"]],
    }
    digest = domain_digest("credit_model_bundle", 1, canonical_json_bytes(draft))
    return CreditModelBundle(
        bundle_id=str(draft["bundle_id"]),
        model_version=str(draft["model_version"]),
        horizon_days=90,
        feature_schema=schema,
        intercept=Decimal("-1.1000"),
        weights={name: Decimal(value) for name, value in reference_weights.items()},
        policy_thresholds=(("moderate", Decimal("0.2500")), ("high", Decimal("0.5500"))),
        digest=digest,
    )


def infer_deterioration_signal(
    bundle: CreditModelBundle, observation: CreditFeatureObservation
) -> CreditEarlyWarningSignal:
    """Score one frozen/as-of observation without accessing mutable facility or CBB state."""
    linear = bundle.intercept
    contributions: list[tuple[Decimal, str]] = []
    missing: list[str] = []
    for feature in bundle.feature_schema:
        raw_value = observation.values.get(feature.name)
        if raw_value is None:
            if feature.required:
                missing.append(f"MISSING_{feature.name.upper()}")
            normalized = Decimal(0)
        else:
            normalized = (raw_value - feature.mean) / feature.scale
        contribution = bundle.weights[feature.name] * normalized * feature.direction
        linear += contribution
        contributions.append((contribution, feature.reason_code))
    probability = Decimal(str(1 / (1 + math.exp(-float(linear))))).quantize(
        _PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN
    )
    hard_rule_codes = _hard_rule_codes(observation)
    band = "high" if hard_rule_codes else _band(bundle, probability)
    ordered_reasons = tuple(
        reason for contribution, reason in sorted(contributions, reverse=True) if contribution > 0
    )[:3]
    reason_codes = (
        *hard_rule_codes,
        *(reason for reason in ordered_reasons if reason not in hard_rule_codes),
    )
    return CreditEarlyWarningSignal(
        signal_type="synthetic_deterioration_likelihood",
        horizon_days=bundle.horizon_days,
        probability=probability,
        band=band,
        top_reason_codes=(reason_codes or ("NO_MATERIAL_DETERIORATION_DRIVER",))[:3],
        missing_feature_codes=tuple(sorted(missing)),
        hard_rule_codes=hard_rule_codes,
        model_bundle_digest=bundle.digest,
    )


def _band(bundle: CreditModelBundle, probability: Decimal) -> str:
    result = "low"
    for name, threshold in bundle.policy_thresholds:
        if probability >= threshold:
            result = name
    return result


def _hard_rule_codes(observation: CreditFeatureObservation) -> tuple[str, ...]:
    """Apply a narrow policy boundary after scoring; it never exposes a lending-cap field."""
    payment_delay = observation.values.get("payment_delay_days")
    if payment_delay is not None and payment_delay >= Decimal("30"):
        return ("HARD_RULE_MATERIAL_PAYMENT_DELAY",)
    return ()
