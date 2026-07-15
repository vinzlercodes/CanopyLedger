"""M6 credit early-warning behavior contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


def test_reference_signal_is_advisory_and_has_the_required_90_day_label() -> None:
    """The public M6 inference contract is bounded advisory information, not capacity math."""
    from canopyledger.credit.engine import (
        CreditFeatureObservation,
        build_reference_bundle,
        infer_deterioration_signal,
    )

    bundle = build_reference_bundle()
    signal = infer_deterioration_signal(
        bundle,
        CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000000601",
            as_of=datetime(2026, 7, 1, tzinfo=UTC),
            values={
                "liquidity_ratio": Decimal("1.05"),
                "receivable_days": Decimal("65"),
                "margin_coverage_ratio": Decimal("0.90"),
                "payment_delay_days": Decimal("12"),
            },
        ),
    )

    assert signal.signal_type == "synthetic_deterioration_likelihood"
    assert signal.horizon_days == 90
    assert signal.advisory_only is True
    assert signal.probability >= Decimal("0")
    assert signal.probability <= Decimal("1")
    assert signal.model_bundle_digest == bundle.digest
    assert signal.top_reason_codes


def test_feature_observation_rejects_future_values_to_prevent_as_of_leakage() -> None:
    from canopyledger.credit.engine import (
        CreditEarlyWarningError,
        CreditFeatureObservation,
    )

    with pytest.raises(CreditEarlyWarningError, match="future"):
        CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000000601",
            as_of=datetime(2026, 7, 1, tzinfo=UTC),
            values={"liquidity_ratio": Decimal("1.0")},
            observed_at=datetime(2026, 7, 2, tzinfo=UTC),
        )


def test_missing_features_and_hard_rules_are_visible_with_hard_rule_precedence() -> None:
    from canopyledger.credit.engine import (
        CreditFeatureObservation,
        build_reference_bundle,
        infer_deterioration_signal,
    )

    signal = infer_deterioration_signal(
        build_reference_bundle(),
        CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000000602",
            as_of=datetime(2026, 7, 1, tzinfo=UTC),
            values={"payment_delay_days": Decimal("45")},
        ),
    )

    assert signal.band == "high"
    assert signal.hard_rule_codes == ("HARD_RULE_MATERIAL_PAYMENT_DELAY",)
    assert signal.top_reason_codes[0] == "HARD_RULE_MATERIAL_PAYMENT_DELAY"
    assert set(signal.missing_feature_codes) == {
        "MISSING_LIQUIDITY_RATIO",
        "MISSING_MARGIN_COVERAGE_RATIO",
        "MISSING_RECEIVABLE_DAYS",
    }


def test_reference_fit_is_temporally_isolated_replayable_and_reports_calibration() -> None:
    from canopyledger.credit.training import (
        fit_reference_model,
        generate_synthetic_borrower_panel,
        split_temporally_by_borrower,
    )

    panel = generate_synthetic_borrower_panel(borrower_count=12, observations_per_borrower=8)
    split = split_temporally_by_borrower(panel)
    artifact = fit_reference_model(panel)

    assert split.train and split.validation
    assert all(
        max(row.as_of for row in split.train if row.borrower_id == borrower_id)
        < min(row.as_of for row in split.validation if row.borrower_id == borrower_id)
        for borrower_id in {row.borrower_id for row in panel}
    )
    assert artifact.leakage_report.passed is True
    assert artifact.evaluation.roc_auc >= Decimal("0")
    assert artifact.evaluation.pr_auc >= Decimal("0")
    assert artifact.evaluation.brier_score <= Decimal("1")
    assert artifact.evaluation.calibration_curve
    assert artifact.bundle.digest == fit_reference_model(panel).bundle.digest


def test_stage_output_pins_model_and_snapshot_lineage_without_capacity_fields() -> None:
    from canopyledger.credit.engine import (
        CreditFeatureObservation,
        build_reference_bundle,
    )
    from canopyledger.credit.pipeline import (
        build_credit_early_warning_stage_output,
    )

    bundle = build_reference_bundle()
    output = build_credit_early_warning_stage_output(
        snapshot_id="snp_0198a000-0000-7000-8000-000000000601",
        input_digest="sha256:" + "a" * 64,
        policy_bundle_digest="sha256:" + "b" * 64,
        computation_bundle_digest="sha256:" + "c" * 64,
        bundle=bundle,
        observation=CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000000601",
            as_of=datetime(2026, 7, 1, tzinfo=UTC),
            values={
                "payment_delay_days": Decimal("11"),
                "liquidity_ratio": Decimal("1.1"),
                "receivable_days": Decimal("52"),
                "margin_coverage_ratio": Decimal("1.0"),
            },
        ),
        stage_output_id="out_0198a000-0000-7000-8000-000000000601",
        started_at=datetime(2026, 7, 1, tzinfo=UTC),
        completed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert output.stage == "credit_early_warning"
    assert output.result["signal_type"] == "synthetic_deterioration_likelihood"
    assert output.result["model_bundle_digest"] == bundle.digest
    assert "cbb" not in output.result
    assert "availability" not in output.result


def test_credit_projection_api_is_typed_advisory_and_keeps_missing_feature_state() -> None:
    from canopyledger.demo.workspace import SNAPSHOT_ID, create_demo_app

    response = TestClient(create_demo_app()).get(
        f"/api/v1/snapshots/{SNAPSHOT_ID}/credit-early-warning",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "credit_early_warning"
    assert body["advisory_only"] is True
    assert body["signal_type"] == "synthetic_deterioration_likelihood"
    assert body["model_bundle_digest"].startswith("sha256:")
    assert "contractual_borrowing_base" not in body
