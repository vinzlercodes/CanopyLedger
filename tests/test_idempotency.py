"""Normative idempotency contract tests."""

from datetime import UTC, datetime, timedelta

import pytest

from canopyledger.integrity.idempotency import (
    IdempotencyConflict,
    IdempotencyLedger,
    IdempotencyScope,
    StoredResponse,
    request_fingerprint,
)


def test_request_fingerprint_is_independent_of_object_key_order() -> None:
    first = request_fingerprint(
        method="POST",
        path="/api/v1/facilities",
        schema_version="facility-create-v1",
        body={"currency": "EUR", "limit": "100.00"},
    )
    second = request_fingerprint(
        method="post",
        path="/api/v1/facilities",
        schema_version="facility-create-v1",
        body={"limit": "100.00", "currency": "EUR"},
    )
    assert first == second


def test_same_scope_and_fingerprint_replays_original_response() -> None:
    ledger = IdempotencyLedger()
    scope = IdempotencyScope("actor_1", "create_facility", "facilities", "request-key-0001")
    fingerprint = "sha256:" + "a" * 64
    response = StoredResponse(201, {"location": "/api/v1/facilities/fac_1"}, b'{"id":"fac_1"}')
    now = datetime(2026, 6, 21, tzinfo=UTC)

    assert ledger.register(scope, fingerprint, response, now=now) is response
    assert ledger.register(scope, fingerprint, response, now=now + timedelta(seconds=1)) is response


def test_same_scope_with_changed_fingerprint_conflicts() -> None:
    ledger = IdempotencyLedger()
    scope = IdempotencyScope("actor_1", "create_facility", "facilities", "request-key-0001")
    response = StoredResponse(201, {}, b"{}")
    now = datetime(2026, 6, 21, tzinfo=UTC)
    ledger.register(scope, "sha256:" + "a" * 64, response, now=now)

    with pytest.raises(IdempotencyConflict, match="different fingerprint"):
        ledger.register(scope, "sha256:" + "b" * 64, response, now=now)


def test_expired_response_leaves_tombstone_that_blocks_reuse() -> None:
    ledger = IdempotencyLedger(retention=timedelta(days=1))
    scope = IdempotencyScope("actor_1", "create_facility", "facilities", "request-key-0001")
    response = StoredResponse(201, {}, b"{}")
    now = datetime(2026, 6, 21, tzinfo=UTC)
    ledger.register(scope, "sha256:" + "a" * 64, response, now=now)
    ledger.expire(now=now + timedelta(days=2))

    with pytest.raises(IdempotencyConflict, match="expired tombstone"):
        ledger.register(scope, "sha256:" + "a" * 64, response, now=now + timedelta(days=2))
