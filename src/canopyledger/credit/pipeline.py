"""Immutable M6 credit early-warning stage-output envelope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from canopyledger.credit.engine import (
    CreditFeatureObservation,
    CreditModelBundle,
    infer_deterioration_signal,
)
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


@dataclass(frozen=True)
class CreditEarlyWarningStageOutput:
    stage_output_id: str
    snapshot_id: str
    stage: str
    stage_version: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    result: dict[str, object]
    reason_codes: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    output_digest: str

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "stage_output_id": self.stage_output_id,
            "snapshot_id": self.snapshot_id,
            "stage": self.stage,
            "stage_version": self.stage_version,
            "input_digests": list(self.input_digests),
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "result": self.result,
            "reason_codes": list(self.reason_codes),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output_digest": self.output_digest,
        }


def build_credit_early_warning_stage_output(
    *,
    snapshot_id: str,
    input_digest: str,
    policy_bundle_digest: str,
    computation_bundle_digest: str,
    bundle: CreditModelBundle,
    observation: CreditFeatureObservation,
    stage_output_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> CreditEarlyWarningStageOutput:
    """Create a fully pinned advisory stage; capacity calculations are intentionally absent."""
    signal = infer_deterioration_signal(bundle, observation)
    result: dict[str, object] = {
        "signal_type": signal.signal_type,
        "horizon_days": signal.horizon_days,
        "probability": str(signal.probability),
        "band": signal.band,
        "top_reason_codes": list(signal.top_reason_codes),
        "missing_feature_codes": list(signal.missing_feature_codes),
        "hard_rule_codes": list(signal.hard_rule_codes),
        "model_bundle_digest": signal.model_bundle_digest,
        "advisory_only": True,
        "as_of": observation.as_of.isoformat(),
    }
    draft = {
        "stage_output_id": stage_output_id,
        "snapshot_id": snapshot_id,
        "stage": "credit_early_warning",
        "stage_version": "1.0.0",
        "input_digests": [input_digest, bundle.digest],
        "policy_bundle_digest": policy_bundle_digest,
        "computation_bundle_digest": computation_bundle_digest,
        "result": result,
        "reason_codes": list(
            (*signal.hard_rule_codes, *signal.missing_feature_codes, *signal.top_reason_codes)
        ),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    return CreditEarlyWarningStageOutput(
        stage_output_id=stage_output_id,
        snapshot_id=snapshot_id,
        stage="credit_early_warning",
        stage_version="1.0.0",
        input_digests=(input_digest, bundle.digest),
        policy_bundle_digest=policy_bundle_digest,
        computation_bundle_digest=computation_bundle_digest,
        result=result,
        reason_codes=tuple(
            (*signal.hard_rule_codes, *signal.missing_feature_codes, *signal.top_reason_codes)
        ),
        started_at=started_at,
        completed_at=completed_at,
        output_digest=domain_digest("pipeline_stage_output", 1, canonical_json_bytes(draft)),
    )
