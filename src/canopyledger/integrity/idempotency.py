"""Normative idempotency fingerprint and replay semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .canonical import canonical_json_bytes, domain_digest


class IdempotencyError(ValueError):
    """Base idempotency contract error."""


class IdempotencyConflict(IdempotencyError):
    """Raised when a key cannot be registered or replayed safely."""


@dataclass(frozen=True)
class IdempotencyScope:
    actor_id: str
    operation: str
    resource_namespace: str
    key: str

    def __post_init__(self) -> None:
        if not 16 <= len(self.key) <= 128:
            raise IdempotencyError("idempotency key length must be 16 through 128")
        if not self.key.isascii() or not self.key.isprintable():
            raise IdempotencyError("idempotency key must be printable ASCII")
        if not self.actor_id or not self.operation or not self.resource_namespace:
            raise IdempotencyError("idempotency scope fields cannot be empty")


@dataclass(frozen=True)
class StoredResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class _Record:
    fingerprint: str
    response: StoredResponse
    created_at: datetime


def request_fingerprint(
    *,
    method: str,
    path: str,
    schema_version: str,
    body: Any,
    relevant_headers: Mapping[str, str] | None = None,
) -> str:
    """Fingerprint one normalized command request."""
    normalized_method = method.upper()
    if normalized_method not in {"POST", "PATCH", "PUT", "DELETE"}:
        raise IdempotencyError("fingerprints are only defined for mutation methods")
    if not path.startswith("/") or "?" in path or "#" in path:
        raise IdempotencyError("path must be absolute and exclude query or fragment")
    headers = {
        key.lower(): value.strip()
        for key, value in sorted((relevant_headers or {}).items(), key=lambda item: item[0].lower())
    }
    payload = canonical_json_bytes(
        {
            "method": normalized_method,
            "path": path,
            "schema_version": schema_version,
            "headers": headers,
            "body": body,
        }
    )
    return domain_digest("request_fingerprint", 1, payload)


class IdempotencyLedger:
    """In-memory contract implementation; persistence adapter follows same semantics."""

    def __init__(self, *, retention: timedelta = timedelta(days=365 * 7)) -> None:
        if retention <= timedelta(0):
            raise IdempotencyError("retention must be positive")
        self._retention = retention
        self._records: dict[IdempotencyScope, _Record] = {}
        self._tombstones: set[IdempotencyScope] = set()

    def register(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        response: StoredResponse,
        *,
        now: datetime,
    ) -> StoredResponse:
        if now.tzinfo is None or now.utcoffset() is None:
            raise IdempotencyError("registration time must be timezone-aware")
        if scope in self._tombstones:
            raise IdempotencyConflict("idempotency key has an expired tombstone")
        existing = self._records.get(scope)
        if existing is None:
            self._records[scope] = _Record(fingerprint, response, now)
            return response
        if existing.fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key was reused with a different fingerprint")
        return existing.response

    def lookup(self, scope: IdempotencyScope, fingerprint: str) -> StoredResponse | None:
        """Return a replayable response or reject conflicting/tombstoned reuse."""
        if scope in self._tombstones:
            raise IdempotencyConflict("idempotency key has an expired tombstone")
        existing = self._records.get(scope)
        if existing is None:
            return None
        if existing.fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key was reused with a different fingerprint")
        return existing.response

    def expire(self, *, now: datetime) -> None:
        expired = [
            scope
            for scope, record in self._records.items()
            if record.created_at + self._retention <= now
        ]
        for scope in expired:
            del self._records[scope]
            self._tombstones.add(scope)
