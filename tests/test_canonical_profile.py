"""Contract tests for Canopy Canonical Value Profile v1."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from canopyledger.integrity.canonical import (
    CanonicalSetRule,
    CanonicalValueError,
    canonical_decimal,
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (Decimal("0"), 2, "0.00"),
        (Decimal("0.25"), 2, "0.25"),
        (Decimal("-0.25"), 2, "-0.25"),
        (Decimal("123.4"), 2, "123.40"),
    ],
)
def test_decimal_uses_fixed_scale(value: Decimal, scale: int, expected: str) -> None:
    assert canonical_decimal(value, scale=scale) == expected


def test_decimal_rejects_negative_zero() -> None:
    with pytest.raises(CanonicalValueError, match="negative zero"):
        canonical_decimal(Decimal("-0.00"), scale=2)


def test_decimal_rejects_value_requiring_rounding() -> None:
    with pytest.raises(CanonicalValueError, match="declared scale"):
        canonical_decimal(Decimal("1.005"), scale=2)


def test_timestamp_normalizes_utc_to_fixed_microseconds() -> None:
    value = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    assert canonical_timestamp(value) == "2026-06-21T17:00:00.000000Z"


def test_timestamp_rejects_naive_value() -> None:
    with pytest.raises(CanonicalValueError, match="timezone-aware"):
        canonical_timestamp(datetime(2026, 6, 21, 17, 0))


def test_digest_is_domain_separated() -> None:
    payload = b'{"amount":"1.00"}'
    snapshot = domain_digest("snapshot", 1, payload)
    manifest = domain_digest("manifest", 1, payload)
    assert snapshot != manifest
    assert snapshot.startswith("sha256:")
    assert len(snapshot) == len("sha256:") + 64


def test_arrays_preserve_source_order_by_default() -> None:
    payload = {"stages": [{"id": "second"}, {"id": "first"}]}
    assert canonical_json_bytes(payload) == b'{"stages":[{"id":"second"},{"id":"first"}]}'


def test_declared_set_sorts_by_field_specific_key() -> None:
    payload = {
        "evidence": [
            {"document_digest": "sha256:b", "document_id": "doc_2"},
            {"document_digest": "sha256:a", "document_id": "doc_1"},
        ]
    }
    rules = [
        CanonicalSetRule(
            path=("evidence",),
            sort_keys=("document_digest", "document_id"),
        )
    ]
    assert canonical_json_bytes(payload, set_rules=rules) == (
        b'{"evidence":[{"document_digest":"sha256:a","document_id":"doc_1"},'
        b'{"document_digest":"sha256:b","document_id":"doc_2"}]}'
    )


def test_set_rules_accept_single_pass_iterable() -> None:
    rules = (
        rule
        for rule in [CanonicalSetRule(path=("ids",), sort_keys=("id",))]
    )
    assert canonical_json_bytes({"ids": [{"id": "b"}, {"id": "a"}]}, set_rules=rules) == (
        b'{"ids":[{"id":"a"},{"id":"b"}]}'
    )


def test_strings_are_normalized_to_nfc() -> None:
    assert canonical_json_bytes({"origin": "Cafe\u0301"}) == (
        '{"origin":"Caf\u00e9"}'.encode()
    )


def test_floating_point_numbers_are_rejected() -> None:
    with pytest.raises(CanonicalValueError, match="floating-point"):
        canonical_json_bytes({"amount": 1.25})
