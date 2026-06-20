"""Pure stage leasing and publication fencing contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


class PipelineError(ValueError):
    """Base pipeline contract error."""


class ClaimConflict(PipelineError):
    """Raised when a stage cannot be leased."""


class FencedPublication(PipelineError):
    """Raised when an attempt lacks authority to publish."""


class StageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


@dataclass(frozen=True)
class PipelineStage:
    stage_definition_id: str
    status: StageStatus
    lease_epoch: int
    worker_id: str | None
    lease_expires_at: datetime | None
    output_digest: str | None

    @classmethod
    def pending(cls, stage_definition_id: str) -> PipelineStage:
        if not stage_definition_id:
            raise PipelineError("stage definition ID cannot be empty")
        return cls(stage_definition_id, StageStatus.PENDING, 0, None, None, None)


def claim_stage(
    stage: PipelineStage,
    *,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
) -> PipelineStage:
    """Atomically model a queue claim or expired-lease reassignment."""
    _require_aware(now)
    if not worker_id:
        raise PipelineError("worker ID cannot be empty")
    if lease_duration <= timedelta(0):
        raise PipelineError("lease duration must be positive")
    if stage.status is StageStatus.RUNNING:
        if stage.lease_expires_at is None or stage.lease_expires_at > now:
            raise ClaimConflict("stage has an active lease")
    elif stage.status is not StageStatus.PENDING:
        raise ClaimConflict("only pending or expired running stages can be claimed")
    return replace(
        stage,
        status=StageStatus.RUNNING,
        lease_epoch=stage.lease_epoch + 1,
        worker_id=worker_id,
        lease_expires_at=now + lease_duration,
    )


def publish_stage_output(
    stage: PipelineStage,
    *,
    supplied_epoch: int,
    output_digest: str,
    now: datetime,
) -> PipelineStage:
    """Publish only under the current, live fenced lease."""
    _require_aware(now)
    if stage.status is not StageStatus.RUNNING:
        raise FencedPublication("stage must be RUNNING to publish")
    if stage.lease_epoch != supplied_epoch:
        raise FencedPublication("supplied lease epoch is stale")
    if stage.lease_expires_at is None or stage.lease_expires_at <= now:
        raise FencedPublication("lease expired before publication")
    if not _is_digest(output_digest):
        raise FencedPublication("output digest is invalid")
    return replace(
        stage,
        status=StageStatus.SUCCEEDED,
        lease_expires_at=None,
        output_digest=output_digest,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PipelineError("database time must be timezone-aware")


def _is_digest(value: str) -> bool:
    return value.startswith("sha256:") and len(value) == 71 and all(
        character in "0123456789abcdef" for character in value[7:]
    )
