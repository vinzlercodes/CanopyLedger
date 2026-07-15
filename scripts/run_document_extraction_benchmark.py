"""Run the deterministic M7 document-extraction benchmark fixture."""

from __future__ import annotations

import json

from canopyledger.document_intelligence.benchmark import (
    ExtractionBenchmarkCase,
    run_extraction_benchmark,
)


def main() -> int:
    result = run_extraction_benchmark(
        (
            ExtractionBenchmarkCase(
                case_id="warehouse-receipt-v1",
                filename="warehouse-receipt.txt",
                content_type="text/plain",
                content=(
                    b"WAREHOUSE RECEIPT\nWarehouse ID: wh_fixture\nReceipt Number: WR-001\n"
                    b"Lot ID: lot_fixture\nAs Of: 2026-07-15\nQuantity: 100 bags\n"
                ),
                expected_document_type="warehouse_receipt",
                expected_fact_types=("inventory_quantity", "warehouse_receipt"),
            ),
        )
    )
    print(json.dumps(result.__dict__, sort_keys=True, separators=(",", ":")))
    return 0 if not result.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
