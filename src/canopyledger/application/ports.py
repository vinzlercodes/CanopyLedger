"""Persistence ports consumed by integrity application services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from canopyledger.integrity.bundles import VersionBundle
from canopyledger.integrity.idempotency import IdempotencyScope, StoredResponse

from .models import AuditEventData, FacilityState, OutboxMessageData, SnapshotData


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
