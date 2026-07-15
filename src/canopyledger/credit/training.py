"""Offline, CPU-only reproducible fitting workflow for the M6 synthetic reference artifact."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from canopyledger.credit.engine import (
    CreditEarlyWarningError,
    CreditFeatureDefinition,
    CreditFeatureObservation,
    CreditModelBundle,
    infer_deterioration_signal,
)
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


@dataclass(frozen=True)
class BorrowerPanelRow:
    borrower_id: str
    as_of: datetime
    observed_at: datetime
    values: dict[str, Decimal]
    deterioration_within_90_days: int

    def __post_init__(self) -> None:
        if (
            not self.borrower_id.startswith("bor_")
            or self.as_of.tzinfo is None
            or self.observed_at.tzinfo is None
            or self.observed_at > self.as_of
            or self.deterioration_within_90_days not in (0, 1)
            or not self.values
            or any(not value.is_finite() for value in self.values.values())
        ):
            raise CreditEarlyWarningError(
                "synthetic borrower panel row is invalid or leaks future data"
            )


@dataclass(frozen=True)
class TemporalSplit:
    train: tuple[BorrowerPanelRow, ...]
    validation: tuple[BorrowerPanelRow, ...]


@dataclass(frozen=True)
class LeakageReport:
    passed: bool
    checked_row_count: int
    allowed_features: tuple[str, ...]
    violations: tuple[str, ...]


@dataclass(frozen=True)
class CreditEvaluation:
    roc_auc: Decimal
    pr_auc: Decimal
    brier_score: Decimal
    calibration_curve: tuple[dict[str, str], ...]
    precision_at_threshold: Decimal
    recall_at_threshold: Decimal
    time_stability: tuple[dict[str, str], ...]
    segment_performance: tuple[dict[str, str], ...]
    challenger_accuracy: Decimal


@dataclass(frozen=True)
class CreditTrainingArtifact:
    bundle: CreditModelBundle
    leakage_report: LeakageReport
    evaluation: CreditEvaluation
    model_card: dict[str, object]

    def canonical_dict(self) -> dict[str, object]:
        return {
            "bundle": self.bundle.canonical_dict(),
            "bundle_digest": self.bundle.digest,
            "leakage_report": {
                "passed": self.leakage_report.passed,
                "checked_row_count": self.leakage_report.checked_row_count,
                "allowed_features": list(self.leakage_report.allowed_features),
                "violations": list(self.leakage_report.violations),
            },
            "evaluation": {
                "roc_auc": str(self.evaluation.roc_auc),
                "pr_auc": str(self.evaluation.pr_auc),
                "brier_score": str(self.evaluation.brier_score),
                "calibration_curve": list(self.evaluation.calibration_curve),
                "precision_at_threshold": str(self.evaluation.precision_at_threshold),
                "recall_at_threshold": str(self.evaluation.recall_at_threshold),
                "time_stability": list(self.evaluation.time_stability),
                "segment_performance": list(self.evaluation.segment_performance),
                "challenger_accuracy": str(self.evaluation.challenger_accuracy),
            },
            "model_card": self.model_card,
        }


def generate_synthetic_borrower_panel(
    *, borrower_count: int = 24, observations_per_borrower: int = 10, seed: int = 417
) -> tuple[BorrowerPanelRow, ...]:
    """Create a deterministic public-reference panel with no borrower data dependency."""
    if borrower_count < 2 or observations_per_borrower < 4:
        raise CreditEarlyWarningError(
            "synthetic panel requires at least two borrowers and four periods"
        )
    random_source = random.Random(seed)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    rows: list[BorrowerPanelRow] = []
    for borrower_index in range(borrower_count):
        borrower_risk = random_source.uniform(-0.8, 0.8)
        borrower_id = f"bor_0198a000-0000-7000-8000-{borrower_index:012d}"
        for period in range(observations_per_borrower):
            trend = period / max(observations_per_borrower - 1, 1)
            liquidity = (
                1.6 - 0.55 * borrower_risk - 0.35 * trend + random_source.uniform(-0.12, 0.12)
            )
            receivable_days = 38 + 20 * borrower_risk + 15 * trend + random_source.uniform(-6, 6)
            margin_coverage = (
                1.55 - 0.45 * borrower_risk - 0.25 * trend + random_source.uniform(-0.1, 0.1)
            )
            payment_delay = 3 + 9 * borrower_risk + 9 * trend + random_source.uniform(-3, 3)
            latent = (
                (1.25 - liquidity) * 1.7
                + (receivable_days - 48) / 16
                + (1.15 - margin_coverage) * 1.8
                + (payment_delay - 8) / 8
                + random_source.uniform(-0.45, 0.45)
            )
            as_of = base + timedelta(days=30 * period)
            rows.append(
                BorrowerPanelRow(
                    borrower_id=borrower_id,
                    as_of=as_of,
                    observed_at=as_of,
                    values={
                        "liquidity_ratio": _decimal(liquidity),
                        "receivable_days": _decimal(receivable_days),
                        "margin_coverage_ratio": _decimal(margin_coverage),
                        "payment_delay_days": _decimal(max(payment_delay, 0)),
                    },
                    deterioration_within_90_days=int(latent > 0.35),
                )
            )
    return tuple(rows)


def split_temporally_by_borrower(rows: tuple[BorrowerPanelRow, ...]) -> TemporalSplit:
    """Reserve the latest quarter of each borrower's history for time-forward validation."""
    grouped: dict[str, list[BorrowerPanelRow]] = defaultdict(list)
    for row in rows:
        grouped[row.borrower_id].append(row)
    train: list[BorrowerPanelRow] = []
    validation: list[BorrowerPanelRow] = []
    for borrower_id, borrower_rows in sorted(grouped.items()):
        ordered = sorted(borrower_rows, key=lambda item: item.as_of)
        if len(ordered) < 4 or len({item.as_of for item in ordered}) != len(ordered):
            raise CreditEarlyWarningError(f"borrower {borrower_id} cannot support temporal split")
        boundary = max(1, (len(ordered) * 3) // 4)
        train.extend(ordered[:boundary])
        validation.extend(ordered[boundary:])
    if not train or not validation:
        raise CreditEarlyWarningError("temporal split produced an empty partition")
    return TemporalSplit(tuple(train), tuple(validation))


def audit_leakage(
    rows: tuple[BorrowerPanelRow, ...], schema: tuple[CreditFeatureDefinition, ...]
) -> LeakageReport:
    """Reject outcome-shaped, unknown, and post-as-of data before preprocessing can see it."""
    allowed = tuple(feature.name for feature in schema)
    allowed_set = set(allowed)
    violations: list[str] = []
    for row in rows:
        if row.observed_at > row.as_of:
            violations.append(f"FUTURE_OBSERVATION:{row.borrower_id}:{row.as_of.isoformat()}")
        unknown = sorted(set(row.values) - allowed_set)
        if unknown:
            violations.append(f"UNKNOWN_FEATURE:{','.join(unknown)}")
        prohibited = sorted(
            name for name in row.values if "deterioration" in name or "target" in name
        )
        if prohibited:
            violations.append(f"OUTCOME_FEATURE:{','.join(prohibited)}")
    return LeakageReport(
        passed=not violations,
        checked_row_count=len(rows),
        allowed_features=allowed,
        violations=tuple(sorted(violations)),
    )


def fit_reference_model(rows: tuple[BorrowerPanelRow, ...]) -> CreditTrainingArtifact:
    """Fit baseline logistic and compare a shallow challenger using only CPU/stdlib primitives."""
    schema = _reference_schema()
    leakage = audit_leakage(rows, schema)
    if not leakage.passed:
        raise CreditEarlyWarningError(
            f"credit leakage audit failed: {', '.join(leakage.violations)}"
        )
    split = split_temporally_by_borrower(rows)
    means, scales = _fit_preprocessing(split.train, schema)
    intercept, weights = _fit_logistic(split.train, schema, means, scales)
    bundle = _fitted_bundle(schema, means, scales, intercept, weights)
    evaluation = _evaluate(bundle, split.validation)
    card = {
        "label": "Synthetic borrower deterioration likelihood",
        "horizon_days": 90,
        "training_data": "deterministic synthetic public reference panel",
        "split": "per-borrower chronological 75/25 temporal holdout",
        "baseline": "logistic regression fitted with fixed-seed batch gradient descent",
        "challenger": "depth-one threshold tree, comparison only",
        "calibration": "five-bin holdout calibration curve",
        "limitations": [
            "Advisory only; cannot calculate or alter Contractual Borrowing Base.",
            "Synthetic reference performance is not evidence of production credit performance.",
        ],
    }
    return CreditTrainingArtifact(
        bundle=bundle, leakage_report=leakage, evaluation=evaluation, model_card=card
    )


def _reference_schema() -> tuple[CreditFeatureDefinition, ...]:
    return (
        CreditFeatureDefinition(
            "liquidity_ratio", "LIQUIDITY_COVERAGE_DECLINE", Decimal("0"), Decimal("1"), -1
        ),
        CreditFeatureDefinition(
            "receivable_days", "RECEIVABLE_DAYS_RISING", Decimal("0"), Decimal("1"), 1
        ),
        CreditFeatureDefinition(
            "margin_coverage_ratio", "MARGIN_STRESS_INCREASE", Decimal("0"), Decimal("1"), -1
        ),
        CreditFeatureDefinition(
            "payment_delay_days", "PAYMENT_DELAYS_RISING", Decimal("0"), Decimal("1"), 1
        ),
    )


def _fit_preprocessing(
    rows: tuple[BorrowerPanelRow, ...], schema: tuple[CreditFeatureDefinition, ...]
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    means: dict[str, Decimal] = {}
    scales: dict[str, Decimal] = {}
    for feature in schema:
        values = [row.values[feature.name] for row in rows]
        mean = sum(values, Decimal(0)) / len(values)
        variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / len(values)
        means[feature.name] = mean
        scales[feature.name] = max(variance.sqrt(), Decimal("0.0001"))
    return means, scales


def _fit_logistic(
    rows: tuple[BorrowerPanelRow, ...],
    schema: tuple[CreditFeatureDefinition, ...],
    means: dict[str, Decimal],
    scales: dict[str, Decimal],
) -> tuple[Decimal, dict[str, Decimal]]:
    intercept = 0.0
    weights = {feature.name: 0.0 for feature in schema}
    learning_rate = 0.08
    for _ in range(350):
        gradients = {feature.name: 0.0 for feature in schema}
        intercept_gradient = 0.0
        for row in rows:
            values = _normalized_values(row, schema, means, scales)
            linear = intercept + sum(weights[name] * values[name] for name in weights)
            probability = 1 / (1 + math.exp(-max(min(linear, 30), -30)))
            error = probability - row.deterioration_within_90_days
            intercept_gradient += error
            for name, value in values.items():
                gradients[name] += error * value
        divisor = len(rows)
        intercept -= learning_rate * intercept_gradient / divisor
        for name in weights:
            weights[name] -= learning_rate * gradients[name] / divisor
    return Decimal(str(intercept)), {name: Decimal(str(value)) for name, value in weights.items()}


def _fitted_bundle(
    schema: tuple[CreditFeatureDefinition, ...],
    means: dict[str, Decimal],
    scales: dict[str, Decimal],
    intercept: Decimal,
    fitted_weights: dict[str, Decimal],
) -> CreditModelBundle:
    fitted_schema = tuple(
        CreditFeatureDefinition(
            item.name,
            item.reason_code,
            means[item.name],
            scales[item.name],
            item.direction,
            item.required,
        )
        for item in schema
    )
    # The optimizer uses values already transformed into each feature's risk direction.
    positive_weights = {name: fitted_weights[name] for name in fitted_weights}
    draft = {
        "bundle_id": "cmb_reference_credit_early_warning_v1",
        "model_version": "reference-v1",
        "horizon_days": 90,
        "feature_schema": [item.canonical_dict() for item in fitted_schema],
        "intercept": str(intercept),
        "weights": {name: str(positive_weights[name]) for name in sorted(positive_weights)},
        "policy_thresholds": [["moderate", "0.2500"], ["high", "0.5500"]],
    }
    return CreditModelBundle(
        bundle_id="cmb_reference_credit_early_warning_v1",
        model_version="reference-v1",
        horizon_days=90,
        feature_schema=fitted_schema,
        intercept=intercept,
        weights=positive_weights,
        policy_thresholds=(("moderate", Decimal("0.2500")), ("high", Decimal("0.5500"))),
        digest=domain_digest("credit_model_bundle", 1, canonical_json_bytes(draft)),
    )


def _evaluate(bundle: CreditModelBundle, rows: tuple[BorrowerPanelRow, ...]) -> CreditEvaluation:
    scored = [
        (
            row,
            infer_deterioration_signal(
                bundle,
                CreditFeatureObservation(row.borrower_id, row.as_of, row.values, row.observed_at),
            ).probability,
        )
        for row in rows
    ]
    labels = [row.deterioration_within_90_days for row, _ in scored]
    probabilities = [score for _, score in scored]
    threshold = Decimal("0.5500")
    true_positive = sum(
        1
        for label, score in zip(labels, probabilities, strict=True)
        if label and score >= threshold
    )
    predicted_positive = sum(1 for score in probabilities if score >= threshold)
    actual_positive = sum(labels)
    calibration = _calibration_curve(labels, probabilities)
    by_month: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for row, score in scored:
        by_month[row.as_of.strftime("%Y-%m")].append((row.deterioration_within_90_days, score))
    time_stability = tuple(
        {
            "period": period,
            "brier_score": str(
                _brier([label for label, _ in items], [score for _, score in items])
            ),
        }
        for period, items in sorted(by_month.items())
    )
    segment = tuple(
        {
            "segment": "payment_delay_30_plus" if delayed else "payment_delay_under_30",
            "row_count": str(len(items)),
            "event_rate": str(_decimal(sum(label for label, _ in items) / max(len(items), 1))),
        }
        for delayed, items in (
            (
                False,
                [
                    (row.deterioration_within_90_days, score)
                    for row, score in scored
                    if row.values["payment_delay_days"] < 30
                ],
            ),
            (
                True,
                [
                    (row.deterioration_within_90_days, score)
                    for row, score in scored
                    if row.values["payment_delay_days"] >= 30
                ],
            ),
        )
    )
    return CreditEvaluation(
        roc_auc=_roc_auc(labels, probabilities),
        pr_auc=_pr_auc(labels, probabilities),
        brier_score=_brier(labels, probabilities),
        calibration_curve=calibration,
        precision_at_threshold=_decimal(true_positive / max(predicted_positive, 1)),
        recall_at_threshold=_decimal(true_positive / max(actual_positive, 1)),
        time_stability=time_stability,
        segment_performance=segment,
        challenger_accuracy=_shallow_challenger_accuracy(rows),
    )


def _normalized_values(
    row: BorrowerPanelRow,
    schema: tuple[CreditFeatureDefinition, ...],
    means: dict[str, Decimal],
    scales: dict[str, Decimal],
) -> dict[str, float]:
    return {
        feature.name: float((row.values[feature.name] - means[feature.name]) / scales[feature.name])
        * feature.direction
        for feature in schema
    }


def _roc_auc(labels: list[int], scores: list[Decimal]) -> Decimal:
    positives = [(label, score) for label, score in zip(labels, scores, strict=True) if label]
    negatives = [(label, score) for label, score in zip(labels, scores, strict=True) if not label]
    if not positives or not negatives:
        return Decimal("0")
    wins = sum(
        Decimal("1")
        if p_score > n_score
        else Decimal("0.5")
        if p_score == n_score
        else Decimal("0")
        for _, p_score in positives
        for _, n_score in negatives
    )
    return _decimal(wins / (len(positives) * len(negatives)))


def _pr_auc(labels: list[int], scores: list[Decimal]) -> Decimal:
    positives = sum(labels)
    if positives == 0:
        return Decimal("0")
    ranked = sorted(zip(labels, scores, strict=True), key=lambda item: item[1], reverse=True)
    true_positive = 0
    total = Decimal("0")
    for index, (label, _) in enumerate(ranked, start=1):
        if label:
            true_positive += 1
            total += Decimal(true_positive) / Decimal(index)
    return _decimal(total / positives)


def _brier(labels: list[int], scores: list[Decimal]) -> Decimal:
    return _decimal(
        sum((Decimal(label) - score) ** 2 for label, score in zip(labels, scores, strict=True))
        / len(labels)
    )


def _calibration_curve(labels: list[int], scores: list[Decimal]) -> tuple[dict[str, str], ...]:
    result: list[dict[str, str]] = []
    for bin_index in range(5):
        lower = Decimal(bin_index) / 5
        upper = Decimal(bin_index + 1) / 5
        items = [
            (label, score)
            for label, score in zip(labels, scores, strict=True)
            if lower <= score < upper or (bin_index == 4 and score == upper)
        ]
        if items:
            result.append(
                {
                    "bin": f"{lower}-{upper}",
                    "mean_prediction": str(_decimal(sum(score for _, score in items) / len(items))),
                    "observed_rate": str(_decimal(sum(label for label, _ in items) / len(items))),
                    "count": str(len(items)),
                }
            )
    return tuple(result)


def _shallow_challenger_accuracy(rows: tuple[BorrowerPanelRow, ...]) -> Decimal:
    threshold = sum(row.values["payment_delay_days"] for row in rows) / len(rows)
    correct = sum(
        (row.values["payment_delay_days"] >= threshold) == bool(row.deterioration_within_90_days)
        for row in rows
    )
    return _decimal(correct / len(rows))


def _decimal(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
