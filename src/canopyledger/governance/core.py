"""Pure M4B decision governance with immutable recommendation lineage."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


class GovernanceError(ValueError):
    """Base error for governed-decision contract failures."""


class ApprovalDenied(GovernanceError):
    """Raised when separation of duties or authority rules reject an action."""


class ApprovalRequestExpired(GovernanceError):
    """Raised when an approval or override request has expired."""


class SupersededDecision(GovernanceError):
    """Raised when an obsolete final decision is used as current."""


class ReportIneligible(GovernanceError):
    """Raised unless a current approved final decision can support reporting."""


class RecommendationClass(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    REDUCE_REQUESTED_DRAW = "REDUCE_REQUESTED_DRAW"
    REQUIRE_ADDITIONAL_COLLATERAL = "REQUIRE_ADDITIONAL_COLLATERAL"
    REQUIRE_HEDGE_ADJUSTMENT = "REQUIRE_HEDGE_ADJUSTMENT"
    REQUIRE_LIQUIDITY_BUFFER = "REQUIRE_LIQUIDITY_BUFFER"
    INCREASE_MONITORING = "INCREASE_MONITORING"
    DEFER_PENDING_EVIDENCE = "DEFER_PENDING_EVIDENCE"
    DECLINE = "DECLINE"


class FinalDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class DecisionContext:
    snapshot_id: str
    cbb: Money
    contractual_availability: Money
    internal_risk_capacity: Money
    liquidity_cap: Money
    facility_commitment: Money
    policy_caps: tuple[Money, ...]
    outstanding_exposure: Money
    approved_unfunded_exposure: Money
    cbb_output_digest: str
    hedge_liquidity_output_digest: str
    irc_output_digest: str
    policy_bundle_digest: str

    def __post_init__(self) -> None:
        amounts = (
            self.cbb,
            self.contractual_availability,
            self.internal_risk_capacity,
            self.liquidity_cap,
            self.facility_commitment,
            self.outstanding_exposure,
            self.approved_unfunded_exposure,
            *self.policy_caps,
        )
        if not self.snapshot_id or not all(item.amount >= 0 for item in amounts):
            raise GovernanceError("decision context requires snapshot and non-negative amounts")
        if len({item.currency for item in amounts}) != 1:
            raise GovernanceError("decision context amounts must use one currency")
        if self.internal_risk_capacity.amount > self.cbb.amount:
            raise GovernanceError("internal risk capacity cannot exceed CBB")
        if self.contractual_availability.amount > min(
            self.cbb.amount, self.facility_commitment.amount
        ):
            raise GovernanceError("contractual availability cannot exceed contractual capacity")
        if not all(_SHA256_DIGEST.fullmatch(item) for item in self.output_digests):
            raise GovernanceError("decision context lineage must use SHA-256 digests")

    @property
    def currency(self) -> str:
        return self.cbb.currency

    @property
    def output_digests(self) -> tuple[str, str, str, str]:
        return (
            self.cbb_output_digest,
            self.hedge_liquidity_output_digest,
            self.irc_output_digest,
            self.policy_bundle_digest,
        )


@dataclass(frozen=True)
class Recommendation:
    resource_id: str
    snapshot_id: str
    author_id: str
    requested_amount: Money
    contractual_availability: Money
    internal_risk_capacity: Money
    recommended_exposure_cap: Money
    recommended_incremental_draw: Money
    compared_limits: dict[str, str]
    binding_constraint: str
    recommendation_class: RecommendationClass
    conditions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    output_digests: tuple[str, ...]
    policy_bundle_digest: str
    expires_at: datetime
    created_at: datetime
    digest: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "snapshot_id": self.snapshot_id,
            "author_id": self.author_id,
            "requested_amount": _money(self.requested_amount),
            "contractual_availability": _money(self.contractual_availability),
            "internal_risk_capacity": _money(self.internal_risk_capacity),
            "recommended_exposure_cap": _money(self.recommended_exposure_cap),
            "recommended_incremental_draw": _money(self.recommended_incremental_draw),
            "compared_limits": self.compared_limits,
            "binding_constraint": self.binding_constraint,
            "recommendation_class": self.recommendation_class.value,
            "conditions": list(self.conditions),
            "reason_codes": list(self.reason_codes),
            "output_digests": list(self.output_digests),
            "policy_bundle_digest": self.policy_bundle_digest,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ApprovalRequest:
    resource_id: str
    recommendation_id: str
    requested_by: str
    expires_at: datetime
    created_at: datetime
    digest: str


@dataclass(frozen=True)
class ApprovalAction:
    resource_id: str
    approval_request_id: str | None
    override_id: str | None
    actor_id: str
    action: str
    reason: str
    occurred_at: datetime
    digest: str


@dataclass(frozen=True)
class FinalDecision:
    resource_id: str
    snapshot_id: str
    recommendation_id: str
    approval_request_id: str | None
    status: FinalDecisionStatus
    approver_id: str
    reason: str
    approved_at: datetime
    override_id: str | None
    superseded_by: str | None
    digest: str


@dataclass(frozen=True)
class DecisionOverride:
    resource_id: str
    original_decision_id: str
    recommendation_id: str
    requester_id: str
    proposed_exposure_cap: Money
    reason: str
    policy_basis: str
    expires_at: datetime
    requires_dual_control: bool
    approval_actions: tuple[str, ...]
    created_at: datetime
    digest: str


@dataclass(frozen=True)
class GovernanceTimelineEvent:
    """A read-only, snapshot-scoped event derived from immutable governance records."""

    resource_id: str
    resource_type: str
    action: str
    actor_id: str
    occurred_at: datetime
    digest: str
    reason: str | None = None
    status: str | None = None


class GovernanceService:
    """In-memory authoritative M4B behavior; persistence adapters mirror this contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self._recommendations: dict[str, Recommendation] = {}
        self._approval_requests: dict[str, ApprovalRequest] = {}
        self._approval_actions: dict[str, ApprovalAction] = {}
        self._final_decisions: dict[str, FinalDecision] = {}
        self._overrides: dict[str, DecisionOverride] = {}

    def create_recommendation(
        self,
        *,
        context: DecisionContext,
        recommendation_id: str,
        author_id: str,
        requested_amount: Money,
        recommendation_class: RecommendationClass,
        conditions: tuple[str, ...],
        reason_codes: tuple[str, ...],
        expires_at: datetime,
    ) -> Recommendation:
        now = self._clock()
        _validate_expiry(expires_at, now)
        if requested_amount.currency != context.currency or requested_amount.amount < 0:
            raise GovernanceError("requested amount must be non-negative in facility currency")
        limits = {
            "facility_commitment": context.facility_commitment,
            "contractual_borrowing_base": context.cbb,
            "internal_risk_capacity": context.internal_risk_capacity,
            "liquidity_cap": context.liquidity_cap,
            **{f"policy_cap_{index + 1}": value for index, value in enumerate(context.policy_caps)},
        }
        binding_key, cap = min(limits.items(), key=lambda item: (item[1].amount, item[0]))
        exposure_headroom = Money(
            max(
                Decimal(0),
                cap.amount
                - context.outstanding_exposure.amount
                - context.approved_unfunded_exposure.amount,
            ),
            context.currency,
        )
        incremental_key, incremental = min(
            {
                "requested_amount": requested_amount,
                "exposure_headroom": exposure_headroom,
                "contractual_availability": context.contractual_availability,
            }.items(),
            key=lambda item: (item[1].amount, item[0]),
        )
        draft = Recommendation(
            resource_id=recommendation_id,
            snapshot_id=context.snapshot_id,
            author_id=author_id,
            requested_amount=requested_amount.quantized(),
            contractual_availability=context.contractual_availability.quantized(),
            internal_risk_capacity=context.internal_risk_capacity.quantized(),
            recommended_exposure_cap=cap.quantized(),
            recommended_incremental_draw=incremental.quantized(),
            compared_limits={
                **{key: _amount(value) for key, value in limits.items()},
                "contractual_availability": _amount(context.contractual_availability),
                "exposure_headroom": _amount(exposure_headroom),
            },
            binding_constraint=(
                binding_key.upper()
                if incremental_key == "exposure_headroom"
                else incremental_key.upper()
            ),
            recommendation_class=recommendation_class,
            conditions=conditions,
            reason_codes=reason_codes,
            output_digests=context.output_digests[:-1],
            policy_bundle_digest=context.policy_bundle_digest,
            expires_at=expires_at,
            created_at=now,
            digest="",
        )
        recommendation = replace(
            draft,
            digest=domain_digest(
                "recommendation", 1, canonical_json_bytes(draft.canonical_payload())
            ),
        )
        self._insert_immutable(self._recommendations, recommendation.resource_id, recommendation)
        return recommendation

    def create_approval_request(
        self,
        *,
        approval_request_id: str,
        recommendation_id: str,
        requested_by: str,
        expires_at: datetime,
    ) -> ApprovalRequest:
        recommendation = self.get_recommendation(recommendation_id)
        now = self._clock()
        _validate_expiry(expires_at, now)
        if recommendation.expires_at <= now:
            raise ApprovalRequestExpired("recommendation has expired")
        draft = ApprovalRequest(
            approval_request_id, recommendation_id, requested_by, expires_at, now, ""
        )
        result = replace(
            draft,
            digest=domain_digest(
                "approval_request", 1, canonical_json_bytes(_approval_request_payload(draft))
            ),
        )
        self._insert_immutable(self._approval_requests, result.resource_id, result)
        return result

    def approve(
        self,
        *,
        approval_action_id: str,
        final_decision_id: str,
        approval_request_id: str,
        approver_id: str,
        reason: str,
    ) -> FinalDecision:
        request = self._current_request(approval_request_id)
        recommendation = self.get_recommendation(request.recommendation_id)
        self._assert_recommendation_current(recommendation)
        if approver_id == recommendation.author_id or approver_id == request.requested_by:
            raise ApprovalDenied("self-approval is prohibited")
        self._record_approval_action(
            approval_action_id,
            approval_request_id=request.resource_id,
            override_id=None,
            actor_id=approver_id,
            action="APPROVE",
            reason=reason,
        )
        return self._create_final_decision(
            final_decision_id,
            recommendation,
            request.resource_id,
            FinalDecisionStatus.APPROVED,
            approver_id,
            reason,
            None,
        )

    def reject(
        self,
        *,
        approval_action_id: str,
        final_decision_id: str,
        approval_request_id: str,
        approver_id: str,
        reason: str,
    ) -> FinalDecision:
        request = self._current_request(approval_request_id)
        recommendation = self.get_recommendation(request.recommendation_id)
        self._assert_recommendation_current(recommendation)
        if approver_id == recommendation.author_id or approver_id == request.requested_by:
            raise ApprovalDenied("self-approval is prohibited")
        self._record_approval_action(
            approval_action_id,
            approval_request_id=request.resource_id,
            override_id=None,
            actor_id=approver_id,
            action="REJECT",
            reason=reason,
        )
        return self._create_final_decision(
            final_decision_id,
            recommendation,
            request.resource_id,
            FinalDecisionStatus.REJECTED,
            approver_id,
            reason,
            None,
        )

    def create_override_request(
        self,
        *,
        override_id: str,
        original_decision_id: str,
        requester_id: str,
        proposed_exposure_cap: Money,
        reason: str,
        policy_basis: str,
        expires_at: datetime,
        requires_dual_control: bool,
    ) -> DecisionOverride:
        original = self.get_decision(original_decision_id)
        if original.superseded_by is not None:
            raise SupersededDecision("superseded decision cannot be overridden")
        now = self._clock()
        _validate_expiry(expires_at, now)
        if original.status is FinalDecisionStatus.REJECTED and not requires_dual_control:
            raise ApprovalDenied("reinstating a rejected decision requires dual control")
        recommendation = self.get_recommendation(original.recommendation_id)
        if proposed_exposure_cap.currency != recommendation.requested_amount.currency:
            raise GovernanceError("override cap currency must match recommendation")
        draft = DecisionOverride(
            override_id,
            original_decision_id,
            recommendation.resource_id,
            requester_id,
            proposed_exposure_cap.quantized(),
            reason,
            policy_basis,
            expires_at,
            requires_dual_control,
            (),
            now,
            "",
        )
        result = replace(
            draft,
            digest=domain_digest(
                "decision_override", 1, canonical_json_bytes(_override_payload(draft))
            ),
        )
        self._insert_immutable(self._overrides, result.resource_id, result)
        return result

    def approve_override(
        self, override_id: str, approver_id: str, reason: str, *, approval_action_id: str
    ) -> FinalDecision | None:
        override = self._overrides.get(override_id)
        if override is None:
            raise GovernanceError("override request not found")
        now = self._clock()
        if override.expires_at <= now:
            raise ApprovalRequestExpired("override request has expired")
        if approver_id == override.requester_id:
            raise ApprovalDenied("override requester cannot approve")
        prior_actors = tuple(
            self._approval_actions[action_id].actor_id for action_id in override.approval_actions
        )
        if approver_id in prior_actors:
            raise ApprovalDenied("dual-control approvers must be distinct")
        action = self._record_approval_action(
            approval_action_id,
            approval_request_id=None,
            override_id=override.resource_id,
            actor_id=approver_id,
            action="OVERRIDE_APPROVE",
            reason=reason,
        )
        updated = replace(
            override, approval_actions=(*override.approval_actions, action.resource_id)
        )
        self._overrides[override_id] = updated
        required = 2 if override.requires_dual_control else 1
        if len(updated.approval_actions) < required:
            return None
        original = self.get_decision(updated.original_decision_id)
        if original.superseded_by is not None:
            raise SupersededDecision("superseded decision cannot be overridden")
        recommendation = self.get_recommendation(updated.recommendation_id)
        self._final_decisions[original.resource_id] = replace(
            original, superseded_by=self._id_factory("fdc")
        )
        replacement_id = self._final_decisions[original.resource_id].superseded_by
        assert replacement_id is not None
        replacement = self._create_final_decision(
            replacement_id,
            recommendation,
            None,
            FinalDecisionStatus.APPROVED,
            approver_id,
            updated.reason,
            updated.resource_id,
        )
        return replacement

    def get_recommendation(self, resource_id: str) -> Recommendation:
        try:
            return self._recommendations[resource_id]
        except KeyError as exc:
            raise GovernanceError("recommendation not found") from exc

    def get_approval_request(self, resource_id: str) -> ApprovalRequest:
        try:
            return self._approval_requests[resource_id]
        except KeyError as exc:
            raise GovernanceError("approval request not found") from exc

    def list_approval_requests(self) -> tuple[ApprovalRequest, ...]:
        return tuple(
            sorted(
                self._approval_requests.values(),
                key=lambda request: (request.expires_at, request.resource_id),
            )
        )

    def list_overrides(self) -> tuple[DecisionOverride, ...]:
        return tuple(
            sorted(
                self._overrides.values(),
                key=lambda override: (override.expires_at, override.resource_id),
            )
        )

    def list_timeline_events(self, snapshot_id: str) -> tuple[GovernanceTimelineEvent, ...]:
        """Project governance history without mutating or reconstructing decisions in the UI."""
        recommendations = {
            item.resource_id: item
            for item in self._recommendations.values()
            if item.snapshot_id == snapshot_id
        }
        recommendation_ids = set(recommendations)
        requests = {
            item.resource_id: item
            for item in self._approval_requests.values()
            if item.recommendation_id in recommendation_ids
        }
        overrides = {
            item.resource_id: item
            for item in self._overrides.values()
            if item.recommendation_id in recommendation_ids
        }
        events: list[GovernanceTimelineEvent] = [
            GovernanceTimelineEvent(
                resource_id=item.resource_id,
                resource_type="recommendation",
                action="recommendation.created",
                actor_id=item.author_id,
                occurred_at=item.created_at,
                digest=item.digest,
                status=item.recommendation_class.value,
            )
            for item in recommendations.values()
        ]
        events.extend(
            GovernanceTimelineEvent(
                resource_id=item.resource_id,
                resource_type="approval_request",
                action="approval_request.created",
                actor_id=item.requested_by,
                occurred_at=item.created_at,
                digest=item.digest,
            )
            for item in requests.values()
        )
        events.extend(
            GovernanceTimelineEvent(
                resource_id=item.resource_id,
                resource_type="decision_override",
                action="override.requested",
                actor_id=item.requester_id,
                occurred_at=item.created_at,
                digest=item.digest,
                reason=item.reason,
            )
            for item in overrides.values()
        )
        events.extend(
            GovernanceTimelineEvent(
                resource_id=item.resource_id,
                resource_type="approval_action",
                action=(
                    f"approval.{item.action.lower()}"
                    if item.approval_request_id in requests
                    else f"override.{item.action.lower()}"
                ),
                actor_id=item.actor_id,
                occurred_at=item.occurred_at,
                digest=item.digest,
                reason=item.reason,
            )
            for item in self._approval_actions.values()
            if item.approval_request_id in requests or item.override_id in overrides
        )
        events.extend(
            GovernanceTimelineEvent(
                resource_id=item.resource_id,
                resource_type="final_decision",
                action=f"final_decision.{item.status.value.lower()}",
                actor_id=item.approver_id,
                occurred_at=item.approved_at,
                digest=item.digest,
                reason=item.reason,
                status=("SUPERSEDED" if item.superseded_by is not None else item.status.value),
            )
            for item in self._final_decisions.values()
            if item.snapshot_id == snapshot_id and item.recommendation_id in recommendation_ids
        )
        return tuple(
            sorted(
                events,
                key=lambda item: (
                    item.occurred_at,
                    {
                        "recommendation.created": 0,
                        "approval_request.created": 1,
                        "override.requested": 2,
                        "approval.approve": 3,
                        "approval.reject": 3,
                        "override.override_approve": 3,
                        "final_decision.approved": 4,
                        "final_decision.rejected": 4,
                    }.get(item.action, 99),
                    item.resource_id,
                ),
            )
        )

    def get_decision(self, resource_id: str) -> FinalDecision:
        try:
            return self._final_decisions[resource_id]
        except KeyError as exc:
            raise GovernanceError("final decision not found") from exc

    def get_current_decision(self, snapshot_id: str) -> FinalDecision | None:
        current = [
            decision
            for decision in self._final_decisions.values()
            if decision.snapshot_id == snapshot_id and decision.superseded_by is None
        ]
        if len(current) > 1:
            raise GovernanceError("snapshot has multiple current final decisions")
        return current[0] if current else None

    def get_current_recommendation(self, snapshot_id: str) -> Recommendation | None:
        """Return current decision's recommendation or latest unexpired pending recommendation."""
        decision = self.get_current_decision(snapshot_id)
        if decision is not None:
            return self.get_recommendation(decision.recommendation_id)
        candidates = [
            recommendation
            for recommendation in self._recommendations.values()
            if recommendation.snapshot_id == snapshot_id
            and recommendation.expires_at > self._clock()
        ]
        return max(candidates, key=lambda item: (item.created_at, item.resource_id), default=None)

    def get_override(self, resource_id: str) -> DecisionOverride:
        try:
            return self._overrides[resource_id]
        except KeyError as exc:
            raise GovernanceError("decision override not found") from exc

    def assert_report_eligible(self, decision_id: str) -> FinalDecision:
        decision = self.get_decision(decision_id)
        if decision.superseded_by is not None:
            raise SupersededDecision("superseded decision is report-ineligible")
        if decision.status is not FinalDecisionStatus.APPROVED:
            raise ReportIneligible("only current approved decisions are report-eligible")
        return decision

    def _current_request(self, resource_id: str) -> ApprovalRequest:
        try:
            request = self._approval_requests[resource_id]
        except KeyError as exc:
            raise GovernanceError("approval request not found") from exc
        now = self._clock()
        if request.expires_at <= now:
            raise ApprovalRequestExpired("approval request has expired")
        if any(
            action.approval_request_id == resource_id for action in self._approval_actions.values()
        ) or any(
            decision.approval_request_id == resource_id
            for decision in self._final_decisions.values()
        ):
            raise GovernanceError("approval request has already been decided")
        return request

    def _assert_recommendation_current(self, recommendation: Recommendation) -> None:
        if recommendation.expires_at <= self._clock():
            raise ApprovalRequestExpired("recommendation has expired")

    def _record_approval_action(
        self,
        resource_id: str,
        *,
        approval_request_id: str | None,
        override_id: str | None,
        actor_id: str,
        action: str,
        reason: str,
    ) -> ApprovalAction:
        if not reason:
            raise GovernanceError("approval reason is required")
        if (approval_request_id is None) == (override_id is None):
            raise GovernanceError("approval action requires exactly one governance target")
        draft = ApprovalAction(
            resource_id,
            approval_request_id,
            override_id,
            actor_id,
            action,
            reason,
            self._clock(),
            "",
        )
        result = replace(
            draft,
            digest=domain_digest(
                "approval_action", 1, canonical_json_bytes(_approval_action_payload(draft))
            ),
        )
        self._insert_immutable(self._approval_actions, result.resource_id, result)
        return result

    def _create_final_decision(
        self,
        resource_id: str,
        recommendation: Recommendation,
        approval_request_id: str | None,
        status: FinalDecisionStatus,
        approver_id: str,
        reason: str,
        override_id: str | None,
    ) -> FinalDecision:
        if any(
            decision.snapshot_id == recommendation.snapshot_id and decision.superseded_by is None
            for decision in self._final_decisions.values()
        ):
            raise SupersededDecision("snapshot already has a current final decision")
        draft = FinalDecision(
            resource_id,
            recommendation.snapshot_id,
            recommendation.resource_id,
            approval_request_id,
            status,
            approver_id,
            reason,
            self._clock(),
            override_id,
            None,
            "",
        )
        decision = replace(
            draft,
            digest=domain_digest(
                "final_decision", 1, canonical_json_bytes(_final_decision_payload(draft))
            ),
        )
        self._insert_immutable(self._final_decisions, decision.resource_id, decision)
        return decision

    @staticmethod
    def _insert_immutable(values: dict[str, Any], resource_id: str, value: Any) -> None:
        existing = values.get(resource_id)
        if existing is not None and existing != value:
            raise GovernanceError("immutable resource ID already has different content")
        values[resource_id] = value


def _validate_expiry(expires_at: datetime, now: datetime) -> None:
    if expires_at.tzinfo is None or expires_at <= now:
        raise ApprovalRequestExpired("expiry must be in the future")


_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _amount(value: Money) -> str:
    return f"{value.quantized().amount:.2f}"


def _money(value: Money) -> dict[str, str]:
    return {"amount": _amount(value), "currency": value.currency}


def _approval_request_payload(value: ApprovalRequest) -> dict[str, str]:
    return {
        "resource_id": value.resource_id,
        "recommendation_id": value.recommendation_id,
        "requested_by": value.requested_by,
        "expires_at": value.expires_at.isoformat(),
        "created_at": value.created_at.isoformat(),
    }


def _approval_action_payload(value: ApprovalAction) -> dict[str, str | None]:
    return {
        "resource_id": value.resource_id,
        "approval_request_id": value.approval_request_id,
        "override_id": value.override_id,
        "actor_id": value.actor_id,
        "action": value.action,
        "reason": value.reason,
        "occurred_at": value.occurred_at.isoformat(),
    }


def _final_decision_payload(value: FinalDecision) -> dict[str, str | None]:
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
        "proposed_exposure_cap": _money(value.proposed_exposure_cap),
        "reason": value.reason,
        "policy_basis": value.policy_basis,
        "expires_at": value.expires_at.isoformat(),
        "requires_dual_control": value.requires_dual_control,
        "created_at": value.created_at.isoformat(),
    }
