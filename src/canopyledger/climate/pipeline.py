"""Immutable M5 climate/EUDR stage-output envelope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from canopyledger.climate.engine import ClimateEudrInput, assess_climate_eudr
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


@dataclass(frozen=True)
class ClimateEudrStageOutput:
    """One published, replayable M5 output for a frozen snapshot."""

    stage_output_id: str
    snapshot_id: str
    input_digests: tuple[str, ...]
    legal_interpretation_bundle_digest: str
    policy_bundle_digest: str
    computation_bundle_digest: str
    result: dict[str, object]
    reason_codes: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "stage_output_id": self.stage_output_id,
            "snapshot_id": self.snapshot_id,
            "stage": "climate_eudr",
            "stage_version": "1.0.0",
            "input_digests": list(self.input_digests),
            "legal_interpretation_bundle_digest": self.legal_interpretation_bundle_digest,
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "result": self.result,
            "reason_codes": list(self.reason_codes),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output_digest": self.output_digest,
        }


def build_climate_eudr_stage_output(
    value: ClimateEudrInput,
    *,
    stage_output_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> ClimateEudrStageOutput:
    """Build the deterministic M5 stage without accessing mutable state or providers."""
    assessment = assess_climate_eudr(value, completed_at=completed_at)
    draft: dict[str, object] = {
        "stage_output_id": stage_output_id,
        "snapshot_id": value.snapshot_id,
        "stage": "climate_eudr",
        "stage_version": "1.0.0",
        "input_digests": [value.input_digest, value.legal_interpretation_bundle_digest],
        "legal_interpretation_bundle_digest": value.legal_interpretation_bundle_digest,
        "policy_bundle_digest": value.policy_bundle_digest,
        "computation_bundle_digest": value.computation_bundle_digest,
        "result": assessment.result,
        "reason_codes": list(assessment.reason_codes),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    return ClimateEudrStageOutput(
        stage_output_id=stage_output_id,
        snapshot_id=value.snapshot_id,
        input_digests=tuple(draft["input_digests"]),  # type: ignore[arg-type]
        legal_interpretation_bundle_digest=value.legal_interpretation_bundle_digest,
        policy_bundle_digest=value.policy_bundle_digest,
        computation_bundle_digest=value.computation_bundle_digest,
        result=assessment.result,
        reason_codes=assessment.reason_codes,
        started_at=started_at,
        completed_at=completed_at,
        output_digest=domain_digest("pipeline_stage_output", 1, canonical_json_bytes(draft)),
    )
