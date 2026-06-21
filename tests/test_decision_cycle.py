"""Executable coverage for the normative decision-cycle state machine."""

import pytest

from canopyledger.domain import (
    DecisionCycleEvent,
    DecisionCycleState,
    InvalidStateTransition,
    transition,
)

NORMATIVE_TRANSITIONS = (
    (DecisionCycleState.DRAFT, DecisionCycleEvent.FREEZE_REQUESTED, DecisionCycleState.FREEZING),
    (DecisionCycleState.FREEZING, DecisionCycleEvent.FREEZE_ACCEPTED, DecisionCycleState.FROZEN),
    (
        DecisionCycleState.FREEZING,
        DecisionCycleEvent.FREEZE_REJECTED,
        DecisionCycleState.FREEZE_REJECTED,
    ),
    (
        DecisionCycleState.FROZEN,
        DecisionCycleEvent.PIPELINE_STARTED,
        DecisionCycleState.CALCULATING,
    ),
    (
        DecisionCycleState.CALCULATING,
        DecisionCycleEvent.REQUIRED_STAGES_PUBLISHED,
        DecisionCycleState.RECOMMENDATION_READY,
    ),
    (
        DecisionCycleState.RECOMMENDATION_READY,
        DecisionCycleEvent.APPROVAL_REQUESTED,
        DecisionCycleState.AWAITING_APPROVAL,
    ),
    (
        DecisionCycleState.AWAITING_APPROVAL,
        DecisionCycleEvent.APPROVED,
        DecisionCycleState.APPROVED,
    ),
    (
        DecisionCycleState.AWAITING_APPROVAL,
        DecisionCycleEvent.REJECTED,
        DecisionCycleState.REJECTED,
    ),
    (
        DecisionCycleState.APPROVED,
        DecisionCycleEvent.PACKAGE_RENDERED,
        DecisionCycleState.REPORTED,
    ),
    (
        DecisionCycleState.APPROVED,
        DecisionCycleEvent.SUPERSEDED,
        DecisionCycleState.SUPERSEDED,
    ),
    (
        DecisionCycleState.REPORTED,
        DecisionCycleEvent.SUPERSEDED,
        DecisionCycleState.SUPERSEDED,
    ),
)


@pytest.mark.parametrize(("current", "event", "expected"), NORMATIVE_TRANSITIONS)
def test_normative_transition(
    current: DecisionCycleState,
    event: DecisionCycleEvent,
    expected: DecisionCycleState,
) -> None:
    assert transition(current, event) is expected


def test_every_unlisted_transition_is_rejected() -> None:
    allowed = {(current, event) for current, event, _ in NORMATIVE_TRANSITIONS}

    for current in DecisionCycleState:
        for event in DecisionCycleEvent:
            if (current, event) in allowed:
                continue
            with pytest.raises(InvalidStateTransition) as caught:
                transition(current, event)
            assert caught.value.code == "INVALID_STATE_TRANSITION"
            assert caught.value.current is current
            assert caught.value.event is event


def test_transition_requires_explicit_event_not_a_timestamp() -> None:
    with pytest.raises(TypeError):
        transition(DecisionCycleState.AWAITING_APPROVAL, "2026-06-21T12:00:00Z")  # type: ignore[arg-type]
