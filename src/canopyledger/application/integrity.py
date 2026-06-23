"""Application services for facility commands and M1A integrity operations."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.canonical import (
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)
from canopyledger.integrity.idempotency import (
    IdempotencyScope,
    StoredResponse,
    request_fingerprint,
)
from canopyledger.integrity.replay import ReplayResult, verify_replay
from canopyledger.integrity.snapshot import BundleReference, SnapshotManifest

from .models import (
    AuditEventData,
    CommandResponse,
    CreateFacilityCommand,
    FacilityState,
    FreezeFacilityCommand,
    InboxResult,
    OutboxMessageData,
    PublishedStage,
    SnapshotData,
    StageLease,
    StagePublicationData,
    UpdateFacilityCommand,
)
from .ports import IntegrityStore, IntegrityTransaction

__all__ = [
    "CreateFacilityCommand",
    "FreezeFacilityCommand",
    "IntegrityService",
    "PreconditionFailed",
    "SnapshotAlreadyFrozen",
    "UpdateFacilityCommand",
]


class FacilityCommandError(ValueError):
    """Base error for facility application commands."""


class FacilityNotFound(FacilityCommandError):
    """Raised when a facility is outside the visible resource set."""


class PreconditionFailed(FacilityCommandError):
    """Raised when a strong facility ETag does not match current state."""


class BundleReferenceRejected(FacilityCommandError):
    """Raised when a freeze bundle ID, digest, or type is not approved and immutable."""


class SnapshotAlreadyFrozen(FacilityCommandError):
    """Raised when a working facility version already has an immutable snapshot."""


class OutputSchemaRejected(FacilityCommandError):
    """Raised when a stage output does not match a registered versioned schema."""


class InboxDigestConflict(FacilityCommandError):
    """Raised when a delivered message ID is reused with different content."""


class IntegrityService:
    def __init__(
        self,
        store: IntegrityStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] = new_resource_id,
        output_schema_validators: Mapping[str, Callable[[object], bool]] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory
        self._output_schema_validators = dict(output_schema_validators or {})

    def verify_snapshot_replay(
        self,
        *,
        snapshot_id: str,
        declared_environment: dict[str, str],
        current_environment: dict[str, str],
        actor_id: str,
        correlation_id: str,
    ) -> ReplayResult:
        package = self._store.load_replay_package(snapshot_id, declared_environment)
        result = verify_replay(package, current_environment=current_environment)
        self._store.append_replay_audit(
            result,
            actor_id,
            correlation_id,
            self._id_factory("aud"),
            self._clock(),
        )
        return result

    def claim_stage(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
        maximum_lease_lifetime: timedelta,
    ) -> StageLease | None:
        if not worker_id or lease_duration <= timedelta(0):
            raise FacilityCommandError("worker and positive lease duration are required")
        if maximum_lease_lifetime < lease_duration:
            raise FacilityCommandError("maximum lease lifetime cannot be shorter than lease")
        return self._store.claim_stage(
            worker_id,
            now,
            lease_duration,
            maximum_lease_lifetime,
            self._id_factory("att"),
        )

    def heartbeat(
        self,
        *,
        stage_id: str,
        worker_id: str,
        epoch: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> StageLease:
        return self._store.heartbeat_stage(stage_id, worker_id, epoch, now, lease_duration)

    def publish_stage(
        self,
        *,
        stage_id: str,
        worker_id: str,
        epoch: int,
        input_digest: str,
        output_schema_version: str,
        output: object,
        now: datetime,
    ) -> PublishedStage:
        validator = self._output_schema_validators.get(output_schema_version)
        if validator is None or not validator(output):
            raise OutputSchemaRejected("stage output schema is unknown or invalid")
        canonical_output = canonical_json_bytes(output)
        return self._store.publish_stage(
            StagePublicationData(
                stage_id=stage_id,
                worker_id=worker_id,
                epoch=epoch,
                input_digest=input_digest,
                output_schema_version=output_schema_version,
                canonical_output=canonical_output,
                output_digest=domain_digest("pipeline_stage_output", 1, canonical_output),
                output_id=self._id_factory("out"),
                outbox_message_id=self._id_factory("msg"),
                audit_event_id=self._id_factory("aud"),
                published_at=now,
            )
        )

    def record_inbox(
        self,
        *,
        consumer: str,
        message_id: str,
        message_digest: str,
        outcome: bytes,
        now: datetime,
    ) -> InboxResult:
        return self._store.record_inbox(consumer, message_id, message_digest, outcome, now)

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

    def freeze_facility(self, command: FreezeFacilityCommand) -> CommandResponse:
        _validate_freeze(command)
        now = self._clock()
        scope = IdempotencyScope(
            command.actor_id,
            "freeze_facility",
            command.facility_id,
            command.idempotency_key,
        )
        fingerprint = request_fingerprint(
            method="POST",
            path=f"/api/v1/facilities/{command.facility_id}/snapshots",
            schema_version="facility-freeze-v1",
            body={
                "as_of": canonical_timestamp(command.as_of),
                "market_bundle": command.market_bundle.model_dump(),
                "policy_bundle": command.policy_bundle.model_dump(),
                "legal_interpretation_bundle": command.legal_interpretation_bundle.model_dump(),
                "computation_bundle": command.computation_bundle.model_dump(),
                "inputs": [item.model_dump() for item in command.inputs],
            },
            relevant_headers={"if-match": command.if_match},
        )

        def execute(transaction: IntegrityTransaction) -> StoredResponse:
            facility = transaction.get_facility_for_update(command.facility_id)
            if facility is None:
                raise FacilityNotFound("facility not found")
            facility_representation = _facility_representation(facility)
            facility_digest = _facility_digest(facility_representation)
            if command.if_match != _facility_etag(facility, facility_digest):
                raise PreconditionFailed("strong ETag does not match")
            existing_snapshot = transaction.find_snapshot_id(command.facility_id, facility.version)
            if existing_snapshot is not None:
                raise SnapshotAlreadyFrozen(
                    f"facility version already frozen as {existing_snapshot}"
                )
            _require_bundle(
                transaction,
                command.market_bundle,
                BundleType.MARKET,
            )
            _require_bundle(
                transaction,
                command.policy_bundle,
                BundleType.POLICY,
            )
            _require_bundle(
                transaction,
                command.legal_interpretation_bundle,
                BundleType.LEGAL_INTERPRETATION,
            )
            _require_bundle(
                transaction,
                command.computation_bundle,
                BundleType.COMPUTATION,
            )
            manifest = SnapshotManifest(
                snapshot_id=self._id_factory("snp"),
                facility_id=facility.resource_id,
                facility_working_version=facility.version,
                schema_version="1.0",
                as_of=command.as_of,
                market_bundle=command.market_bundle,
                policy_bundle=command.policy_bundle,
                legal_interpretation_bundle=command.legal_interpretation_bundle,
                computation_bundle=command.computation_bundle,
                inputs=command.inputs,
                created_by=command.actor_id,
                created_at=now,
            )
            transaction.insert_snapshot(
                SnapshotData(
                    manifest=manifest,
                    legal_name=facility.legal_name,
                    currency=facility.currency,
                    facility_commitment=facility.facility_commitment,
                )
            )
            outbox_payload = canonical_json_bytes(
                {
                    "event_type": "pipeline.start",
                    "snapshot_digest": manifest.digest,
                    "snapshot_id": manifest.snapshot_id,
                }
            )
            transaction.insert_outbox_message(
                OutboxMessageData(
                    message_id=self._id_factory("msg"),
                    topic="pipeline.start",
                    message_key=f"{facility.resource_id}:{facility.version}",
                    payload=outbox_payload,
                    payload_digest=domain_digest("outbox_message", 1, outbox_payload),
                    created_at=now,
                    available_at=now,
                )
            )
            transaction.append_audit_event(
                AuditEventData(
                    event_id=self._id_factory("aud"),
                    actor_id=command.actor_id,
                    action="snapshot.freeze",
                    resource_type="facility_snapshot",
                    resource_id=manifest.snapshot_id,
                    correlation_id=command.correlation_id,
                    causation_id=None,
                    before_digest=facility_digest,
                    after_digest=manifest.digest,
                    reason=None,
                    metadata={"facility_id": facility.resource_id},
                    occurred_at=now,
                )
            )
            representation = _snapshot_representation(manifest)
            return StoredResponse(
                201,
                {
                    "ETag": f'"snapshot:{manifest.snapshot_id}:{manifest.digest[7:]}"',
                    "Location": f"/api/v1/snapshots/{manifest.snapshot_id}",
                },
                json.dumps(representation, separators=(",", ":")).encode(),
            )

        stored, replayed = self._store.execute_serializable_idempotent(
            scope, fingerprint, now, execute
        )
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


def _validate_freeze(command: FreezeFacilityCommand) -> None:
    if not command.if_match:
        raise FacilityCommandError("If-Match is required")
    if command.as_of.tzinfo is None or command.as_of.utcoffset() is None:
        raise FacilityCommandError("snapshot as-of time must be timezone-aware")


def _require_bundle(
    transaction: IntegrityTransaction,
    reference: BundleReference,
    expected_type: BundleType,
) -> VersionBundle:
    bundle = transaction.get_bundle(reference.resource_id)
    if (
        bundle is None
        or bundle.bundle_type is not expected_type
        or bundle.digest != reference.digest
    ):
        raise BundleReferenceRejected(
            f"snapshot requires an immutable {expected_type.value} bundle with matching digest"
        )
    return bundle


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


def _snapshot_representation(manifest: SnapshotManifest) -> dict[str, object]:
    return {
        "snapshot_id": manifest.snapshot_id,
        "facility_id": manifest.facility_id,
        "facility_working_version": manifest.facility_working_version,
        "schema_version": manifest.schema_version,
        "as_of": canonical_timestamp(manifest.as_of),
        "market_bundle": manifest.market_bundle.model_dump(),
        "policy_bundle": manifest.policy_bundle.model_dump(),
        "legal_interpretation_bundle": manifest.legal_interpretation_bundle.model_dump(),
        "computation_bundle": manifest.computation_bundle.model_dump(),
        "inputs": [item.model_dump() for item in manifest.inputs],
        "created_by": manifest.created_by,
        "created_at": canonical_timestamp(manifest.created_at),
        "digest": manifest.digest,
    }
