"""M4B authenticated recommendation and approval API workflow."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from canopyledger.api.app import create_app
from canopyledger.domain.money import Money
from canopyledger.governance.core import DecisionContext, GovernanceService, RecommendationClass


def test_recommendation_to_human_approval_rejects_self_approval() -> None:
    expires_at = (datetime(2026, 7, 12, tzinfo=UTC)).isoformat()
    request = {
        "recommendation_id": "rec_0198a000-0000-7000-8000-000000000001",
        "requested_amount": {"amount": "70000", "currency": "USD"},
        "recommendation_class": "APPROVE_WITH_CONDITIONS",
        "conditions": ["VERIFY_INSURANCE"],
        "reason_codes": ["IRC_POLICY_CAP_BINDS"],
        "expires_at": expires_at,
        "cbb": {"amount": "100000", "currency": "USD"},
        "contractual_availability": {"amount": "75000", "currency": "USD"},
        "internal_risk_capacity": {"amount": "90000", "currency": "USD"},
        "liquidity_cap": {"amount": "95000", "currency": "USD"},
        "facility_commitment": {"amount": "120000", "currency": "USD"},
        "policy_caps": [{"amount": "85000", "currency": "USD"}],
        "outstanding_exposure": {"amount": "20000", "currency": "USD"},
        "approved_unfunded_exposure": {"amount": "5000", "currency": "USD"},
        "cbb_output_digest": "sha256:" + "a" * 64,
        "hedge_liquidity_output_digest": "sha256:" + "b" * 64,
        "irc_output_digest": "sha256:" + "c" * 64,
        "policy_bundle_digest": "sha256:" + "d" * 64,
    }
    app = create_app(clock=lambda: datetime(2026, 7, 11, tzinfo=UTC))
    analyst = {"Authorization": "Bearer analyst-demo-token"}
    response = TestClient(app).post(
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000001/recommendations",
        headers=analyst,
        json=request,
    )
    assert response.status_code == 201, response.text
    approval = TestClient(app).post(
        "/api/v1/recommendations/rec_0198a000-0000-7000-8000-000000000001/approval-requests",
        headers=analyst,
        json={
            "approval_request_id": "arq_0198a000-0000-7000-8000-000000000001",
            "expires_at": expires_at,
        },
    )
    assert approval.status_code == 201, approval.text
    action = {
        "approval_action_id": "apa_0198a000-0000-7000-8000-000000000001",
        "final_decision_id": "fdc_0198a000-0000-7000-8000-000000000001",
        "reason": "approve",
    }
    denied = TestClient(app).post(
        "/api/v1/approval-requests/arq_0198a000-0000-7000-8000-000000000001/approve",
        headers=analyst,
        json=action,
    )
    assert denied.status_code == 403
    approved = TestClient(app).post(
        "/api/v1/approval-requests/arq_0198a000-0000-7000-8000-000000000001/approve",
        headers={"Authorization": "Bearer approver-demo-token"},
        json=action,
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["status"] == "APPROVED"
    decision = TestClient(app).get(
        "/api/v1/decisions/fdc_0198a000-0000-7000-8000-000000000001",
        headers={"Authorization": "Bearer approver-demo-token"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "APPROVED"
    override = TestClient(app).post(
        "/api/v1/recommendations/rec_0198a000-0000-7000-8000-000000000001/override-requests",
        headers=analyst,
        json={
            "override_id": "ovr_0198a000-0000-7000-8000-000000000003",
            "proposed_exposure_cap": {"amount": "80000", "currency": "USD"},
            "reason": "temporary exception",
            "policy_basis": "credit-policy-7.2",
            "expires_at": expires_at,
        },
    )
    assert override.status_code == 201, override.text


def test_approval_workspace_is_authenticated_and_explains_governed_separation() -> None:
    response = TestClient(create_app()).get(
        "/ui/approval-workspace",
        headers={"Authorization": "Bearer approver-demo-token"},
    )
    assert response.status_code == 200
    assert "Approval workspace" in response.text
    assert "separate\nimmutable resources" in response.text
    assert "Governed action console" in response.text
    assert "Record human decision" in response.text
    assert "dual-control override" in response.text


def test_initial_workspaces_are_authenticated_and_keep_cbb_and_irc_distinct() -> None:
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer analyst-demo-token"}
    cockpit = client.get("/ui/facility-cockpit", headers=headers)
    assert cockpit.status_code == 200
    assert "Contractual Borrowing Base" in cockpit.text
    assert "Internal Risk Capacity" in cockpit.text
    for path in ("/ui/collateral-workspace", "/ui/hedge-lab", "/ui/scenario-lab"):
        assert client.get(path, headers=headers).status_code == 200


def test_analytical_workspaces_render_only_frozen_snapshot_outputs() -> None:
    snapshot_id = "snp_0198a000-0000-7000-8000-000000000004"
    app = create_app(
        collateral_output_loader=lambda _: {"collateral_valuation": {"inventory": ["lot-1"]}},
        hedge_output_loader=lambda _: {"stage": "hedge_liquidity", "reason_codes": ["MARGIN"]},
        scenario_output_loader=lambda _: {"stage": "scenario_capacity", "reason_codes": ["IRC"]},
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer analyst-demo-token"}
    for path, expected in (
        ("/ui/collateral-workspace", "collateral_valuation"),
        ("/ui/hedge-lab", "hedge_liquidity"),
        ("/ui/scenario-lab", "scenario_capacity"),
    ):
        response = client.get(f"{path}?snapshot_id={snapshot_id}", headers=headers)
        assert response.status_code == 200
        assert expected in response.text


def test_final_decision_endpoint_requires_credit_approver_authority() -> None:
    now = datetime(2026, 7, 11, tzinfo=UTC)
    governance = GovernanceService(clock=lambda: now)
    recommendation = governance.create_recommendation(
        context=DecisionContext(
            snapshot_id="snp_0198a000-0000-7000-8000-000000000002",
            cbb=Money(Decimal("100000"), "USD"),
            contractual_availability=Money(Decimal("100000"), "USD"),
            internal_risk_capacity=Money(Decimal("90000"), "USD"),
            liquidity_cap=Money(Decimal("95000"), "USD"),
            facility_commitment=Money(Decimal("120000"), "USD"),
            policy_caps=(),
            outstanding_exposure=Money(Decimal("0"), "USD"),
            approved_unfunded_exposure=Money(Decimal("0"), "USD"),
            cbb_output_digest="sha256:" + "a" * 64,
            hedge_liquidity_output_digest="sha256:" + "b" * 64,
            irc_output_digest="sha256:" + "c" * 64,
            policy_bundle_digest="sha256:" + "d" * 64,
        ),
        recommendation_id="rec_0198a000-0000-7000-8000-000000000002",
        author_id="act_0198a000-0000-7000-8000-000000000099",
        requested_amount=Money(Decimal("70000"), "USD"),
        recommendation_class=RecommendationClass.APPROVE,
        conditions=(),
        reason_codes=(),
        expires_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    request = governance.create_approval_request(
        approval_request_id="arq_0198a000-0000-7000-8000-000000000002",
        recommendation_id=recommendation.resource_id,
        requested_by="act_0198a000-0000-7000-8000-000000000099",
        expires_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    response = TestClient(create_app(clock=lambda: now, governance_service=governance)).post(
        f"/api/v1/approval-requests/{request.resource_id}/approve",
        headers={"Authorization": "Bearer analyst-demo-token"},
        json={
            "approval_action_id": "apa_0198a000-0000-7000-8000-000000000010",
            "final_decision_id": "fdc_0198a000-0000-7000-8000-000000000008",
            "reason": "approve",
        },
    )
    assert response.status_code == 403


def test_authoritative_context_loader_ignores_browser_calculation_values() -> None:
    now = datetime(2026, 7, 11, tzinfo=UTC)
    governance = GovernanceService(clock=lambda: now)

    def load_context(snapshot_id: str) -> DecisionContext:
        return DecisionContext(
            snapshot_id=snapshot_id,
            cbb=Money(Decimal("100000"), "USD"),
            contractual_availability=Money(Decimal("80000"), "USD"),
            internal_risk_capacity=Money(Decimal("90000"), "USD"),
            liquidity_cap=Money(Decimal("95000"), "USD"),
            facility_commitment=Money(Decimal("120000"), "USD"),
            policy_caps=(),
            outstanding_exposure=Money(Decimal("20000"), "USD"),
            approved_unfunded_exposure=Money(Decimal("0"), "USD"),
            cbb_output_digest="sha256:" + "a" * 64,
            hedge_liquidity_output_digest="sha256:" + "b" * 64,
            irc_output_digest="sha256:" + "c" * 64,
            policy_bundle_digest="sha256:" + "d" * 64,
        )

    client = TestClient(
        create_app(
            clock=lambda: now,
            governance_service=governance,
            decision_context_loader=load_context,
        )
    )
    response = client.post(
        "/api/v1/snapshots/snp_0198a000-0000-7000-8000-000000000003/recommendations",
        headers={"Authorization": "Bearer analyst-demo-token"},
        json={
            "recommendation_id": "rec_0198a000-0000-7000-8000-000000000003",
            "requested_amount": {"amount": "70000", "currency": "USD"},
            "recommendation_class": "APPROVE",
            "expires_at": "2026-07-12T00:00:00+00:00",
            "cbb": {"amount": "1", "currency": "USD"},
        },
    )

    assert response.status_code == 201, response.text
    recommendation = governance.get_recommendation(response.json()["resource_id"])
    assert recommendation.recommended_exposure_cap.amount == Decimal("90000.00")
    assert recommendation.output_digests[0] == "sha256:" + "a" * 64
    cockpit = client.get(
        "/ui/facility-cockpit?snapshot_id=snp_0198a000-0000-7000-8000-000000000003",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )
    assert cockpit.status_code == 200
    assert "100000.00 USD" in cockpit.text
    assert "90000.00 USD" in cockpit.text
    assert "Internal Risk Capacity" in cockpit.text
    workspace = client.get(
        "/ui/approval-workspace?recommendation_id=rec_0198a000-0000-7000-8000-000000000003",
        headers={"Authorization": "Bearer analyst-demo-token"},
    )
    assert workspace.status_code == 200
    assert "Recommendation review" in workspace.text
    assert "70000.00 USD" in workspace.text
    assert "80000.00 USD" in workspace.text


def test_public_override_workflow_cannot_disable_dual_control() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/decisions/fdc_0198a000-0000-7000-8000-000000000001/override-requests",
        headers={"Authorization": "Bearer analyst-demo-token"},
        json={
            "override_id": "ovr_0198a000-0000-7000-8000-000000000009",
            "proposed_exposure_cap": {"amount": "90000", "currency": "USD"},
            "reason": "temporary exception",
            "policy_basis": "credit-policy-7.2",
            "expires_at": "2026-07-20T00:00:00+00:00",
            "requires_dual_control": False,
        },
    )
    assert response.status_code == 422
