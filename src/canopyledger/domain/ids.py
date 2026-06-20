"""Type-prefixed UUIDv7 resource IDs."""

from __future__ import annotations

import secrets
import time
import uuid


def new_resource_id(prefix: str) -> str:
    """Generate a lowercase type-prefixed UUIDv7-compatible identifier."""
    if len(prefix) != 3 or not prefix.isascii() or not prefix.islower() or not prefix.isalpha():
        raise ValueError("resource prefix must be three lowercase ASCII letters")
    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << 48:
        raise RuntimeError("timestamp exceeds UUIDv7 range")
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= random_a << 64
    value |= 0b10 << 62
    value |= random_b
    return f"{prefix}_{uuid.UUID(int=value)}"

