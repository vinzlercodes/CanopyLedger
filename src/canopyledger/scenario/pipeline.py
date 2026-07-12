"""Immutable S6 scenario and IRC stage-output envelope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.scenario.engine import ScenarioCapacityInput, evaluate_scenario_capacity


@dataclass(frozen=True)
class ScenarioCapacityStageOutput:
    stage_output_id: str
    snapshot_id: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    scenario: dict[str, Any]
    internal_risk_capacity: dict[str, Any]
    reason_codes: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "stage_output_id": self.stage_output_id,
            "snapshot_id": self.snapshot_id,
            "stage": "scenario_capacity",
            "stage_version": "1.0.0",
            "input_digests": list(self.input_digests),
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "scenario": self.scenario,
            "internal_risk_capacity": self.internal_risk_capacity,
            "reason_codes": list(self.reason_codes),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output_digest": self.output_digest,
        }


def build_scenario_capacity_stage_output(
    value: ScenarioCapacityInput,
    *,
    stage_output_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> ScenarioCapacityStageOutput:
    assessment = evaluate_scenario_capacity(value)
    scenario = {
        "assessment_id": assessment.assessment_id,
        "assessment_digest": assessment.output_digest,
        "result": assessment.result,
    }
    draft = {
        "stage_output_id": stage_output_id,
        "snapshot_id": value.snapshot_id,
        "stage": "scenario_capacity",
        "stage_version": "1.0.0",
        "input_digests": [
            value.cbb_output_digest,
            value.hedge_liquidity_output_digest,
            value.input_digest,
            value.market_bundle_digest,
        ],
        "policy_bundle_digest": value.policy_bundle_digest,
        "computation_bundle_digest": value.computation_bundle_digest,
        "scenario": scenario,
        "internal_risk_capacity": assessment.result["internal_risk_capacity"],
        "reason_codes": list(assessment.reason_codes),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    return ScenarioCapacityStageOutput(
        stage_output_id,
        value.snapshot_id,
        tuple(draft["input_digests"]),
        value.policy_bundle_digest,
        value.computation_bundle_digest,
        scenario,
        assessment.result["internal_risk_capacity"],
        assessment.reason_codes,
        started_at,
        completed_at,
        domain_digest("pipeline_stage_output", 1, canonical_json_bytes(draft)),
    )
