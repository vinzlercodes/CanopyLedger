"""M4B authoritative decision-context derivation contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from canopyledger.governance.core import GovernanceError
from canopyledger.governance.postgres import decision_context_from_published
from canopyledger.integrity.canonical import canonical_json_bytes


def _row(resource_id: str, digest: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "output_digest": digest,
        "canonical_output": canonical_json_bytes(payload),
    }


def _published_outputs() -> list[dict[str, object]]:
    return [
        _row(
            "out_0198a000-0000-7000-8000-000000000001",
            "sha256:" + "a" * 64,
            {
                "stage": "contractual_borrowing_base",
                "result": {
                    "currency": "USD",
                    "contractual_borrowing_base": "100000.00",
                    "contractual_availability": "74000.00",
                    "facility_limit": "120000.00",
                    "current_principal": "20000.00",
                    "lc_exposure": "5000.00",
                    "other_contractual_usage": "1000.00",
                },
            },
        ),
        _row(
            "out_0198a000-0000-7000-8000-000000000002",
            "sha256:" + "b" * 64,
            {
                "stage": "hedge_liquidity",
                "result": {"assessment": {"liquidity": {"total_liquidity_available": "95000.00"}}},
            },
        ),
        _row(
            "out_0198a000-0000-7000-8000-000000000003",
            "sha256:" + "c" * 64,
            {"stage": "scenario_capacity"},
        ),
    ]


def test_decision_context_uses_only_published_outputs_and_matching_irc() -> None:
    context = decision_context_from_published(
        "snp_0198a000-0000-7000-8000-000000000001",
        {"policy_bundle_digest": "sha256:" + "d" * 64},
        _published_outputs(),
        {
            "scenario_stage_output_id": "out_0198a000-0000-7000-8000-000000000003",
            "cbb_output_digest": "sha256:" + "a" * 64,
            "irc": "90000.00",
            "currency": "USD",
        },
    )

    assert context.cbb.amount == Decimal("100000.00")
    assert context.contractual_availability.amount == Decimal("74000.00")
    assert context.internal_risk_capacity.amount == Decimal("90000.00")
    assert context.liquidity_cap.amount == Decimal("95000.00")
    assert context.outstanding_exposure.amount == Decimal("26000.00")
    assert context.irc_output_digest == "sha256:" + "c" * 64


def test_decision_context_rejects_missing_required_stage_output() -> None:
    outputs = _published_outputs()
    with pytest.raises(GovernanceError, match="hedge_liquidity"):
        decision_context_from_published(
            "snp_0198a000-0000-7000-8000-000000000001",
            {"policy_bundle_digest": "sha256:" + "d" * 64},
            [outputs[0], outputs[2]],
            {
                "scenario_stage_output_id": "out_0198a000-0000-7000-8000-000000000003",
                "cbb_output_digest": "sha256:" + "a" * 64,
                "irc": "90000.00",
                "currency": "USD",
            },
        )
