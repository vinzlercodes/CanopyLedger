"""Application command, state, and result records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


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
