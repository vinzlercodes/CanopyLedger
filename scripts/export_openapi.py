"""Export or verify the deterministic OpenAPI v1 artifact."""

import argparse
from pathlib import Path

from canopyledger.api.app import create_app
from canopyledger.api.openapi import render_openapi_json

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "docs" / "api" / "openapi-v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in artifact differs from generated OpenAPI",
    )
    args = parser.parse_args()
    generated = render_openapi_json(create_app())

    if args.check:
        if not ARTIFACT.exists() or ARTIFACT.read_bytes() != generated:
            parser.error("OpenAPI artifact is stale; run scripts/export_openapi.py")
        return 0

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
