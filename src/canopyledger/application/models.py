"""Application command, state, and result records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from canopyledger.integrity.snapshot import (
    BundleReference,
    SnapshotInputReference,
    SnapshotManifest,
)


@dataclass(frozen=True)
class FacilityState:
    resource_id: str
    legal_name: str
    currency: str
    facility_commitment: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuditEventData:
    event_id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    correlation_id: str
    causation_id: str | None
    before_digest: str | None
    after_digest: str | None
    reason: str | None
    metadata: Mapping[str, object]
    occurred_at: datetime


@dataclass(frozen=True)
class CommandResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    replayed: bool = False


@dataclass(frozen=True)
class CreateFacilityCommand:
    actor_id: str
    idempotency_key: str
    legal_name: str
    currency: str
    facility_commitment: str
    correlation_id: str


@dataclass(frozen=True)
class UpdateFacilityCommand:
    actor_id: str
    facility_id: str
    idempotency_key: str
    if_match: str
    legal_name: str
    reason: str
    correlation_id: str


@dataclass(frozen=True)
class FreezeFacilityCommand:
    actor_id: str
    facility_id: str
    idempotency_key: str
    if_match: str
    as_of: datetime
    market_bundle: BundleReference
    policy_bundle: BundleReference
    legal_interpretation_bundle: BundleReference
    computation_bundle: BundleReference
    inputs: tuple[SnapshotInputReference, ...]
    correlation_id: str


@dataclass(frozen=True)
class SnapshotData:
    manifest: SnapshotManifest
    legal_name: str
    currency: str
    facility_commitment: str


@dataclass(frozen=True)
class OutboxMessageData:
    message_id: str
    topic: str
    message_key: str
    payload: bytes
    payload_digest: str
    created_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class StageLease:
    stage_id: str
    attempt_id: str
    worker_id: str
    epoch: int
    input_digest: str
    lease_expires_at: datetime
    maximum_lease_expires_at: datetime


@dataclass(frozen=True)
class StagePublicationData:
    stage_id: str
    worker_id: str
    epoch: int
    input_digest: str
    output_schema_version: str
    canonical_output: bytes
    output_digest: str
    output_id: str
    outbox_message_id: str
    audit_event_id: str
    published_at: datetime


@dataclass(frozen=True)
class PublishedStage:
    output_id: str
    publication_key: str
    output_digest: str


@dataclass(frozen=True)
class InboxResult:
    outcome: bytes
    replayed: bool
