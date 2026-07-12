"""M4A immutable scenario and IRC API surface."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from test_scenario_capacity import _input

from canopyledger.api.app import create_app
from canopyledger.scenario.pipeline import build_scenario_capacity_stage_output


def test_snapshot_scenario_and_irc_routes_only_serve_one_published_output() -> None:
    value = _input()
    output = build_scenario_capacity_stage_output(
        value,
        stage_output_id="out_0198a000-0000-7000-8000-000000000001",
        started_at=datetime(2026, 7, 11, tzinfo=UTC),
        completed_at=datetime(2026, 7, 11, tzinfo=UTC),
    ).to_canonical_dict()
    app = create_app(
        scenario_output_loader=lambda snapshot_id: (
            output if snapshot_id == value.snapshot_id else None
        )
    )
    for path in ("scenarios", "irc"):
        response = TestClient(app).get(
            f"/api/v1/snapshots/{value.snapshot_id}/{path}",
            headers={"Authorization": "Bearer analyst-demo-token"},
        )
        assert response.status_code == 200, response.text
        assert Decimal(response.json()["internal_risk_capacity"]["irc"]) <= Decimal(
            response.json()["internal_risk_capacity"]["cbb"]
        )
