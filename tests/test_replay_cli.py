"""Replay CLI exit and canonical output tests."""

from __future__ import annotations

import json

from canopyledger.cli.replay import main


def test_cli_returns_nonzero_and_prints_canonical_result_on_mismatch(tmp_path, capsys) -> None:
    package_path = tmp_path / "package.json"
    package_path.write_text(
        json.dumps(
            {
                "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
                "declared_environment": {"cpu": "arm64"},
                "artifacts": [],
            }
        )
    )
    assert main([str(package_path), "--environment", '{"cpu":"x86_64"}']) == 1
    output = capsys.readouterr().out.encode().strip()
    assert json.loads(output)["level_a"] == "MISMATCH"
