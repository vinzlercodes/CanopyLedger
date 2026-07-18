"""Durable PostgreSQL adapter for M4B immutable governance resources."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import DBAPIError

from canopyledger.domain.money import Money
from canopyledger.governance.core import (
    ApprovalAction,
    ApprovalRequest,
    DecisionContext,
    DecisionOverride,
    FinalDecision,
    FinalDecisionStatus,
    GovernanceError,
    GovernanceService,
    GovernanceTimelineEvent,
    Recommendation,
    RecommendationClass,
)
from canopyledger.integrity.canonical import canonical_json_bytes
from canopyledger.persistence.schema import (
    approval_action,
    approval_request,
    decision_override,
    facility_snapshot,
    final_decision,
    internal_risk_capacity_assessment,
    pipeline_stage_output,
    recommendation,
)


class PostgresGovernanceService:
    """Loads immutable governance state, applies one command, and commits its delta atomically."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._clock = clock

    def execute(self, command: Callable[[GovernanceService], Any]) -> Any:
        with self._engine.begin() as connection:
            service = self._load(connection)
            original_decisions = dict(service._final_decisions)
            result = command(service)
            try:
                self._persist_new(connection, service, original_decisions)
            except DBAPIError as exc:
                raise GovernanceError(
                    "durable governance state conflicts with current decision"
                ) from exc
            return result

    def get_decision(self, resource_id: str) -> FinalDecision:
        with self._engine.connect() as connection:
            return self._load(connection).get_decision(resource_id)

    def get_recommendation(self, resource_id: str) -> Recommendation:
        with self._engine.connect() as connection:
            return self._load(connection).get_recommendation(resource_id)

    def get_approval_request(self, resource_id: str) -> ApprovalRequest:
        with self._engine.connect() as connection:
            return self._load(connection).get_approval_request(resource_id)

    def list_approval_requests(self) -> tuple[ApprovalRequest, ...]:
        with self._engine.connect() as connection:
            return self._load(connection).list_approval_requests()

    def list_overrides(self) -> tuple[DecisionOverride, ...]:
        with self._engine.connect() as connection:
            return self._load(connection).list_overrides()

    def list_timeline_events(self, snapshot_id: str) -> tuple[GovernanceTimelineEvent, ...]:
        with self._engine.connect() as connection:
            return self._load(connection).list_timeline_events(snapshot_id)

    def get_current_decision(self, snapshot_id: str) -> FinalDecision | None:
        with self._engine.connect() as connection:
            return self._load(connection).get_current_decision(snapshot_id)

    def get_current_recommendation(self, snapshot_id: str) -> Recommendation | None:
        with self._engine.connect() as connection:
            return self._load(connection).get_current_recommendation(snapshot_id)

    def get_override(self, resource_id: str) -> DecisionOverride:
        with self._engine.connect() as connection:
            return self._load(connection).get_override(resource_id)

    def assert_report_eligible(self, resource_id: str) -> FinalDecision:
        with self._engine.connect() as connection:
            return self._load(connection).assert_report_eligible(resource_id)

    def load_authoritative_context(self, snapshot_id: str) -> DecisionContext:
        """Build decision limits only from the approved snapshot and published stages."""
        with self._engine.connect() as connection:
            snapshot = (
                connection.execute(
                    select(facility_snapshot).where(facility_snapshot.c.resource_id == snapshot_id)
                )
                .mappings()
                .one_or_none()
            )
            outputs = (
                connection.execute(
                    select(pipeline_stage_output).where(
                        pipeline_stage_output.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .all()
            )
            irc = (
                connection.execute(
                    select(internal_risk_capacity_assessment).where(
                        internal_risk_capacity_assessment.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if snapshot is None:
            raise GovernanceError("approved snapshot not found")
        return decision_context_from_published(snapshot_id, snapshot, outputs, irc)

    def load_collateral_view(self, snapshot_id: str) -> dict[str, object] | None:
        """Return frozen collateral valuation and eligibility outputs for the analytical UI."""
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(pipeline_stage_output).where(
                        pipeline_stage_output.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .all()
            )
        outputs: dict[str, object] = {}
        wanted = {
            "collateral_valuation",
            "eligibility_and_reserves",
            "contractual_borrowing_base",
        }
        for row in rows:
            payload = json.loads(bytes(row["canonical_output"]))
            stage = payload.get("stage") if isinstance(payload, dict) else None
            if stage in wanted:
                payload["output_digest"] = str(row["output_digest"])
                outputs[str(stage)] = payload
        return outputs or None

    def _load(self, connection: Any) -> GovernanceService:
        service = GovernanceService(clock=self._clock)
        service._recommendations = {
            item.resource_id: item
            for item in (
                _recommendation_from_row(row)
                for row in connection.execute(select(recommendation)).mappings()
            )
        }
        service._approval_requests = {
            item.resource_id: item
            for item in (
                _request_from_row(row)
                for row in connection.execute(select(approval_request)).mappings()
            )
        }
        service._approval_actions = {
            item.resource_id: item
            for item in (
                _action_from_row(row)
                for row in connection.execute(select(approval_action)).mappings()
            )
        }
        service._final_decisions = {
            item.resource_id: item
            for item in (
                _decision_from_row(row)
                for row in connection.execute(select(final_decision)).mappings()
            )
        }
        service._overrides = {
            item.resource_id: item
            for item in (
                _override_from_row(row)
                for row in connection.execute(select(decision_override)).mappings()
            )
        }
        for override_id, override in tuple(service._overrides.items()):
            actions = tuple(
                action.resource_id
                for action in service._approval_actions.values()
                if action.override_id == override_id
            )
            service._overrides[override_id] = DecisionOverride(
                **{**override.__dict__, "approval_actions": actions}
            )
        return service

    def _persist_new(
        self,
        connection: Any,
        service: GovernanceService,
        original_decisions: dict[str, FinalDecision],
    ) -> None:
        for item in service._recommendations.values():
            _insert_immutable_row(
                connection,
                recommendation,
                {
                    "resource_id": item.resource_id,
                    "snapshot_id": item.snapshot_id,
                    "author_id": item.author_id,
                    "expires_at": item.expires_at,
                    "canonical_payload": canonical_json_bytes(item.canonical_payload()),
                    "digest": item.digest,
                    "created_at": item.created_at,
                },
            )
        for request in service._approval_requests.values():
            _insert_immutable_row(
                connection,
                approval_request,
                {
                    "resource_id": request.resource_id,
                    "recommendation_id": request.recommendation_id,
                    "requested_by": request.requested_by,
                    "expires_at": request.expires_at,
                    "canonical_payload": canonical_json_bytes(_request_payload(request)),
                    "digest": request.digest,
                    "created_at": request.created_at,
                },
            )
        for override in service._overrides.values():
            _insert_immutable_row(
                connection,
                decision_override,
                {
                    "resource_id": override.resource_id,
                    "original_decision_id": override.original_decision_id,
                    "recommendation_id": override.recommendation_id,
                    "requester_id": override.requester_id,
                    "expires_at": override.expires_at,
                    "requires_dual_control": int(override.requires_dual_control),
                    "canonical_payload": canonical_json_bytes(_override_payload(override)),
                    "digest": override.digest,
                    "created_at": override.created_at,
                },
            )
        for action in service._approval_actions.values():
            _insert_immutable_row(
                connection,
                approval_action,
                {
                    "resource_id": action.resource_id,
                    "approval_request_id": action.approval_request_id,
                    "override_id": action.override_id,
                    "actor_id": action.actor_id,
                    "action": action.action,
                    "reason": action.reason,
                    "canonical_payload": canonical_json_bytes(_action_payload(action)),
                    "digest": action.digest,
                    "occurred_at": action.occurred_at,
                },
            )
        for decision in service._final_decisions.values():
            previous = original_decisions.get(decision.resource_id)
            if previous is None:
                connection.execute(
                    insert(final_decision).values(
                        resource_id=decision.resource_id,
                        snapshot_id=decision.snapshot_id,
                        recommendation_id=decision.recommendation_id,
                        approval_request_id=decision.approval_request_id,
                        status=decision.status.value,
                        approver_id=decision.approver_id,
                        override_id=decision.override_id,
                        superseded_by=decision.superseded_by,
                        canonical_payload=canonical_json_bytes(_decision_payload(decision)),
                        digest=decision.digest,
                        approved_at=decision.approved_at,
                    )
                )
            elif previous.superseded_by != decision.superseded_by:
                connection.execute(
                    update(final_decision)
                    .where(final_decision.c.resource_id == decision.resource_id)
                    .values(superseded_by=decision.superseded_by)
                )


def _insert_immutable_row(connection: Any, table: Any, values: dict[str, Any]) -> None:
    """Insert an immutable row or prove that the exact same resource already exists."""
    inserted = connection.execute(
        postgres_insert(table).values(**values).on_conflict_do_nothing().returning(table.c.digest)
    ).scalar_one_or_none()
    if inserted is not None:
        return
    existing_digest = connection.execute(
        select(table.c.digest).where(table.c.resource_id == values["resource_id"])
    ).scalar_one_or_none()
    if existing_digest != values["digest"]:
        raise GovernanceError("immutable governance resource conflicts with existing content")


def _decode(row: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(bytes(row["canonical_payload"])))


def decision_context_from_published(
    snapshot_id: str,
    snapshot: Any,
    outputs: Any,
    irc_assessment: Any,
) -> DecisionContext:
    """Validate the policy-required publication chain and derive decision limits."""
    stage_outputs: dict[str, Any] = {}
    for row in outputs:
        decoded = json.loads(bytes(row["canonical_output"]))
        stage = decoded.get("stage") if isinstance(decoded, dict) else None
        if not isinstance(stage, str):
            continue
        if stage in stage_outputs:
            raise GovernanceError(f"multiple published {stage} outputs prevent a decision")
        stage_outputs[stage] = (row, decoded)
    required = ("contractual_borrowing_base", "hedge_liquidity", "scenario_capacity")
    missing = [stage for stage in required if stage not in stage_outputs]
    if missing:
        raise GovernanceError(
            "recommendation requires published stage outputs: " + ", ".join(missing)
        )
    if irc_assessment is None:
        raise GovernanceError("recommendation requires a published IRC assessment")
    cbb_row, cbb_payload = stage_outputs["contractual_borrowing_base"]
    hedge_row, hedge_payload = stage_outputs["hedge_liquidity"]
    scenario_row, _ = stage_outputs["scenario_capacity"]
    if (
        irc_assessment["scenario_stage_output_id"] != scenario_row["resource_id"]
        or irc_assessment["cbb_output_digest"] != cbb_row["output_digest"]
    ):
        raise GovernanceError("IRC assessment does not match the published decision lineage")
    try:
        cbb = cast(dict[str, Any], cbb_payload["result"])
        hedge_result = cast(dict[str, Any], hedge_payload["result"])
        liquidity = cast(
            dict[str, Any], cast(dict[str, Any], hedge_result["assessment"])["liquidity"]
        )
        currency = str(cbb["currency"])
        cbb_amount = Decimal(str(cbb["contractual_borrowing_base"]))
        facility_limit = Decimal(str(cbb["facility_limit"]))
        exposure = sum(
            (
                Decimal(str(cbb[field]))
                for field in ("current_principal", "lc_exposure", "other_contractual_usage")
            ),
            Decimal(0),
        )
        liquidity_cap = Decimal(str(liquidity["total_liquidity_available"]))
        irc = Decimal(str(irc_assessment["irc"]))
        irc_currency = str(irc_assessment["currency"])
        policy_bundle_digest = str(snapshot["policy_bundle_digest"])
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise GovernanceError("published decision-stage output is malformed") from exc
    if irc_currency != currency:
        raise GovernanceError("IRC assessment currency differs from the CBB output")
    return DecisionContext(
        snapshot_id=snapshot_id,
        cbb=Money(cbb_amount, currency),
        contractual_availability=Money(Decimal(str(cbb["contractual_availability"])), currency),
        internal_risk_capacity=Money(irc, currency),
        liquidity_cap=Money(liquidity_cap, currency),
        facility_commitment=Money(facility_limit, currency),
        policy_caps=(),
        outstanding_exposure=Money(exposure, currency),
        approved_unfunded_exposure=Money(Decimal(0), currency),
        cbb_output_digest=str(cbb_row["output_digest"]),
        hedge_liquidity_output_digest=str(hedge_row["output_digest"]),
        irc_output_digest=str(scenario_row["output_digest"]),
        policy_bundle_digest=policy_bundle_digest,
    )


def _money(value: dict[str, str]) -> Money:
    return Money(Decimal(value["amount"]), value["currency"])


def _recommendation_from_row(row: Any) -> Recommendation:
    value = _decode(row)
    return Recommendation(
        resource_id=str(row["resource_id"]),
        snapshot_id=value["snapshot_id"],
        author_id=value["author_id"],
        requested_amount=_money(value["requested_amount"]),
        contractual_availability=_money(value["contractual_availability"]),
        internal_risk_capacity=_money(value["internal_risk_capacity"]),
        recommended_exposure_cap=_money(value["recommended_exposure_cap"]),
        recommended_incremental_draw=_money(value["recommended_incremental_draw"]),
        compared_limits=dict(value["compared_limits"]),
        binding_constraint=value["binding_constraint"],
        recommendation_class=RecommendationClass(value["recommendation_class"]),
        conditions=tuple(value["conditions"]),
        reason_codes=tuple(value["reason_codes"]),
        output_digests=tuple(value["output_digests"]),
        policy_bundle_digest=value["policy_bundle_digest"],
        expires_at=datetime.fromisoformat(value["expires_at"]),
        created_at=datetime.fromisoformat(value["created_at"]),
        digest=str(row["digest"]),
    )


def _request_from_row(row: Any) -> ApprovalRequest:
    value = _decode(row)
    return ApprovalRequest(
        str(row["resource_id"]),
        value["recommendation_id"],
        value["requested_by"],
        datetime.fromisoformat(value["expires_at"]),
        datetime.fromisoformat(value["created_at"]),
        str(row["digest"]),
    )


def _action_from_row(row: Any) -> ApprovalAction:
    value = _decode(row)
    return ApprovalAction(
        str(row["resource_id"]),
        value["approval_request_id"],
        value["override_id"],
        value["actor_id"],
        value["action"],
        value["reason"],
        datetime.fromisoformat(value["occurred_at"]),
        str(row["digest"]),
    )


def _decision_from_row(row: Any) -> FinalDecision:
    value = _decode(row)
    return FinalDecision(
        str(row["resource_id"]),
        value["snapshot_id"],
        value["recommendation_id"],
        value["approval_request_id"],
        FinalDecisionStatus(value["status"]),
        value["approver_id"],
        value["reason"],
        datetime.fromisoformat(value["approved_at"]),
        value["override_id"],
        row["superseded_by"],
        str(row["digest"]),
    )


def _override_from_row(row: Any) -> DecisionOverride:
    value = _decode(row)
    return DecisionOverride(
        str(row["resource_id"]),
        value["original_decision_id"],
        value["recommendation_id"],
        value["requester_id"],
        _money(value["proposed_exposure_cap"]),
        value["reason"],
        value["policy_basis"],
        datetime.fromisoformat(value["expires_at"]),
        bool(value["requires_dual_control"]),
        (),
        datetime.fromisoformat(value["created_at"]),
        str(row["digest"]),
    )


def _request_payload(value: ApprovalRequest) -> dict[str, str]:
    return {
        "resource_id": value.resource_id,
        "recommendation_id": value.recommendation_id,
        "requested_by": value.requested_by,
        "expires_at": value.expires_at.isoformat(),
        "created_at": value.created_at.isoformat(),
    }


def _action_payload(value: ApprovalAction) -> dict[str, str | None]:
    return {
        "resource_id": value.resource_id,
        "approval_request_id": value.approval_request_id,
        "override_id": value.override_id,
        "actor_id": value.actor_id,
        "action": value.action,
        "reason": value.reason,
        "occurred_at": value.occurred_at.isoformat(),
    }


def _decision_payload(value: FinalDecision) -> dict[str, str | None]:
    return {
        "resource_id": value.resource_id,
        "snapshot_id": value.snapshot_id,
        "recommendation_id": value.recommendation_id,
        "approval_request_id": value.approval_request_id,
        "status": value.status.value,
        "approver_id": value.approver_id,
        "reason": value.reason,
        "approved_at": value.approved_at.isoformat(),
        "override_id": value.override_id,
        "superseded_by": value.superseded_by,
    }


def _override_payload(value: DecisionOverride) -> dict[str, Any]:
    return {
        "resource_id": value.resource_id,
        "original_decision_id": value.original_decision_id,
        "recommendation_id": value.recommendation_id,
        "requester_id": value.requester_id,
        "proposed_exposure_cap": {
            "amount": f"{value.proposed_exposure_cap.amount:.2f}",
            "currency": value.proposed_exposure_cap.currency,
        },
        "reason": value.reason,
        "policy_basis": value.policy_basis,
        "expires_at": value.expires_at.isoformat(),
        "requires_dual_control": value.requires_dual_control,
        "created_at": value.created_at.isoformat(),
    }
