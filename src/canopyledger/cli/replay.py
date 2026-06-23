"""Canonical replay-package verifier CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from canopyledger.integrity.replay import ReplayPackage, ReplayStatus, verify_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a CanopyLedger replay package")
    parser.add_argument("package", type=Path)
    parser.add_argument("--environment", required=True, help="Current environment JSON object")
    args = parser.parse_args(argv)
    package = ReplayPackage.from_json(json.loads(args.package.read_text()))
    environment = json.loads(args.environment)
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
    ):
        parser.error("--environment must be a JSON object of string values")
    result = verify_replay(package, current_environment=environment)
    sys.stdout.buffer.write(result.canonical_bytes + b"\n")
    return 0 if result.level_a is result.level_b is ReplayStatus.MATCH else 1


if __name__ == "__main__":
    raise SystemExit(main())
