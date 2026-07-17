"""M10 durable report-model and artifact acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_m1b_postgres_pipeline import _freeze_snapshot

from canopyledger.application.integrity import IntegrityService
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.governance.core import DecisionContext, RecommendationClass
from canopyledger.governance.postgres import PostgresGovernanceService
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.reporting.core import ReportCompileInput, ReportModelCompiler, ReportPackageKind
from canopyledger.reporting.postgres import PostgresReportService
from canopyledger.reporting.service import reference_renderer_manifest, reference_report_renderer

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
ANALYST = "act_0198a000-0000-7000-8000-000000000001"
APPROVER = "apr_0198a000-0000-7000-8000-000000000001"


def test_report_package_survives_restart_and_immutable_database_guards(
    database_engine: Engine,
) -> None:
    integrity_store = PostgresIntegrityStore(database_engine)
    integrity = IntegrityService(integrity_store, clock=lambda: NOW)
    snapshot_id, _ = _freeze_snapshot(integrity, integrity_store)
    snapshot = json.loads(integrity.get_snapshot_manifest(snapshot_id).body)
    governance = PostgresGovernanceService(database_engine, clock=lambda: NOW)
    context = DecisionContext(
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
        policy_bundle_digest=str(snapshot["policy_bundle"]["digest"]),
    )
    recommendation = governance.execute(
        lambda state: state.create_recommendation(
            context=context,
            recommendation_id=new_resource_id("rec"),
            author_id=ANALYST,
            requested_amount=Money(Decimal("60000"), "EUR"),
            recommendation_class=RecommendationClass.APPROVE,
            conditions=(),
            reason_codes=(),
            expires_at=NOW + timedelta(days=1),
        )
    )
    request = governance.execute(
        lambda state: state.create_approval_request(
            approval_request_id=new_resource_id("arq"),
            recommendation_id=recommendation.resource_id,
            requested_by=ANALYST,
            expires_at=NOW + timedelta(days=1),
        )
    )
    decision = governance.execute(
        lambda state: state.approve(
            approval_action_id=new_resource_id("apa"),
            final_decision_id=new_resource_id("fdc"),
            approval_request_id=request.resource_id,
            approver_id=APPROVER,
            reason="independent M10 report approval",
        )
    )
    report = PostgresReportService(
        database_engine,
        compiler=ReportModelCompiler(),
        renderer=reference_report_renderer(),
    ).generate(_source(snapshot, decision.resource_id, decision.digest))

    restarted = PostgresReportService(
        database_engine,
        compiler=ReportModelCompiler(),
        renderer=reference_report_renderer(),
    ).get(report.report_model.resource_id)
    assert restarted.report_model.digest == report.report_model.digest
    assert [item.digest for item in restarted.artifacts] == [
        item.digest for item in report.artifacts
    ]
    with (
        pytest.raises(DBAPIError, match="immutable"),
        database_engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE canopyledger.report_model SET package_kind = 'HISTORICAL_AUDIT'")
        )


def _source(
    snapshot: dict[str, object], decision_id: str, decision_digest: str
) -> ReportCompileInput:
    renderer = reference_renderer_manifest()
    return ReportCompileInput(
        report_id=new_resource_id("rpt"),
        package_kind=ReportPackageKind.CURRENT_OFFICIAL,
        decision={
            "resource_id": decision_id,
            "snapshot_id": snapshot["snapshot_id"],
            "status": "APPROVED",
            "superseded_by": None,
            "digest": decision_digest,
        },
        snapshot=snapshot,
        decision_pack={
            "contractual_borrowing_base": {"amount": "100000.00", "currency": "EUR"},
            "contractual_availability": {"amount": "75000.00", "currency": "EUR"},
            "internal_risk_capacity": {"amount": "90000.00", "currency": "EUR"},
            "recommendation": {
                "recommended_incremental_draw": {"amount": "60000.00", "currency": "EUR"}
            },
            "final_decision": {"resource_id": decision_id},
        },
        stage_outputs={
            name: {"output_digest": "sha256:" + character * 64}
            for name, character in (
                ("collateral", "a"),
                ("hedge", "b"),
                ("scenario", "c"),
                ("climate", "d"),
                ("credit", "e"),
            )
        },
        template_version="committee-pack-v1",
        renderer_manifest={
            "renderer": "canopyledger-html-v1",
            "font_digest": str(renderer["font_digest"]),
            "locale": "en-US",
            "timezone": "UTC",
        },
        created_at=NOW,
    )
