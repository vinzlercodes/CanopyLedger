"""Reproduce the public M6 synthetic credit-model artifact with no external model service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from canopyledger.credit.training import fit_reference_model, generate_synthetic_borrower_panel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/credit/reference-v1"))
    args = parser.parse_args()
    artifact = fit_reference_model(generate_synthetic_borrower_panel())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "model-bundle.json").write_text(
        json.dumps(
            {"bundle": artifact.bundle.canonical_dict(), "digest": artifact.bundle.digest},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "model-card.json").write_text(
        json.dumps(
            {
                "model_card": artifact.model_card,
                "evaluation": artifact.canonical_dict()["evaluation"],
                "leakage_report": artifact.canonical_dict()["leakage_report"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output_dir} with model bundle {artifact.bundle.digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
