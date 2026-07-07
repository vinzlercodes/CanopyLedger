"""CLI demo for deterministic M1B CBB certificates."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from canopyledger.borrowing_base.calculation import (
    CollateralContribution,
    ContractualReserve,
    calculate_contractual_borrowing_base,
)
from canopyledger.borrowing_base.certificate import ContractualUsage, build_cbb_certificate
from canopyledger.domain.money import Money
from canopyledger.integrity.canonical import canonical_json_bytes


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON M1B CBB demo input")
    parser.add_argument("--output", type=Path, help="write certificate JSON to this path")
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    certificate = build_certificate_from_payload(payload)
    output = canonical_json_bytes(certificate.to_canonical_dict())
    if args.output is None:
        print(output.decode("utf-8"))
    else:
        args.output.write_bytes(output)
    return 0


def build_certificate_from_payload(payload: dict[str, Any]) -> Any:
    facility_limit = _money(payload["facility_limit"])
    contributions = tuple(
        CollateralContribution(
            str(item["source_type"]),
            str(item["source_id"]),
            _money(item["amount"]),
        )
        for item in payload["contributions"]
    )
    reserves = tuple(
        ContractualReserve(str(item["reserve_type"]), _money(item["amount"]))
        for item in payload["reserves"]
    )
    assessment = calculate_contractual_borrowing_base(
        facility_limit=facility_limit,
        contributions=contributions,
        reserves=reserves,
    )
    usage_payload = payload["usage"]
    usage = ContractualUsage(
        current_principal=_money(usage_payload["current_principal"]),
        lc_exposure=_money(usage_payload["lc_exposure"]),
        other_contractual_usage=_money(usage_payload["other_contractual_usage"]),
    )
    return build_cbb_certificate(
        certificate_id=str(payload["certificate_id"]),
        snapshot_id=str(payload["snapshot_id"]),
        facility_id=str(payload["facility_id"]),
        assessment=assessment,
        contributions=contributions,
        reserves=reserves,
        usage=usage,
        reason_codes=tuple(str(code) for code in payload["reason_codes"]),
    )


def _money(payload: dict[str, str]) -> Money:
    return Money(Decimal(payload["amount"]), payload["currency"])


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
