"""Normative decision-cycle states and transitions."""

from enum import StrEnum


class DecisionCycleState(StrEnum):
    """Materialized states in one governed facility decision cycle."""

    DRAFT = "DRAFT"
    FREEZING = "FREEZING"
    FROZEN = "FROZEN"
    CALCULATING = "CALCULATING"
    RECOMMENDATION_READY = "RECOMMENDATION_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REPORTED = "REPORTED"
    FREEZE_REJECTED = "FREEZE_REJECTED"
    CALCULATION_FAILED = "CALCULATION_FAILED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DecisionCycleEvent(StrEnum):
    """Explicit domain events that may advance a decision cycle."""

    FREEZE_REQUESTED = "FREEZE_REQUESTED"
    FREEZE_ACCEPTED = "FREEZE_ACCEPTED"
    FREEZE_REJECTED = "FREEZE_REJECTED"
    PIPELINE_STARTED = "PIPELINE_STARTED"
    REQUIRED_STAGES_PUBLISHED = "REQUIRED_STAGES_PUBLISHED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PACKAGE_RENDERED = "PACKAGE_RENDERED"
    SUPERSEDED = "SUPERSEDED"


class InvalidStateTransition(ValueError):
    """Raised when an event is not permitted from the current state."""

    code = "INVALID_STATE_TRANSITION"

    def __init__(self, current: DecisionCycleState, event: DecisionCycleEvent) -> None:
        self.current = current
        self.event = event
        super().__init__(f"{event.value} is not permitted from {current.value}")


_TRANSITIONS: dict[tuple[DecisionCycleState, DecisionCycleEvent], DecisionCycleState] = {
    (DecisionCycleState.DRAFT, DecisionCycleEvent.FREEZE_REQUESTED): DecisionCycleState.FREEZING,
    (DecisionCycleState.FREEZING, DecisionCycleEvent.FREEZE_ACCEPTED): DecisionCycleState.FROZEN,
    (
        DecisionCycleState.FREEZING,
        DecisionCycleEvent.FREEZE_REJECTED,
    ): DecisionCycleState.FREEZE_REJECTED,
    (
        DecisionCycleState.FROZEN,
        DecisionCycleEvent.PIPELINE_STARTED,
    ): DecisionCycleState.CALCULATING,
    (
        DecisionCycleState.CALCULATING,
        DecisionCycleEvent.REQUIRED_STAGES_PUBLISHED,
    ): DecisionCycleState.RECOMMENDATION_READY,
    (
        DecisionCycleState.RECOMMENDATION_READY,
        DecisionCycleEvent.APPROVAL_REQUESTED,
    ): DecisionCycleState.AWAITING_APPROVAL,
    (
        DecisionCycleState.AWAITING_APPROVAL,
        DecisionCycleEvent.APPROVED,
    ): DecisionCycleState.APPROVED,
    (
        DecisionCycleState.AWAITING_APPROVAL,
        DecisionCycleEvent.REJECTED,
    ): DecisionCycleState.REJECTED,
    (DecisionCycleState.APPROVED, DecisionCycleEvent.PACKAGE_RENDERED): DecisionCycleState.REPORTED,
    (DecisionCycleState.APPROVED, DecisionCycleEvent.SUPERSEDED): DecisionCycleState.SUPERSEDED,
    (DecisionCycleState.REPORTED, DecisionCycleEvent.SUPERSEDED): DecisionCycleState.SUPERSEDED,
}


def transition(current: DecisionCycleState, event: DecisionCycleEvent) -> DecisionCycleState:
    """Return the next state for an explicitly permitted event."""
    if not isinstance(current, DecisionCycleState) or not isinstance(event, DecisionCycleEvent):
        raise TypeError("current and event must be decision-cycle enum values")
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise InvalidStateTransition(current, event) from exc
