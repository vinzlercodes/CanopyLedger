"""Fresh-database acceptance for M4B durable decision governance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_m1b_postgres_pipeline import _freeze_snapshot

from canopyledger.application.integrity import IntegrityService
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.governance.core import (
    DecisionContext,
    FinalDecisionStatus,
    RecommendationClass,
)
from canopyledger.governance.postgres import PostgresGovernanceService
from canopyledger.persistence.postgres import PostgresIntegrityStore

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 11, 14, tzinfo=UTC)
ANALYST = "act_0198a000-0000-7000-8000-000000000001"
APPROVER = "apr_0198a000-0000-7000-8000-000000000001"
SECOND_APPROVER = "apr_0198a000-0000-7000-8000-000000000002"


def _context(snapshot_id: str) -> DecisionContext:
    return DecisionContext(
        snapshot_id=snapshot_id,
        cbb=Money(Decimal("100000"), "EUR"),
        contractual_availability=Money(Decimal("75000"), "EUR"),
        internal_risk_capacity=Money(Decimal("90000"), "EUR"),
        liquidity_cap=Money(Decimal("95000"), "EUR"),
        facility_commitment=Money(Decimal("120000"), "EUR"),
        policy_caps=(Money(Decimal("85000"), "EUR"),),
        outstanding_exposure=Money(Decimal("20000"), "EUR"),
        approved_unfunded_exposure=Money(Decimal("5000"), "EUR"),
        cbb_output_digest="sha256:" + "a" * 64,
        hedge_liquidity_output_digest="sha256:" + "b" * 64,
        irc_output_digest="sha256:" + "c" * 64,
        policy_bundle_digest="sha256:" + "d" * 64,
    )


def test_durable_governance_survives_restart_and_requires_dual_control(
    database_engine: Engine,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    snapshot_id, _ = _freeze_snapshot(IntegrityService(integrity, clock=lambda: NOW), integrity)
    service = PostgresGovernanceService(database_engine, clock=lambda: NOW)
    recommendation_id = new_resource_id("rec")
    approval_request_id = new_resource_id("arq")
    original_action_id = new_resource_id("apa")
    original_decision_id = new_resource_id("fdc")
    override_id = new_resource_id("ovr")
    first_override_action_id = new_resource_id("apa")
    second_override_action_id = new_resource_id("apa")
    recommendation = service.execute(
        lambda state: state.create_recommendation(
            context=_context(snapshot_id),
            recommendation_id=recommendation_id,
            author_id=ANALYST,
            requested_amount=Money(Decimal("70000"), "EUR"),
            recommendation_class=RecommendationClass.APPROVE_WITH_CONDITIONS,
            conditions=("VERIFY_INSURANCE",),
            reason_codes=("IRC_POLICY_CAP_BINDS",),
            expires_at=NOW + timedelta(days=1),
        )
    )
    request = service.execute(
        lambda state: state.create_approval_request(
            approval_request_id=approval_request_id,
            recommendation_id=recommendation.resource_id,
            requested_by=ANALYST,
            expires_at=NOW + timedelta(days=1),
        )
    )
    original = service.execute(
        lambda state: state.approve(
            approval_action_id=original_action_id,
            final_decision_id=original_decision_id,
            approval_request_id=request.resource_id,
            approver_id=APPROVER,
            reason="approved with conditions",
        )
    )
    assert original.status is FinalDecisionStatus.APPROVED
    override = service.execute(
        lambda state: state.create_override_request(
            override_id=override_id,
            original_decision_id=original.resource_id,
            requester_id=ANALYST,
            proposed_exposure_cap=Money(Decimal("95000"), "EUR"),
            reason="temporary exception",
            policy_basis="credit-policy-7.2",
            expires_at=NOW + timedelta(days=1),
            requires_dual_control=True,
        )
    )
    assert (
        service.execute(
            lambda state: state.approve_override(
                override.resource_id,
                APPROVER,
                "first approval",
                approval_action_id=first_override_action_id,
            )
        )
        is None
    )
    replacement = service.execute(
        lambda state: state.approve_override(
            override.resource_id,
            SECOND_APPROVER,
            "second approval",
            approval_action_id=second_override_action_id,
        )
    )
    assert replacement is not None
    restarted = PostgresGovernanceService(database_engine, clock=lambda: NOW)
    assert restarted.get_decision(original.resource_id).superseded_by == replacement.resource_id
    assert restarted.get_recommendation(recommendation.resource_id) == recommendation
    assert restarted.get_override(override.resource_id).digest == override.digest
    assert restarted.get_override(override.resource_id).created_at == override.created_at
    with (
        pytest.raises(DBAPIError, match="final decision mutation is forbidden"),
        database_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE canopyledger.final_decision SET status = 'REJECTED' "
                "WHERE resource_id = :resource_id"
            ),
            {"resource_id": replacement.resource_id},
        )
    with (
        pytest.raises(DBAPIError, match="supersession cannot be cyclic"),
        database_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE canopyledger.final_decision SET superseded_by = :original "
                "WHERE resource_id = :replacement"
            ),
            {"original": original.resource_id, "replacement": replacement.resource_id},
        )
