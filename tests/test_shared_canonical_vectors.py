"""Cross-runtime Canonical Value Profile vector tests."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from canopyledger.integrity.canonical import (
    CanonicalSetRule,
    CanonicalValueError,
    canonical_decimal,
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)

VECTORS = json.loads(
    (Path(__file__).parents[1] / "canonical-vectors" / "v1.json").read_text()
)


@pytest.mark.parametrize("vector", VECTORS["json"], ids=lambda value: str(value["id"]))
def test_shared_json_vector(vector: dict[str, Any]) -> None:
    rules = tuple(
        CanonicalSetRule(path=tuple(rule["path"]), sort_keys=tuple(rule["sort_keys"]))
        for rule in vector["set_rules"]
    )
    actual = canonical_json_bytes(vector["value"], set_rules=rules).decode()
    assert actual == vector["expected_utf8"]


@pytest.mark.parametrize("vector", VECTORS["decimals"], ids=lambda value: str(value["id"]))
def test_shared_decimal_vector(vector: dict[str, Any]) -> None:
    assert canonical_decimal(Decimal(vector["value"]), scale=vector["scale"]) == vector["expected"]


@pytest.mark.parametrize("vector", VECTORS["timestamps"], ids=lambda value: str(value["id"]))
def test_shared_timestamp_vector(vector: dict[str, Any]) -> None:
    assert canonical_timestamp(datetime.fromisoformat(vector["value"])) == vector["expected"]


@pytest.mark.parametrize("vector", VECTORS["digests"], ids=lambda value: str(value["id"]))
def test_shared_digest_vector(vector: dict[str, Any]) -> None:
    assert (
        domain_digest(vector["artifact"], vector["version"], vector["payload_utf8"].encode())
        == vector["expected"]
    )


@pytest.mark.parametrize("vector", VECTORS["rejections"], ids=lambda value: str(value["id"]))
def test_shared_rejection_vector(vector: dict[str, Any]) -> None:
    with pytest.raises(CanonicalValueError, match=vector["error"]):
        if vector["operation"] == "json":
            rules = tuple(
                CanonicalSetRule(path=tuple(rule["path"]), sort_keys=tuple(rule["sort_keys"]))
                for rule in vector["set_rules"]
            )
            canonical_json_bytes(vector["value"], set_rules=rules)
        elif vector["operation"] == "decimal":
            canonical_decimal(Decimal(vector["value"]), scale=vector["scale"])
        else:
            canonical_timestamp(datetime.fromisoformat(vector["value"]))
