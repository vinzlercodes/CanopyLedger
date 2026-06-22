"""Application services for facility commands and M1A integrity operations."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.idempotency import (
    IdempotencyScope,
    StoredResponse,
    request_fingerprint,
)

from .models import (
    AuditEventData,
    CommandResponse,
    CreateFacilityCommand,
    FacilityState,
    UpdateFacilityCommand,
)
from .ports import IntegrityStore, IntegrityTransaction

__all__ = [
    "CreateFacilityCommand",
    "IntegrityService",
    "PreconditionFailed",
    "UpdateFacilityCommand",
]


class FacilityCommandError(ValueError):
    """Base error for facility application commands."""


class FacilityNotFound(FacilityCommandError):
    """Raised when a facility is outside the visible resource set."""


class PreconditionFailed(FacilityCommandError):
    """Raised when a strong facility ETag does not match current state."""


class IntegrityService:
    def __init__(
        self,
        store: IntegrityStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def create_facility(self, command: CreateFacilityCommand) -> CommandResponse:
        _validate_create(command)
        now = self._clock()
        scope = IdempotencyScope(
            command.actor_id,
            "create_facility",
            "facilities",
            command.idempotency_key,
        )
        fingerprint = request_fingerprint(
            method="POST",
            path="/api/v1/facilities",
            schema_version="facility-create-v1",
            body={
                "currency": command.currency,
                "facility_commitment": command.facility_commitment,
                "legal_name": command.legal_name,
            },
        )

        def execute(transaction: IntegrityTransaction) -> StoredResponse:
            facility = FacilityState(
                resource_id=self._id_factory("fac"),
                legal_name=command.legal_name,
                currency=command.currency,
                facility_commitment=command.facility_commitment,
                version=1,
                created_at=now,
                updated_at=now,
            )
            transaction.insert_facility(facility)
            representation = _facility_representation(facility)
            digest = _facility_digest(representation)
            transaction.append_audit_event(
                AuditEventData(
                    event_id=self._id_factory("aud"),
                    actor_id=command.actor_id,
                    action="facility.create",
                    resource_type="facility_working_state",
                    resource_id=facility.resource_id,
                    correlation_id=command.correlation_id,
                    causation_id=None,
                    before_digest=None,
                    after_digest=digest,
                    reason=None,
                    metadata={},
                    occurred_at=now,
                )
            )
            return StoredResponse(
                201,
                {
                    "ETag": _facility_etag(facility, digest),
                    "Location": f"/api/v1/facilities/{facility.resource_id}",
                },
                json.dumps(representation, separators=(",", ":")).encode(),
            )

        stored, replayed = self._store.execute_idempotent(scope, fingerprint, now, execute)
        return CommandResponse(stored.status, stored.headers, stored.body, replayed)

    def update_facility(self, command: UpdateFacilityCommand) -> CommandResponse:
        _validate_update(command)
        now = self._clock()
        scope = IdempotencyScope(
            command.actor_id,
            "update_facility",
            command.facility_id,
            command.idempotency_key,
        )
        fingerprint = request_fingerprint(
            method="PATCH",
            path=f"/api/v1/facilities/{command.facility_id}",
            schema_version="facility-update-v1",
            body={"legal_name": command.legal_name, "reason": command.reason},
            relevant_headers={"if-match": command.if_match},
        )

        def execute(transaction: IntegrityTransaction) -> StoredResponse:
            current = transaction.get_facility_for_update(command.facility_id)
            if current is None:
                raise FacilityNotFound("facility not found")
            before_representation = _facility_representation(current)
            before_digest = _facility_digest(before_representation)
            if command.if_match != _facility_etag(current, before_digest):
                raise PreconditionFailed("strong ETag does not match")
            updated = replace(
                current,
                legal_name=command.legal_name,
                version=current.version + 1,
                updated_at=now,
            )
            transaction.update_facility(updated, expected_version=current.version)
            representation = _facility_representation(updated)
            after_digest = _facility_digest(representation)
            transaction.append_audit_event(
                AuditEventData(
                    event_id=self._id_factory("aud"),
                    actor_id=command.actor_id,
                    action="facility.update",
                    resource_type="facility_working_state",
                    resource_id=updated.resource_id,
                    correlation_id=command.correlation_id,
                    causation_id=None,
                    before_digest=before_digest,
                    after_digest=after_digest,
                    reason=command.reason,
                    metadata={},
                    occurred_at=now,
                )
            )
            return StoredResponse(
                200,
                {"ETag": _facility_etag(updated, after_digest)},
                json.dumps(representation, separators=(",", ":")).encode(),
            )

        stored, replayed = self._store.execute_idempotent(scope, fingerprint, now, execute)
        return CommandResponse(stored.status, stored.headers, stored.body, replayed)


def _validate_create(command: CreateFacilityCommand) -> None:
    if not 1 <= len(command.legal_name) <= 200:
        raise FacilityCommandError("legal name length is invalid")
    if re.fullmatch(r"[A-Z]{3}", command.currency) is None:
        raise FacilityCommandError("currency must be an uppercase ISO-style code")
    try:
        commitment = Decimal(command.facility_commitment)
        quantized = commitment.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise FacilityCommandError("facility commitment is invalid") from exc
    if not commitment.is_finite() or commitment <= 0 or quantized != commitment:
        raise FacilityCommandError("facility commitment must be positive with at most two decimals")


def _validate_update(command: UpdateFacilityCommand) -> None:
    if not 1 <= len(command.legal_name) <= 200:
        raise FacilityCommandError("legal name length is invalid")
    if not 3 <= len(command.reason) <= 500:
        raise FacilityCommandError("update reason length is invalid")
    if not command.if_match:
        raise FacilityCommandError("If-Match is required")


def _facility_representation(facility: FacilityState) -> dict[str, str | int]:
    return {
        "id": facility.resource_id,
        "legal_name": facility.legal_name,
        "currency": facility.currency,
        "facility_commitment": facility.facility_commitment,
        "version": facility.version,
    }


def _facility_digest(representation: dict[str, str | int]) -> str:
    return domain_digest("facility", 1, canonical_json_bytes(representation))


def _facility_etag(facility: FacilityState, digest: str) -> str:
    return f'"facility:{facility.resource_id}:v{facility.version}:{digest[7:]}"'
