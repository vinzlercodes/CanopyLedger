"""Deterministic M7 extraction benchmark for checked-in or caller-supplied fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .engine import parse_document


@dataclass(frozen=True)
class ExtractionBenchmarkCase:
    case_id: str
    filename: str
    content_type: str
    content: bytes
    expected_document_type: str
    expected_fact_types: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionBenchmarkResult:
    case_count: int
    classification_accuracy: str
    candidate_exactness: str
    failures: tuple[str, ...]


def run_extraction_benchmark(
    cases: tuple[ExtractionBenchmarkCase, ...],
) -> ExtractionBenchmarkResult:
    """Score classification and candidate types without approval state or mutable data."""
    if not cases:
        raise ValueError("document extraction benchmark requires at least one case")
    classification_matches = 0
    candidate_matches = 0
    failures: list[str] = []
    for case in cases:
        result = parse_document(
            filename=case.filename,
            content_type=case.content_type,
            content=case.content,
        )
        if result.classification.document_type == case.expected_document_type:
            classification_matches += 1
        else:
            failures.append(
                f"{case.case_id}: document type {result.classification.document_type!r} "
                f"does not match {case.expected_document_type!r}"
            )
        actual_fact_types = tuple(sorted(candidate.fact_type for candidate in result.candidates))
        expected_fact_types = tuple(sorted(case.expected_fact_types))
        if actual_fact_types == expected_fact_types:
            candidate_matches += 1
        else:
            failures.append(
                f"{case.case_id}: candidate types {actual_fact_types!r} "
                f"do not match {expected_fact_types!r}"
            )
    total = Decimal(len(cases))
    return ExtractionBenchmarkResult(
        case_count=len(cases),
        classification_accuracy=_ratio(Decimal(classification_matches), total),
        candidate_exactness=_ratio(Decimal(candidate_matches), total),
        failures=tuple(failures),
    )


def _ratio(numerator: Decimal, denominator: Decimal) -> str:
    return f"{(numerator / denominator).quantize(Decimal('0.0001')):.4f}"
