"""Acceptance gate for the canonical PostgreSQL/PostGIS M10 demo seed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from canopyledger.api.app import create_postgres_app
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
    database_url: str,
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
    api = TestClient(create_postgres_app(database_url))
    headers = {"Authorization": "Bearer approver-demo-token"}

    # The canonical persisted envelopes must drive every primary typed read model.
    collateral = api.get(
        f"/api/v1/snapshots/{seeded.snapshot_id}/collateral", headers=headers
    )
    assert collateral.status_code == 200, collateral.text
    collateral_body = collateral.json()
    assert collateral_body["inventory_items"][0]["gross_market_value"] == {
        "amount": "99901.65",
        "currency": "EUR",
    }
    assert collateral_body["lineage"]["contractual_borrowing_base_output_digest"].startswith(
        "sha256:"
    )
    assert collateral_body["lineage"]["collateral_valuation_output_digest"].startswith(
        "sha256:"
    )
    assert collateral_body["lineage"]["eligibility_output_digest"].startswith("sha256:")

    hedge = api.get(f"/api/v1/snapshots/{seeded.snapshot_id}/hedge-lab", headers=headers)
    assert hedge.status_code == 200, hedge.text
    assert hedge.json()["exposure"]["net_price_exposure"] == "24.95143060"

    scenario = api.get(
        f"/api/v1/snapshots/{seeded.snapshot_id}/scenario-lab", headers=headers
    )
    assert scenario.status_code == 200, scenario.text
    assert scenario.json()["monte_carlo"]["path_count"] == 500
