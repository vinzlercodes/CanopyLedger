"""PostgreSQL adapters for M1A integrity resources."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from canopyledger.application.models import AuditEventData, FacilityState
from canopyledger.application.ports import IntegrityTransaction
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.idempotency import (
    IdempotencyConflict,
    IdempotencyScope,
    StoredResponse,
)

from .schema import (
    audit_event,
    facility_working_state,
    idempotency_record,
    idempotency_tombstone,
)
from .schema import (
    bundle as bundle_table,
)


class ImmutableBundleConflict(ValueError):
    """Raised when publication would give a bundle ID new content."""


class IdempotencyInProgress(IdempotencyConflict):
    """Raised when a visible command claim has not completed."""


class PostgresIntegrityStore:
    """Explicit transactional adapter for durable integrity resources."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish_bundle(self, bundle: VersionBundle) -> VersionBundle:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(bundle_table).values(
                        resource_id=bundle.resource_id,
                        bundle_type=bundle.bundle_type.value,
                        schema_version=bundle.schema_version,
                        canonical_payload=bundle.canonical_bytes,
                        digest=bundle.digest,
                        created_by=bundle.created_by,
                        created_at=bundle.created_at,
                    )
                )
        except IntegrityError:
            existing = self.load_bundle(bundle.resource_id)
            if existing == bundle:
                return existing
            raise ImmutableBundleConflict(
                f"bundle {bundle.resource_id} already has different immutable content"
            ) from None
        return bundle

    def load_bundle(self, resource_id: str) -> VersionBundle | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(bundle_table).where(bundle_table.c.resource_id == resource_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        return _bundle_from_row(row)

    def execute_idempotent(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]:
        _require_aware(now)
        try:
            return self._execute_idempotent_once(scope, fingerprint, now, command)
        except IntegrityError as exc:
            if _constraint_name(exc) != "pk_idempotency_record":
                raise
        with self._engine.begin() as connection:
            record = connection.execute(
                select(idempotency_record)
                .where(_scope_predicate(idempotency_record.c, scope))
                .with_for_update()
            ).mappings().one()
            return _replay_record(record, fingerprint), True

    def _execute_idempotent_once(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]:
        with self._engine.begin() as connection:
            tombstone = connection.execute(
                select(idempotency_tombstone.c.fingerprint).where(
                    _scope_predicate(idempotency_tombstone.c, scope)
                )
            ).scalar_one_or_none()
            if tombstone is not None:
                raise IdempotencyConflict("idempotency key has an expired tombstone")

            record = connection.execute(
                select(idempotency_record)
                .where(_scope_predicate(idempotency_record.c, scope))
                .with_for_update()
            ).mappings().one_or_none()
            if record is not None:
                return _replay_record(record, fingerprint), True

            connection.execute(
                insert(idempotency_record).values(
                    actor_id=scope.actor_id,
                    operation=scope.operation,
                    resource_namespace=scope.resource_namespace,
                    idempotency_key=scope.key,
                    fingerprint=fingerprint,
                    state="PENDING",
                    created_at=now,
                    retain_until=now + timedelta(days=365 * 7),
                )
            )
            response = command(_PostgresIntegrityTransaction(connection))
            connection.execute(
                update(idempotency_record)
                .where(_scope_predicate(idempotency_record.c, scope))
                .values(
                    state="COMPLETED",
                    response_status=response.status,
                    response_headers=dict(response.headers),
                    response_body=response.body,
                    completed_at=now,
                )
            )
            return response, False

    def expire_idempotency_records(self, now: datetime) -> int:
        _require_aware(now)
        with self._engine.begin() as connection:
            records = connection.execute(
                select(idempotency_record)
                .where(idempotency_record.c.retain_until <= now)
                .with_for_update()
            ).mappings().all()
            for record in records:
                connection.execute(
                    insert(idempotency_tombstone).values(
                        actor_id=record["actor_id"],
                        operation=record["operation"],
                        resource_namespace=record["resource_namespace"],
                        idempotency_key=record["idempotency_key"],
                        fingerprint=record["fingerprint"],
                        expired_at=now,
                    )
                )
                connection.execute(
                    delete(idempotency_record).where(
                        idempotency_record.c.actor_id == record["actor_id"],
                        idempotency_record.c.operation == record["operation"],
                        idempotency_record.c.resource_namespace == record["resource_namespace"],
                        idempotency_record.c.idempotency_key == record["idempotency_key"],
                    )
                )
            return len(records)


class _PostgresIntegrityTransaction:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_facility(self, facility: FacilityState) -> None:
        self._connection.execute(
            insert(facility_working_state).values(
                resource_id=facility.resource_id,
                legal_name=facility.legal_name,
                currency=facility.currency,
                facility_commitment=facility.facility_commitment,
                version=facility.version,
                created_at=facility.created_at,
                updated_at=facility.updated_at,
            )
        )

    def get_facility_for_update(self, resource_id: str) -> FacilityState | None:
        row = self._connection.execute(
            select(facility_working_state)
            .where(facility_working_state.c.resource_id == resource_id)
            .with_for_update()
        ).mappings().one_or_none()
        return None if row is None else _facility_from_row(row)

    def update_facility(self, facility: FacilityState, *, expected_version: int) -> None:
        result = self._connection.execute(
            update(facility_working_state)
            .where(
                facility_working_state.c.resource_id == facility.resource_id,
                facility_working_state.c.version == expected_version,
            )
            .values(
                legal_name=facility.legal_name,
                currency=facility.currency,
                facility_commitment=facility.facility_commitment,
                version=facility.version,
                updated_at=facility.updated_at,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("facility version changed during locked update")

    def append_audit_event(self, event: AuditEventData) -> None:
        self._connection.execute(
            insert(audit_event).values(
                event_id=event.event_id,
                actor_id=event.actor_id,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                before_digest=event.before_digest,
                after_digest=event.after_digest,
                reason=event.reason,
                metadata=dict(event.metadata),
                occurred_at=event.occurred_at,
            )
        )


def _bundle_from_row(row: Any) -> VersionBundle:
    return VersionBundle.restore(
        resource_id=row["resource_id"],
        bundle_type=BundleType(row["bundle_type"]),
        schema_version=row["schema_version"],
        canonical_bytes=row["canonical_payload"],
        digest=row["digest"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _facility_from_row(row: RowMapping) -> FacilityState:
    return FacilityState(
        resource_id=row["resource_id"],
        legal_name=row["legal_name"],
        currency=row["currency"],
        facility_commitment=row["facility_commitment"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _stored_response_from_row(row: RowMapping) -> StoredResponse:
    headers = row["response_headers"]
    if not isinstance(headers, dict):
        raise RuntimeError("completed idempotency response headers are invalid")
    status = row["response_status"]
    body = row["response_body"]
    if not isinstance(status, int) or not isinstance(body, bytes):
        raise RuntimeError("completed idempotency response is incomplete")
    return StoredResponse(status, headers, body)


def _replay_record(row: RowMapping, fingerprint: str) -> StoredResponse:
    if row["fingerprint"] != fingerprint:
        raise IdempotencyConflict("idempotency key was reused with a different fingerprint")
    if row["state"] == "PENDING":
        raise IdempotencyInProgress("idempotent command is still in progress")
    return _stored_response_from_row(row)


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _scope_predicate(columns: Any, scope: IdempotencyScope) -> Any:
    return (
        (columns.actor_id == scope.actor_id)
        & (columns.operation == scope.operation)
        & (columns.resource_namespace == scope.resource_namespace)
        & (columns.idempotency_key == scope.key)
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database command time must be timezone-aware")
