"""Queue fencing and exactly-once publication contract tests."""

from datetime import UTC, datetime, timedelta

import pytest

from canopyledger.integrity.pipeline import (
    FencedPublication,
    PipelineStage,
    StageStatus,
    claim_stage,
    publish_stage_output,
)


def test_reclaim_increments_epoch_and_fences_stale_worker() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    stage = PipelineStage.pending("stage_valuation")
    worker_a = claim_stage(
        stage,
        worker_id="worker_a",
        now=now,
        lease_duration=timedelta(seconds=30),
    )
    worker_b = claim_stage(
        worker_a,
        worker_id="worker_b",
        now=now + timedelta(seconds=31),
        lease_duration=timedelta(seconds=30),
    )
    assert worker_b.lease_epoch == worker_a.lease_epoch + 1

    with pytest.raises(FencedPublication, match="lease epoch"):
        publish_stage_output(
            worker_b,
            supplied_epoch=worker_a.lease_epoch,
            output_digest="sha256:" + "a" * 64,
            now=now + timedelta(seconds=32),
        )


def test_current_worker_publishes_one_authoritative_output() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    claimed = claim_stage(
        PipelineStage.pending("stage_valuation"),
        worker_id="worker_a",
        now=now,
        lease_duration=timedelta(seconds=30),
    )
    published = publish_stage_output(
        claimed,
        supplied_epoch=claimed.lease_epoch,
        output_digest="sha256:" + "a" * 64,
        now=now + timedelta(seconds=1),
    )
    assert published.status is StageStatus.SUCCEEDED
    assert published.output_digest == "sha256:" + "a" * 64

    with pytest.raises(FencedPublication, match="RUNNING"):
        publish_stage_output(
            published,
            supplied_epoch=published.lease_epoch,
            output_digest="sha256:" + "a" * 64,
            now=now + timedelta(seconds=2),
        )


def test_expired_lease_cannot_publish_even_before_reclaim() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    claimed = claim_stage(
        PipelineStage.pending("stage_valuation"),
        worker_id="worker_a",
        now=now,
        lease_duration=timedelta(seconds=30),
    )
    with pytest.raises(FencedPublication, match="expired"):
        publish_stage_output(
            claimed,
            supplied_epoch=claimed.lease_epoch,
            output_digest="sha256:" + "a" * 64,
            now=now + timedelta(seconds=30),
        )
