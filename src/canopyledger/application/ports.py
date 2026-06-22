"""Persistence ports consumed by integrity application services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from canopyledger.integrity.bundles import VersionBundle
from canopyledger.integrity.idempotency import IdempotencyScope, StoredResponse

from .models import (
    AuditEventData,
    FacilityState,
    InboxResult,
    OutboxMessageData,
    PublishedStage,
    SnapshotData,
    StageLease,
    StagePublicationData,
)


class IntegrityTransaction(Protocol):
    def insert_facility(self, facility: FacilityState) -> None: ...

    def get_facility_for_update(self, resource_id: str) -> FacilityState | None: ...

    def update_facility(self, facility: FacilityState, *, expected_version: int) -> None: ...

    def append_audit_event(self, event: AuditEventData) -> None: ...

    def get_bundle(self, resource_id: str) -> VersionBundle | None: ...

    def find_snapshot_id(self, facility_id: str, working_version: int) -> str | None: ...

    def insert_snapshot(self, snapshot: SnapshotData) -> None: ...

    def insert_outbox_message(self, message: OutboxMessageData) -> None: ...


class IntegrityStore(Protocol):
    def claim_stage(
        self,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
        maximum_lease_lifetime: timedelta,
        attempt_id: str,
    ) -> StageLease | None: ...

    def heartbeat_stage(
        self,
        stage_id: str,
        worker_id: str,
        epoch: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> StageLease: ...

    def publish_stage(self, publication: StagePublicationData) -> PublishedStage: ...

    def record_inbox(
        self,
        consumer: str,
        message_id: str,
        message_digest: str,
        outcome: bytes,
        now: datetime,
    ) -> InboxResult: ...

    def execute_idempotent(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]: ...

    def execute_serializable_idempotent(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]: ...
