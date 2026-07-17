"""Acceptance gate for the canonical PostgreSQL/PostGIS M10 demo seed."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select

from canopyledger.demo.postgres import seed_demo_workspace
from canopyledger.persistence.schema import (
    hedge_liquidity_input,
    pipeline_stage_output,
    report_artifact,
    report_model,
)

pytestmark = pytest.mark.postgres


def test_seed_demo_workspace_publishes_all_report_sources_and_package(
    database_engine: Engine,
) -> None:
    """The local demo is a fully governed frozen snapshot, not a mock projection."""
    seeded = seed_demo_workspace(database_engine)

    assert seeded.snapshot_id.startswith("snp_")
    assert seeded.decision_id.startswith("fdc_")
    assert seeded.report_id.startswith("rpt_")
    assert seeded.report_model_digest.startswith("sha256:")
    assert set(seeded.artifact_digests) == {"HTML", "PDF"}
    with database_engine.connect() as connection:
        stage_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.snapshot_id == seeded.snapshot_id)
        ).scalar_one()
        model_count = connection.execute(
            select(func.count())
            .select_from(report_model)
            .where(report_model.c.resource_id == seeded.report_id)
        ).scalar_one()
        artifact_count = connection.execute(
            select(func.count())
            .select_from(report_artifact)
            .join(report_model)
            .where(report_model.c.resource_id == seeded.report_id)
        ).scalar_one()
        hedge_input_ids = set(
            connection.execute(select(hedge_liquidity_input.c.resource_id)).scalars()
        )

    assert stage_count == 8
    assert model_count == 1
    assert artifact_count == 2
    assert "hdl_0198a000-0000-7000-8000-000000009501" in hedge_input_ids
    assert "hdl_0198a000-0000-7000-8000-000000000001" not in hedge_input_ids
