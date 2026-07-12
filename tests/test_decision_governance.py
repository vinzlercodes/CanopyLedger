"""M4B governed recommendation and decision contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from canopyledger.domain.money import Money
from canopyledger.governance.core import (
    ApprovalDenied,
    ApprovalRequestExpired,
    DecisionContext,
    GovernanceError,
    GovernanceService,
    RecommendationClass,
    ReportIneligible,
    SupersededDecision,
)
from canopyledger.persistence.schema import final_decision

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)
ANALYST = "act_0198a000-0000-7000-8000-000000000001"
APPROVER = "apr_0198a000-0000-7000-8000-000000000001"
SECOND_APPROVER = "apr_0198a000-0000-7000-8000-000000000002"


def _context() -> DecisionContext:
    return DecisionContext(
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        cbb=Money(Decimal("100000"), "USD"),
        contractual_availability=Money(Decimal("75000"), "USD"),
        internal_risk_capacity=Money(Decimal("90000"), "USD"),
        liquidity_cap=Money(Decimal("95000"), "USD"),
        facility_commitment=Money(Decimal("120000"), "USD"),
        policy_caps=(Money(Decimal("85000"), "USD"),),
        outstanding_exposure=Money(Decimal("20000"), "USD"),
        approved_unfunded_exposure=Money(Decimal("5000"), "USD"),
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        irc_output_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
    )


def _recommendation(service: GovernanceService):
    return service.create_recommendation(
        context=_context(),
        recommendation_id="rec_0198a000-0000-7000-8000-000000000001",
        author_id=ANALYST,
        requested_amount=Money(Decimal("70000"), "USD"),
        recommendation_class=RecommendationClass.APPROVE_WITH_CONDITIONS,
        conditions=("VERIFY_INSURANCE",),
        reason_codes=("IRC_POLICY_CAP_BINDS",),
        expires_at=NOW + timedelta(days=1),
    )


def test_recommendation_records_independent_caps_binding_constraint_and_safe_draw() -> None:
    recommendation = _recommendation(GovernanceService(clock=lambda: NOW))

    assert recommendation.binding_constraint == "POLICY_CAP_1"
    assert recommendation.recommended_exposure_cap.amount == Decimal("85000.00")
    assert recommendation.recommended_incremental_draw.amount == Decimal("60000.00")
    assert recommendation.compared_limits["contractual_borrowing_base"] == "100000.00"
    assert recommendation.compared_limits["internal_risk_capacity"] == "90000.00"
    assert recommendation.compared_limits["contractual_availability"] == "75000.00"
    assert recommendation.contractual_availability.amount == Decimal("75000.00")


def test_contractual_availability_can_bind_incremental_draw() -> None:
    context = _context()
    constrained = DecisionContext(
        **{**context.__dict__, "contractual_availability": Money(Decimal("10000"), "USD")}
    )
    recommendation = GovernanceService(clock=lambda: NOW).create_recommendation(
        context=constrained,
        recommendation_id="rec_0198a000-0000-7000-8000-000000000008",
        author_id=ANALYST,
        requested_amount=Money(Decimal("70000"), "USD"),
        recommendation_class=RecommendationClass.APPROVE,
        conditions=(),
        reason_codes=(),
        expires_at=NOW + timedelta(days=1),
    )
    assert recommendation.binding_constraint == "CONTRACTUAL_AVAILABILITY"
    assert recommendation.recommended_incremental_draw.amount == Decimal("10000.00")


def test_override_final_decision_has_durable_foreign_key_lineage() -> None:
    targets = {
        foreign_key.target_fullname for foreign_key in final_decision.c.override_id.foreign_keys
    }
    assert "canopyledger.decision_override.resource_id" in targets


def test_no_self_approval_and_expired_request_are_rejected() -> None:
    service = GovernanceService(clock=lambda: NOW)
    recommendation = _recommendation(service)
    request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000001",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(hours=1),
    )

    with pytest.raises(ApprovalDenied, match="self-approval"):
        service.approve(
            approval_action_id="apa_0198a000-0000-7000-8000-000000000001",
            final_decision_id="fdc_0198a000-0000-7000-8000-000000000001",
            approval_request_id=request.resource_id,
            approver_id=ANALYST,
            reason="approve",
        )

    current_time = NOW
    expired = GovernanceService(clock=lambda: current_time)
    expired._recommendations[recommendation.resource_id] = recommendation  # test fixture state
    expired_request = expired.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000002",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=3),
    )
    current_time = NOW + timedelta(days=4)
    with pytest.raises(ApprovalRequestExpired):
        expired.approve(
            approval_action_id="apa_0198a000-0000-7000-8000-000000000002",
            final_decision_id="fdc_0198a000-0000-7000-8000-000000000002",
            approval_request_id=expired_request.resource_id,
            approver_id=APPROVER,
            reason="approve",
        )


def test_override_preserves_recommendation_requires_dual_control_and_supersedes() -> None:
    service = GovernanceService(clock=lambda: NOW)
    recommendation = _recommendation(service)
    approval_request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000003",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=1),
    )
    original = service.approve(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000003",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000003",
        approval_request_id=approval_request.resource_id,
        approver_id=APPROVER,
        reason="approve with conditions",
    )
    override = service.create_override_request(
        override_id="ovr_0198a000-0000-7000-8000-000000000001",
        original_decision_id=original.resource_id,
        requester_id=ANALYST,
        proposed_exposure_cap=Money(Decimal("95000"), "USD"),
        reason="temporary exception",
        policy_basis="credit-policy-7.2",
        expires_at=NOW + timedelta(days=1),
        requires_dual_control=True,
    )
    assert service.get_recommendation(recommendation.resource_id) == recommendation

    assert (
        service.approve_override(
            override.resource_id,
            APPROVER,
            "first approval",
            approval_action_id="apa_0198a000-0000-7000-8000-000000000004",
        )
        is None
    )
    first_action = service._approval_actions["apa_0198a000-0000-7000-8000-000000000004"]
    assert first_action.approval_request_id is None
    assert first_action.override_id == override.resource_id
    assert service.get_override(override.resource_id).digest == override.digest
    replacement = service.approve_override(
        override.resource_id,
        SECOND_APPROVER,
        "second approval",
        approval_action_id="apa_0198a000-0000-7000-8000-000000000005",
    )
    assert replacement is not None
    assert service.get_decision(original.resource_id).superseded_by == replacement.resource_id
    with pytest.raises(SupersededDecision):
        service.assert_report_eligible(original.resource_id)
    assert service.assert_report_eligible(replacement.resource_id) == replacement


def test_rejected_decision_is_report_ineligible() -> None:
    service = GovernanceService(clock=lambda: NOW)
    recommendation = _recommendation(service)
    request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000004",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=1),
    )
    decision = service.reject(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000006",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000004",
        approval_request_id=request.resource_id,
        approver_id=APPROVER,
        reason="declined after review",
    )
    with pytest.raises(ReportIneligible):
        service.assert_report_eligible(decision.resource_id)


def test_second_final_decision_and_reused_approval_request_are_rejected() -> None:
    service = GovernanceService(clock=lambda: NOW)
    recommendation = _recommendation(service)
    request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000005",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=1),
    )
    service.approve(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000007",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000005",
        approval_request_id=request.resource_id,
        approver_id=APPROVER,
        reason="approved",
    )
    with pytest.raises(GovernanceError, match="already been decided"):
        service.approve(
            approval_action_id="apa_0198a000-0000-7000-8000-000000000008",
            final_decision_id="fdc_0198a000-0000-7000-8000-000000000006",
            approval_request_id=request.resource_id,
            approver_id=SECOND_APPROVER,
            reason="duplicate approval",
        )
    second_recommendation = service.create_recommendation(
        context=_context(),
        recommendation_id="rec_0198a000-0000-7000-8000-000000000009",
        author_id=ANALYST,
        requested_amount=Money(Decimal("60000"), "USD"),
        recommendation_class=RecommendationClass.APPROVE,
        conditions=(),
        reason_codes=(),
        expires_at=NOW + timedelta(days=1),
    )
    second_request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000009",
        recommendation_id=second_recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=1),
    )
    with pytest.raises(SupersededDecision, match="current final decision"):
        service.approve(
            approval_action_id="apa_0198a000-0000-7000-8000-000000000011",
            final_decision_id="fdc_0198a000-0000-7000-8000-000000000009",
            approval_request_id=second_request.resource_id,
            approver_id=SECOND_APPROVER,
            reason="conflicting decision",
        )


def test_reinstating_a_rejected_decision_requires_dual_control() -> None:
    service = GovernanceService(clock=lambda: NOW)
    recommendation = _recommendation(service)
    request = service.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000006",
        recommendation_id=recommendation.resource_id,
        requested_by=ANALYST,
        expires_at=NOW + timedelta(days=1),
    )
    rejected = service.reject(
        approval_action_id="apa_0198a000-0000-7000-8000-000000000009",
        final_decision_id="fdc_0198a000-0000-7000-8000-000000000007",
        approval_request_id=request.resource_id,
        approver_id=APPROVER,
        reason="declined",
    )
    with pytest.raises(ApprovalDenied, match="requires dual control"):
        service.create_override_request(
            override_id="ovr_0198a000-0000-7000-8000-000000000002",
            original_decision_id=rejected.resource_id,
            requester_id=ANALYST,
            proposed_exposure_cap=Money(Decimal("80000"), "USD"),
            reason="reconsidered evidence",
            policy_basis="credit-policy-7.2",
            expires_at=NOW + timedelta(days=1),
            requires_dual_control=False,
        )
