"""Pure S5 hedge/liquidity stage-output contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from canopyledger.hedge.engine import HedgeLiquidityInput, evaluate_hedge_and_liquidity
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


@dataclass(frozen=True)
class HedgeLiquidityStageOutput:
    """Immutable S5 wrapper around the deterministic hedge/liquidity assessment."""

    stage_output_id: str
    snapshot_id: str
    input_digests: tuple[str, ...]
    policy_bundle_digest: str
    computation_bundle_digest: str
    result: dict[str, Any]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    output_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "stage_output_id": self.stage_output_id,
            "snapshot_id": self.snapshot_id,
            "stage": "hedge_liquidity",
            "stage_version": "1.0.0",
            "input_digests": list(self.input_digests),
            "policy_bundle_digest": self.policy_bundle_digest,
            "computation_bundle_digest": self.computation_bundle_digest,
            "result": self.result,
            "warnings": list(self.warnings),
            "reason_codes": list(self.reason_codes),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output_digest": self.output_digest,
        }


def build_hedge_liquidity_stage_output(
    value: HedgeLiquidityInput,
    *,
    stage_output_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> HedgeLiquidityStageOutput:
    """Build a replayable S5 output from a frozen hedge input and S4 CBB output."""
    assessment = evaluate_hedge_and_liquidity(value)
    result = {
        "assessment_id": assessment.assessment_id,
        "assessment_digest": assessment.output_digest,
        "assessment": assessment.result,
    }
    draft = {
        "stage_output_id": stage_output_id,
        "snapshot_id": value.snapshot_id,
        "stage": "hedge_liquidity",
        "stage_version": "1.0.0",
        "input_digests": [
            value.cbb_output_digest,
            value.input_digest,
            value.market_bundle_digest,
        ],
        "policy_bundle_digest": value.policy_bundle_digest,
        "computation_bundle_digest": value.computation_bundle_digest,
        "result": result,
        "warnings": [],
        "reason_codes": list(assessment.reason_codes),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    return HedgeLiquidityStageOutput(
        stage_output_id=stage_output_id,
        snapshot_id=value.snapshot_id,
        input_digests=(
            value.cbb_output_digest,
            value.input_digest,
            value.market_bundle_digest,
        ),
        policy_bundle_digest=value.policy_bundle_digest,
        computation_bundle_digest=value.computation_bundle_digest,
        result=result,
        warnings=(),
        reason_codes=assessment.reason_codes,
        started_at=started_at,
        completed_at=completed_at,
        output_digest=domain_digest(
            "pipeline_stage_output",
            1,
            canonical_json_bytes(draft),
        ),
    )
