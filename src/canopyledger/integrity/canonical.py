"""Canopy Canonical Value Profile v1 primitives."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class CanonicalValueError(ValueError):
    """Raised when a value has no valid canonical representation."""


@dataclass(frozen=True)
class CanonicalSetRule:
    """Declare one JSON array as unordered with an explicit stable sort key."""

    path: tuple[str, ...]
    sort_keys: tuple[str, ...]


def canonical_decimal(value: Decimal, *, scale: int) -> str:
    """Render a decimal with exact declared scale and no implicit rounding."""
    if scale < 0:
        raise CanonicalValueError("scale must be non-negative")
    if not value.is_finite():
        raise CanonicalValueError("decimal must be finite")
    if value.is_zero() and value.is_signed():
        raise CanonicalValueError("negative zero is forbidden")

    quantum = Decimal(1).scaleb(-scale)
    try:
        quantized = value.quantize(quantum)
    except InvalidOperation as exc:
        raise CanonicalValueError("decimal exceeds supported precision") from exc
    if quantized != value:
        raise CanonicalValueError("decimal exceeds declared scale")
    return format(quantized, f".{scale}f")


def canonical_timestamp(value: datetime) -> str:
    """Render an aware timestamp as UTC with fixed microsecond precision."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalValueError("timestamp must be timezone-aware")
    normalized = value.astimezone(UTC)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def domain_digest(artifact: str, version: int, payload: bytes) -> str:
    """Hash bytes with artifact/version domain separation."""
    invalid_character = any(
        character not in "abcdefghijklmnopqrstuvwxyz_" for character in artifact
    )
    if not artifact or invalid_character:
        raise CanonicalValueError("artifact must use lowercase ASCII letters and underscores")
    if version < 1:
        raise CanonicalValueError("version must be positive")
    prefix = f"canopyledger:{artifact}:v{version}\0".encode()
    return f"sha256:{hashlib.sha256(prefix + payload).hexdigest()}"


def canonical_json_bytes(
    value: Any,
    *,
    set_rules: Iterable[CanonicalSetRule] = (),
) -> bytes:
    """Serialize supported authoritative values with profile-defined set handling."""
    rule_list = tuple(set_rules)
    rules = {rule.path: rule for rule in rule_list}
    if len(rules) != len(rule_list):
        raise CanonicalValueError("duplicate canonical set rule path")
    normalized = _normalize_json_value(value, path=(), set_rules=rules)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize_json_value(
    value: Any,
    *,
    path: tuple[str, ...],
    set_rules: Mapping[tuple[str, ...], CanonicalSetRule],
) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise CanonicalValueError("binary floating-point values are forbidden")
    if isinstance(value, int):
        if abs(value) > 9_007_199_254_740_991:
            raise CanonicalValueError("integer exceeds interoperable JSON range")
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        try:
            normalized.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CanonicalValueError("string contains invalid Unicode") from exc
        return normalized
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalValueError("object keys must be strings")
        normalized_items = []
        for key, item in value.items():
            normalized_key = _normalize_json_value(key, path=path, set_rules=set_rules)
            normalized_items.append(
                (
                    normalized_key,
                    _normalize_json_value(
                        item,
                        path=(*path, normalized_key),
                        set_rules=set_rules,
                    ),
                )
            )
        normalized_items.sort(key=lambda pair: pair[0].encode("utf-16be"))
        return dict(normalized_items)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized_sequence = [
            _normalize_json_value(item, path=path, set_rules=set_rules) for item in value
        ]
        rule = set_rules.get(path)
        if rule is not None:
            normalized_sequence.sort(key=lambda item: _canonical_set_sort_key(item, rule))
        return normalized_sequence
    raise CanonicalValueError(f"unsupported canonical value type: {type(value).__name__}")


def _canonical_set_sort_key(value: Any, rule: CanonicalSetRule) -> tuple[bytes, ...]:
    if not isinstance(value, Mapping):
        raise CanonicalValueError("declared set members must be objects")
    try:
        return tuple(
            json.dumps(value[key], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            for key in rule.sort_keys
        )
    except KeyError as exc:
        raise CanonicalValueError(f"declared set sort key is missing: {exc.args[0]}") from exc
