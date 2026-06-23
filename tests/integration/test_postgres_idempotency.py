"""Transactional PostgreSQL command idempotency acceptance tests."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock

import pytest
from sqlalchemy import Engine, func, insert, select

from canopyledger.application.integrity import (
    CreateFacilityCommand,
    IntegrityService,
    PreconditionFailed,
    UpdateFacilityCommand,
)
from canopyledger.application.models import FacilityState
from canopyledger.application.ports import IntegrityTransaction
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.idempotency import (
    IdempotencyConflict,
    IdempotencyScope,
    StoredResponse,
    request_fingerprint,
)
from canopyledger.persistence.postgres import IdempotencyInProgress, PostgresIntegrityStore
from canopyledger.persistence.schema import (
    facility_working_state,
    idempotency_record,
    idempotency_tombstone,
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 6, 21, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def unique_scope(operation: str = "test_command") -> IdempotencyScope:
    return IdempotencyScope(ACTOR_ID, operation, "test-resources", new_resource_id("key"))


def fingerprint(body: dict[str, object]) -> str:
    return request_fingerprint(
        method="POST",
        path="/test-resources",
        schema_version="test-command-v1",
        body=body,
    )


def test_identical_command_replays_original_response_without_repeating_effect(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    request_digest = fingerprint({"value": "first"})
    facility_id = new_resource_id("fac")
    calls = 0

    def command(transaction: IntegrityTransaction) -> StoredResponse:
        nonlocal calls
        calls += 1
        transaction.insert_facility(
            FacilityState(
                resource_id=facility_id,
                legal_name="Idempotent Coffee BV",
                currency="EUR",
                facility_commitment="100.00",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        return StoredResponse(201, {"Location": f"/facilities/{facility_id}"}, b'{"ok":true}')

    first, first_replayed = store.execute_idempotent(scope, request_digest, NOW, command)
    second, second_replayed = store.execute_idempotent(scope, request_digest, NOW, command)

    assert first == second
    assert first_replayed is False
    assert second_replayed is True
    assert calls == 1


def test_changed_fingerprint_is_rejected(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    store.execute_idempotent(
        scope,
        fingerprint({"value": "first"}),
        NOW,
        lambda _: StoredResponse(204, {}, b""),
    )
    with pytest.raises(IdempotencyConflict, match="different fingerprint"):
        store.execute_idempotent(
            scope,
            fingerprint({"value": "changed"}),
            NOW,
            lambda _: StoredResponse(204, {}, b""),
        )


def test_concurrent_first_use_executes_effect_once_and_replays_winner(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    request_digest = fingerprint({"value": "concurrent"})
    start = Barrier(2)
    effect_lock = Lock()
    effect_count = 0

    def command(_: IntegrityTransaction) -> StoredResponse:
        nonlocal effect_count
        with effect_lock:
            effect_count += 1
        time.sleep(0.1)
        return StoredResponse(201, {"Location": "/winner"}, b'{"winner":true}')

    def invoke() -> tuple[StoredResponse, bool]:
        start.wait()
        return store.execute_idempotent(scope, request_digest, NOW, command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: invoke(), range(2)))

    assert effect_count == 1
    assert {replayed for _, replayed in results} == {False, True}
    assert results[0][0] == results[1][0]


def test_idempotency_scope_is_isolated_by_actor(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    key = new_resource_id("key")
    first_scope = IdempotencyScope(ACTOR_ID, "test_command", "test-resources", key)
    second_scope = IdempotencyScope(
        "act_0198a000-0000-7000-8000-000000000002",
        "test_command",
        "test-resources",
        key,
    )
    request_digest = fingerprint({"value": "actor-scoped"})

    first, first_replayed = store.execute_idempotent(
        first_scope,
        request_digest,
        NOW,
        lambda _: StoredResponse(201, {}, b'{"actor":1}'),
    )
    second, second_replayed = store.execute_idempotent(
        second_scope,
        request_digest,
        NOW,
        lambda _: StoredResponse(201, {}, b'{"actor":2}'),
    )
    assert first.body != second.body
    assert first_replayed is False
    assert second_replayed is False


def test_command_failure_rolls_back_effect_and_idempotency_claim(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    request_digest = fingerprint({"value": "rollback"})
    facility_id = new_resource_id("fac")

    def failing_command(transaction: IntegrityTransaction) -> StoredResponse:
        transaction.insert_facility(
            FacilityState(
                resource_id=facility_id,
                legal_name="Rollback Coffee BV",
                currency="EUR",
                facility_commitment="100.00",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        raise RuntimeError("injected command failure")

    with pytest.raises(RuntimeError, match="injected command failure"):
        store.execute_idempotent(scope, request_digest, NOW, failing_command)

    with database_engine.connect() as connection:
        facility_count = connection.execute(
            select(func.count())
            .select_from(facility_working_state)
            .where(facility_working_state.c.resource_id == facility_id)
        ).scalar_one()
        record_count = connection.execute(
            select(func.count())
            .select_from(idempotency_record)
            .where(idempotency_record.c.idempotency_key == scope.key)
        ).scalar_one()
    assert facility_count == 0
    assert record_count == 0


def test_visible_pending_record_returns_deterministic_in_progress(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    request_digest = fingerprint({"value": "pending"})
    with database_engine.begin() as connection:
        connection.execute(
            insert(idempotency_record).values(
                actor_id=scope.actor_id,
                operation=scope.operation,
                resource_namespace=scope.resource_namespace,
                idempotency_key=scope.key,
                fingerprint=request_digest,
                state="PENDING",
                created_at=NOW,
                retain_until=NOW + timedelta(days=365 * 7),
            )
        )
    with pytest.raises(IdempotencyInProgress, match="still in progress"):
        store.execute_idempotent(
            scope,
            request_digest,
            NOW,
            lambda _: StoredResponse(204, {}, b""),
        )


def test_expired_record_becomes_permanent_tombstone(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    scope = unique_scope()
    request_digest = fingerprint({"value": "expire"})
    store.execute_idempotent(
        scope,
        request_digest,
        NOW,
        lambda _: StoredResponse(204, {}, b""),
    )
    expired_at = NOW + timedelta(days=365 * 7)
    assert store.expire_idempotency_records(expired_at) >= 1

    with pytest.raises(IdempotencyConflict, match="expired tombstone"):
        store.execute_idempotent(
            scope,
            request_digest,
            expired_at,
            lambda _: StoredResponse(204, {}, b""),
        )
    with database_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(idempotency_tombstone)
            .where(idempotency_tombstone.c.idempotency_key == scope.key)
        ).scalar_one()
    assert count == 1


def test_facility_service_persists_versions_and_replays_update_after_version_changes(
    database_engine: Engine,
) -> None:
    ids = iter((new_resource_id("fac"), new_resource_id("aud"), new_resource_id("aud")))
    service = IntegrityService(
        PostgresIntegrityStore(database_engine),
        clock=lambda: NOW,
        id_factory=lambda _: next(ids),
    )
    create = CreateFacilityCommand(
        actor_id=ACTOR_ID,
        idempotency_key=new_resource_id("key"),
        legal_name="Durable Coffee BV",
        currency="EUR",
        facility_commitment="1000000.00",
        correlation_id=new_resource_id("cor"),
    )
    created = service.create_facility(create)
    representation = json.loads(created.body)
    facility_id = representation["id"]

    update = UpdateFacilityCommand(
        actor_id=ACTOR_ID,
        facility_id=facility_id,
        idempotency_key=new_resource_id("key"),
        if_match=created.headers["ETag"],
        legal_name="Durable Coffee Trading BV",
        reason="Legal name correction",
        correlation_id=new_resource_id("cor"),
    )
    updated = service.update_facility(update)
    replayed = service.update_facility(update)

    assert json.loads(updated.body)["version"] == 2
    assert replayed.body == updated.body
    assert replayed.replayed is True
    with pytest.raises(PreconditionFailed):
        service.update_facility(
            UpdateFacilityCommand(
                actor_id=ACTOR_ID,
                facility_id=facility_id,
                idempotency_key=new_resource_id("key"),
                if_match=created.headers["ETag"],
                legal_name="Stale Name BV",
                reason="Stale correction",
                correlation_id=new_resource_id("cor"),
            )
        )
