"""PostgreSQL adapters for M1A integrity resources."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from canopyledger.application.evidence import (
    OwnershipClaimRecord,
    WarehouseReceiptRecord,
)
from canopyledger.application.integrity import (
    InboxDigestConflict,
    SnapshotAlreadyFrozen,
)
from canopyledger.application.models import (
    AuditEventData,
    FacilityState,
    InboxResult,
    OutboxMessageData,
    PublishedStage,
    SnapshotData,
    StageLease,
    StagePublicationData,
)
from canopyledger.application.ports import IntegrityTransaction
from canopyledger.evidence.controls import (
    ApprovedFact,
    CandidateFact,
    DocumentVersion,
    DuplicateWarehouseReceipt,
    EvidenceControlError,
    FactIdentity,
    InventoryOwnershipClaim,
    OwnershipConflict,
    QuantityReconciliationIssue,
    RejectedFact,
    WarehouseReceiptEvidence,
)
from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.idempotency import (
    IdempotencyConflict,
    IdempotencyScope,
    StoredResponse,
)
from canopyledger.integrity.pipeline import FencedPublication
from canopyledger.integrity.replay import ReplayArtifact, ReplayPackage, ReplayResult
from canopyledger.integrity.snapshot import (
    BundleReference,
    SnapshotInputReference,
    SnapshotManifest,
)

from .schema import (
    approved_fact,
    audit_event,
    candidate_fact,
    evidence_document,
    evidence_document_version,
    facility_snapshot,
    facility_working_state,
    idempotency_record,
    idempotency_tombstone,
    inbox_receipt,
    inventory_ownership_claim,
    outbox_message,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_attempt,
    pipeline_stage_output,
    quantity_reconciliation_issue,
    rejected_fact,
    snapshot_input_reference,
    warehouse_receipt_evidence,
)
from .schema import (
    bundle as bundle_table,
)


class ImmutableBundleConflict(ValueError):
    """Raised when publication would give a bundle ID new content."""


class IdempotencyInProgress(IdempotencyConflict):
    """Raised when a visible command claim has not completed."""


class RetryableSerializationConflict(RuntimeError):
    """Explicit SQLSTATE 40001 equivalent used by retry instrumentation and tests."""

    sqlstate = "40001"


class SerializationRetryExhausted(RuntimeError):
    """Raised when bounded serializable retries cannot obtain a commit."""


class PostgresEvidenceStore:
    """PostgreSQL adapter for M2 evidence review resources."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def insert_document_version(
        self, document: DocumentVersion, *, original_bytes: bytes
    ) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    postgres_insert(evidence_document)
                    .values(
                        resource_id=document.document_id,
                        created_by=document.created_by,
                        created_at=document.created_at,
                    )
                    .on_conflict_do_nothing(index_elements=[evidence_document.c.resource_id])
                )
                connection.execute(
                    insert(evidence_document_version).values(
                        resource_id=document.resource_id,
                        document_id=document.document_id,
                        version=document.version,
                        filename=document.filename,
                        content_type=document.content_type,
                        original_bytes=original_bytes,
                        byte_digest=document.byte_digest,
                        size_bytes=document.size_bytes,
                        object_key=f"evidence/{document.resource_id}",
                        created_by=document.created_by,
                        created_at=document.created_at,
                    )
                )
        except IntegrityError as exc:
            existing = self.get_document_version(document.resource_id)
            if existing == document:
                return
            raise EvidenceControlError(
                "document version already exists with different content"
            ) from exc

    def get_document_version(self, document_version_id: str) -> DocumentVersion | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(evidence_document_version).where(
                        evidence_document_version.c.resource_id == document_version_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _document_version_from_row(row)

    def insert_candidate_fact(self, candidate: CandidateFact) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(candidate_fact).values(
                        resource_id=candidate.fact_id,
                        fact_type=candidate.identity.fact_type,
                        subject_id=candidate.identity.subject_id,
                        period=candidate.identity.period,
                        value=candidate.value,
                        document_version_id=candidate.document_version_id,
                        document_byte_digest=candidate.document_byte_digest,
                        page_region=candidate.page_region or "",
                        extraction_method=candidate.extraction_method or "",
                        extractor_version=candidate.extractor_version or "",
                        raw_value=candidate.raw_value or "",
                        normalized_value=candidate.normalized_value or "",
                        extracted_at=candidate.extracted_at,
                    )
                )
        except IntegrityError as exc:
            existing = self.get_candidate_fact(candidate.fact_id)
            if existing == candidate:
                return
            raise EvidenceControlError(
                "candidate fact already exists with different content"
            ) from exc

    def get_candidate_fact(self, candidate_fact_id: str) -> CandidateFact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(candidate_fact).where(candidate_fact.c.resource_id == candidate_fact_id)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _candidate_fact_from_row(row)

    def get_approved_fact_for_candidate(self, candidate_fact_id: str) -> ApprovedFact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(approved_fact).where(
                        approved_fact.c.candidate_fact_id == candidate_fact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _approved_fact_from_row(row)

    def get_rejected_fact_for_candidate(self, candidate_fact_id: str) -> RejectedFact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(rejected_fact).where(
                        rejected_fact.c.candidate_fact_id == candidate_fact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _rejected_fact_from_row(row)

    def get_active_approved_fact(self, identity: FactIdentity) -> ApprovedFact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(approved_fact).where(
                        approved_fact.c.fact_type == identity.fact_type,
                        approved_fact.c.subject_id == identity.subject_id,
                        approved_fact.c.period == identity.period,
                        approved_fact.c.superseded_by.is_(None),
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _approved_fact_from_row(row)

    def get_approved_fact(self, approved_fact_id: str) -> ApprovedFact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(approved_fact).where(
                        approved_fact.c.resource_id == approved_fact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _approved_fact_from_row(row)

    def list_approved_facts_for_identity(
        self, identity: FactIdentity
    ) -> tuple[ApprovedFact, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(approved_fact)
                    .where(
                        approved_fact.c.fact_type == identity.fact_type,
                        approved_fact.c.subject_id == identity.subject_id,
                        approved_fact.c.period == identity.period,
                    )
                    .order_by(approved_fact.c.approved_at, approved_fact.c.resource_id)
                )
                .mappings()
                .all()
            )
        return tuple(_approved_fact_from_row(row) for row in rows)

    def insert_approved_fact(self, approved: ApprovedFact) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(approved_fact).values(
                        resource_id=approved.fact_id,
                        candidate_fact_id=approved.candidate_fact_id,
                        fact_type=approved.identity.fact_type,
                        subject_id=approved.identity.subject_id,
                        period=approved.identity.period,
                        value=approved.value,
                        document_version_id=approved.document_version_id,
                        document_byte_digest=approved.document_byte_digest,
                        approved_by=approved.approved_by,
                        approved_at=approved.approved_at,
                        superseded_by=approved.superseded_by,
                    )
                )
        except IntegrityError as exc:
            raise EvidenceControlError("approved fact conflicts with existing evidence") from exc

    def supersede_approved_fact(
        self, *, superseded: ApprovedFact, replacement: ApprovedFact
    ) -> None:
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    update(approved_fact)
                    .where(
                        approved_fact.c.resource_id == superseded.fact_id,
                        approved_fact.c.superseded_by.is_(None),
                    )
                    .values(superseded_by=replacement.fact_id)
                )
                if result.rowcount != 1:
                    raise EvidenceControlError("approved fact changed before supersession")
                connection.execute(
                    insert(approved_fact).values(
                        resource_id=replacement.fact_id,
                        candidate_fact_id=replacement.candidate_fact_id,
                        fact_type=replacement.identity.fact_type,
                        subject_id=replacement.identity.subject_id,
                        period=replacement.identity.period,
                        value=replacement.value,
                        document_version_id=replacement.document_version_id,
                        document_byte_digest=replacement.document_byte_digest,
                        approved_by=replacement.approved_by,
                        approved_at=replacement.approved_at,
                        superseded_by=replacement.superseded_by,
                    )
                )
        except IntegrityError as exc:
            raise EvidenceControlError("approved fact conflicts with existing evidence") from exc

    def insert_rejected_fact(self, rejected: RejectedFact) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(rejected_fact).values(
                        resource_id=rejected.fact_id,
                        candidate_fact_id=rejected.candidate_fact_id,
                        fact_type=rejected.identity.fact_type,
                        subject_id=rejected.identity.subject_id,
                        period=rejected.identity.period,
                        rejected_by=rejected.rejected_by,
                        rejected_at=rejected.rejected_at,
                        reason=rejected.reason,
                    )
                )
        except IntegrityError as exc:
            raise EvidenceControlError("rejected fact conflicts with existing evidence") from exc

    def get_warehouse_receipt(
        self, *, warehouse_id: str, receipt_number: str
    ) -> WarehouseReceiptRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(warehouse_receipt_evidence).where(
                        warehouse_receipt_evidence.c.warehouse_id == warehouse_id,
                        warehouse_receipt_evidence.c.receipt_number == receipt_number,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _warehouse_receipt_from_row(row)

    def insert_warehouse_receipt(
        self, *, resource_id: str, receipt: WarehouseReceiptEvidence
    ) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(warehouse_receipt_evidence).values(
                        resource_id=resource_id,
                        receipt_number=receipt.receipt_number,
                        warehouse_id=receipt.warehouse_id,
                        lot_id=receipt.lot_id,
                        quantity=receipt.quantity,
                        approved_fact_id=receipt.approved_fact_id,
                    )
                )
        except IntegrityError as exc:
            existing = self.get_warehouse_receipt(
                warehouse_id=receipt.warehouse_id,
                receipt_number=receipt.receipt_number,
            )
            if existing is not None and existing.receipt == receipt:
                return
            raise DuplicateWarehouseReceipt(
                "warehouse receipt number already has approved evidence"
            ) from exc

    def list_warehouse_receipts_for_lot(
        self, lot_id: str
    ) -> tuple[WarehouseReceiptRecord, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(warehouse_receipt_evidence)
                    .where(warehouse_receipt_evidence.c.lot_id == lot_id)
                    .order_by(warehouse_receipt_evidence.c.resource_id)
                )
                .mappings()
                .all()
            )
        return tuple(_warehouse_receipt_from_row(row) for row in rows)

    def get_ownership_claim(
        self, *, lot_id: str, period: str
    ) -> OwnershipClaimRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(inventory_ownership_claim).where(
                        inventory_ownership_claim.c.lot_id == lot_id,
                        inventory_ownership_claim.c.period == period,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _ownership_claim_from_row(row)

    def insert_ownership_claim(
        self, *, resource_id: str, claim: InventoryOwnershipClaim
    ) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(inventory_ownership_claim).values(
                        resource_id=resource_id,
                        lot_id=claim.lot_id,
                        period=claim.period,
                        owner_party_id=claim.owner_party_id,
                        pledgee_id=claim.pledgee_id,
                        approved_fact_id=claim.approved_fact_id,
                    )
                )
        except IntegrityError as exc:
            existing = self.get_ownership_claim(lot_id=claim.lot_id, period=claim.period)
            if existing is not None and existing.claim == claim:
                return
            raise OwnershipConflict(
                "lot already has conflicting ownership or pledge evidence"
            ) from exc

    def insert_quantity_reconciliation_issue(
        self,
        *,
        resource_id: str,
        issue: QuantityReconciliationIssue,
        detected_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                insert(quantity_reconciliation_issue).values(
                    resource_id=resource_id,
                    lot_id=issue.lot_id,
                    expected_quantity=issue.expected_quantity,
                    receipt_quantity=issue.receipt_quantity,
                    difference=issue.difference,
                    detected_at=detected_at,
                )
            )


class PostgresIntegrityStore:
    """Explicit transactional adapter for durable integrity resources."""

    def __init__(
        self,
        engine: Engine,
        *,
        serializable_attempt_hook: Callable[[int], None] | None = None,
        before_serializable_commit: Callable[[], None] | None = None,
        serialization_attempts: int = 3,
    ) -> None:
        if serialization_attempts < 1:
            raise ValueError("serialization attempts must be positive")
        self._engine = engine
        self._serializable_attempt_hook = serializable_attempt_hook
        self._before_serializable_commit = before_serializable_commit
        self._serialization_attempts = serialization_attempts

    def get_facility(self, resource_id: str) -> FacilityState | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(facility_working_state).where(
                        facility_working_state.c.resource_id == resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _facility_from_row(row)

    def get_snapshot_manifest(self, snapshot_id: str) -> SnapshotData | None:
        with self._engine.connect() as connection:
            snapshot = (
                connection.execute(
                    select(facility_snapshot).where(facility_snapshot.c.resource_id == snapshot_id)
                )
                .mappings()
                .one_or_none()
            )
            if snapshot is None:
                return None
            inputs = (
                connection.execute(
                    select(snapshot_input_reference)
                    .where(snapshot_input_reference.c.snapshot_id == snapshot_id)
                    .order_by(snapshot_input_reference.c.position)
                )
                .mappings()
                .all()
            )
        return SnapshotData(
            manifest=_reconstruct_snapshot_manifest(snapshot, inputs),
            legal_name=snapshot["legal_name"],
            currency=snapshot["currency"],
            facility_commitment=snapshot["facility_commitment"],
        )

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
            row = (
                connection.execute(
                    select(bundle_table).where(bundle_table.c.resource_id == resource_id)
                )
                .mappings()
                .one_or_none()
            )
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
            record = (
                connection.execute(
                    select(idempotency_record)
                    .where(_scope_predicate(idempotency_record.c, scope))
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            return _replay_record(record, fingerprint), True

    def _execute_idempotent_once(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]:
        with self._engine.begin() as connection:
            return self._execute_idempotent_in_transaction(
                connection, scope, fingerprint, now, command
            )

    def _execute_idempotent_in_transaction(
        self,
        connection: Connection,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]:
        tombstone = connection.execute(
            select(idempotency_tombstone.c.fingerprint).where(
                _scope_predicate(idempotency_tombstone.c, scope)
            )
        ).scalar_one_or_none()
        if tombstone is not None:
            raise IdempotencyConflict("idempotency key has an expired tombstone")

        record = (
            connection.execute(
                select(idempotency_record)
                .where(_scope_predicate(idempotency_record.c, scope))
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
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

    def execute_serializable_idempotent(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        now: datetime,
        command: Callable[[IntegrityTransaction], StoredResponse],
    ) -> tuple[StoredResponse, bool]:
        _require_aware(now)
        last_error: BaseException | None = None
        for attempt in range(1, self._serialization_attempts + 1):
            try:
                if self._serializable_attempt_hook is not None:
                    self._serializable_attempt_hook(attempt)
                with (
                    self._engine.connect().execution_options(
                        isolation_level="SERIALIZABLE"
                    ) as connection,
                    connection.begin(),
                ):
                    result = self._execute_idempotent_in_transaction(
                        connection, scope, fingerprint, now, command
                    )
                    if self._before_serializable_commit is not None:
                        self._before_serializable_commit()
                    return result
            except IntegrityError as exc:
                if _constraint_name(exc) == "pk_idempotency_record":
                    return self._replay_committed(scope, fingerprint)
                if not _is_serialization_failure(exc):
                    raise
                last_error = exc
            except BaseException as exc:
                if not _is_serialization_failure(exc):
                    raise
                last_error = exc
        raise SerializationRetryExhausted(
            f"serializable transaction failed after {self._serialization_attempts} attempts"
        ) from last_error

    def _replay_committed(
        self, scope: IdempotencyScope, fingerprint: str
    ) -> tuple[StoredResponse, bool]:
        with self._engine.begin() as connection:
            record = (
                connection.execute(
                    select(idempotency_record)
                    .where(_scope_predicate(idempotency_record.c, scope))
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            return _replay_record(record, fingerprint), True

    def claim_stage(
        self,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
        maximum_lease_lifetime: timedelta,
        attempt_id: str,
    ) -> StageLease | None:
        _require_aware(now)
        with self._engine.begin() as connection:
            eligible = (
                select(pipeline_stage.c.resource_id)
                .where(
                    or_(
                        pipeline_stage.c.status == "PENDING",
                        (
                            (pipeline_stage.c.status == "RUNNING")
                            & (pipeline_stage.c.lease_expires_at <= now)
                        ),
                    )
                )
                .order_by(pipeline_stage.c.created_at, pipeline_stage.c.resource_id)
                .limit(1)
                .with_for_update(skip_locked=True)
                .cte("eligible_stage")
            )
            row = (
                connection.execute(
                    update(pipeline_stage)
                    .where(pipeline_stage.c.resource_id == eligible.c.resource_id)
                    .values(
                        status="RUNNING",
                        lease_epoch=pipeline_stage.c.lease_epoch + 1,
                        worker_id=worker_id,
                        lease_started_at=now,
                        lease_expires_at=now + lease_duration,
                        maximum_lease_expires_at=now + maximum_lease_lifetime,
                        updated_at=now,
                    )
                    .returning(
                        pipeline_stage.c.resource_id,
                        pipeline_stage.c.lease_epoch,
                        pipeline_stage.c.input_digest,
                        pipeline_stage.c.lease_expires_at,
                        pipeline_stage.c.maximum_lease_expires_at,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            connection.execute(
                insert(pipeline_stage_attempt).values(
                    resource_id=attempt_id,
                    pipeline_stage_id=row["resource_id"],
                    lease_epoch=row["lease_epoch"],
                    worker_id=worker_id,
                    started_at=now,
                    heartbeat_at=now,
                )
            )
            return _lease_from_row(row, attempt_id, worker_id)

    def heartbeat_stage(
        self,
        stage_id: str,
        worker_id: str,
        epoch: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> StageLease:
        _require_aware(now)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    update(pipeline_stage)
                    .where(
                        pipeline_stage.c.resource_id == stage_id,
                        pipeline_stage.c.status == "RUNNING",
                        pipeline_stage.c.worker_id == worker_id,
                        pipeline_stage.c.lease_epoch == epoch,
                        pipeline_stage.c.lease_expires_at > now,
                        pipeline_stage.c.maximum_lease_expires_at > now,
                    )
                    .values(
                        lease_expires_at=func.least(
                            now + lease_duration,
                            pipeline_stage.c.maximum_lease_expires_at,
                        ),
                        updated_at=now,
                    )
                    .returning(
                        pipeline_stage.c.resource_id,
                        pipeline_stage.c.lease_epoch,
                        pipeline_stage.c.input_digest,
                        pipeline_stage.c.lease_expires_at,
                        pipeline_stage.c.maximum_lease_expires_at,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise FencedPublication("heartbeat lease authority is stale or expired")
            attempt_id = connection.execute(
                update(pipeline_stage_attempt)
                .where(
                    pipeline_stage_attempt.c.pipeline_stage_id == stage_id,
                    pipeline_stage_attempt.c.lease_epoch == epoch,
                    pipeline_stage_attempt.c.worker_id == worker_id,
                    pipeline_stage_attempt.c.finished_at.is_(None),
                )
                .values(heartbeat_at=now)
                .returning(pipeline_stage_attempt.c.resource_id)
            ).scalar_one()
            return _lease_from_row(row, attempt_id, worker_id)

    def publish_stage(self, publication: StagePublicationData) -> PublishedStage:
        _require_aware(publication.published_at)
        with self._engine.begin() as connection:
            context = (
                connection.execute(
                    select(
                        pipeline_stage.c.status,
                        pipeline_stage.c.worker_id,
                        pipeline_stage.c.lease_epoch,
                        pipeline_stage.c.lease_expires_at,
                        pipeline_stage.c.input_digest,
                        pipeline_stage.c.stage_definition_id,
                        pipeline_run.c.snapshot_id,
                        facility_snapshot.c.computation_bundle_id,
                        facility_snapshot.c.computation_bundle_digest,
                    )
                    .join(
                        pipeline_run, pipeline_run.c.resource_id == pipeline_stage.c.pipeline_run_id
                    )
                    .join(
                        facility_snapshot,
                        facility_snapshot.c.resource_id == pipeline_run.c.snapshot_id,
                    )
                    .where(pipeline_stage.c.resource_id == publication.stage_id)
                    .with_for_update(of=pipeline_stage)
                )
                .mappings()
                .one()
            )
            if context["status"] != "RUNNING":
                raise FencedPublication("stage must be RUNNING to publish")
            if (
                context["worker_id"] != publication.worker_id
                or context["lease_epoch"] != publication.epoch
            ):
                raise FencedPublication("worker or lease epoch is stale")
            if context["lease_expires_at"] <= publication.published_at:
                raise FencedPublication("lease expired before publication")
            if context["input_digest"] != publication.input_digest:
                raise FencedPublication("input digest does not match run contract")
            attempt_id = connection.execute(
                select(pipeline_stage_attempt.c.resource_id).where(
                    pipeline_stage_attempt.c.pipeline_stage_id == publication.stage_id,
                    pipeline_stage_attempt.c.lease_epoch == publication.epoch,
                    pipeline_stage_attempt.c.worker_id == publication.worker_id,
                    pipeline_stage_attempt.c.finished_at.is_(None),
                )
            ).scalar_one()
            publication_key = f"{publication.stage_id}:{context['stage_definition_id']}"
            connection.execute(
                insert(pipeline_stage_output).values(
                    resource_id=publication.output_id,
                    pipeline_stage_id=publication.stage_id,
                    snapshot_id=context["snapshot_id"],
                    computation_bundle_id=context["computation_bundle_id"],
                    computation_bundle_digest=context["computation_bundle_digest"],
                    publication_key=publication_key,
                    input_digest=publication.input_digest,
                    output_schema_version=publication.output_schema_version,
                    canonical_output=publication.canonical_output,
                    output_digest=publication.output_digest,
                    published_attempt_id=attempt_id,
                    published_lease_epoch=publication.epoch,
                    published_at=publication.published_at,
                )
            )
            connection.execute(
                update(pipeline_stage)
                .where(pipeline_stage.c.resource_id == publication.stage_id)
                .values(
                    status="SUCCEEDED",
                    worker_id=None,
                    lease_expires_at=None,
                    maximum_lease_expires_at=None,
                    updated_at=publication.published_at,
                )
            )
            connection.execute(
                update(pipeline_stage_attempt)
                .where(pipeline_stage_attempt.c.resource_id == attempt_id)
                .values(finished_at=publication.published_at, outcome="SUCCEEDED")
            )
            event_payload = canonical_json_bytes(
                {
                    "event_type": "pipeline.stage.published",
                    "output_digest": publication.output_digest,
                    "output_id": publication.output_id,
                }
            )
            connection.execute(
                insert(outbox_message).values(
                    message_id=publication.outbox_message_id,
                    topic="pipeline.stage.published",
                    message_key=publication_key,
                    payload=event_payload,
                    payload_digest=domain_digest("outbox_message", 1, event_payload),
                    created_at=publication.published_at,
                    available_at=publication.published_at,
                )
            )
            connection.execute(
                insert(audit_event).values(
                    event_id=publication.audit_event_id,
                    actor_id=publication.worker_id,
                    action="pipeline.stage.publish",
                    resource_type="pipeline_stage_output",
                    resource_id=publication.output_id,
                    correlation_id=publication.stage_id,
                    causation_id=attempt_id,
                    before_digest=publication.input_digest,
                    after_digest=publication.output_digest,
                    reason=None,
                    metadata={"lease_epoch": publication.epoch},
                    occurred_at=publication.published_at,
                )
            )
            if self._before_serializable_commit is not None:
                self._before_serializable_commit()
            return PublishedStage(publication.output_id, publication_key, publication.output_digest)

    def record_inbox(
        self,
        consumer: str,
        message_id: str,
        message_digest: str,
        outcome: bytes,
        now: datetime,
    ) -> InboxResult:
        _require_aware(now)
        with self._engine.begin() as connection:
            inserted = connection.execute(
                postgres_insert(inbox_receipt)
                .values(
                    consumer=consumer,
                    message_id=message_id,
                    message_digest=message_digest,
                    outcome=outcome,
                    received_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[inbox_receipt.c.consumer, inbox_receipt.c.message_id]
                )
                .returning(inbox_receipt.c.outcome)
            ).scalar_one_or_none()
            if inserted is not None:
                return InboxResult(inserted, False)
            existing = (
                connection.execute(
                    select(inbox_receipt).where(
                        inbox_receipt.c.consumer == consumer,
                        inbox_receipt.c.message_id == message_id,
                    )
                )
                .mappings()
                .one()
            )
            if existing["message_digest"] != message_digest:
                raise InboxDigestConflict("message ID was reused with a different digest")
            return InboxResult(existing["outcome"], True)

    def load_replay_package(
        self, snapshot_id: str, declared_environment: dict[str, str]
    ) -> ReplayPackage:
        with self._engine.connect() as connection:
            snapshot = (
                connection.execute(
                    select(facility_snapshot).where(facility_snapshot.c.resource_id == snapshot_id)
                )
                .mappings()
                .one()
            )
            bundle_ids = (
                snapshot["market_bundle_id"],
                snapshot["policy_bundle_id"],
                snapshot["legal_interpretation_bundle_id"],
                snapshot["computation_bundle_id"],
            )
            bundles = (
                connection.execute(
                    select(bundle_table).where(bundle_table.c.resource_id.in_(bundle_ids))
                )
                .mappings()
                .all()
            )
            outputs = (
                connection.execute(
                    select(pipeline_stage_output).where(
                        pipeline_stage_output.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .all()
            )
            inputs = (
                connection.execute(
                    select(snapshot_input_reference)
                    .where(snapshot_input_reference.c.snapshot_id == snapshot_id)
                    .order_by(snapshot_input_reference.c.position)
                )
                .mappings()
                .all()
            )
        domains = {
            "MARKET": "market_bundle",
            "POLICY": "policy_bundle",
            "LEGAL_INTERPRETATION": "legal_interpretation_bundle",
            "COMPUTATION": "computation_bundle",
        }
        artifacts = [
            ReplayArtifact(
                "facility_snapshot",
                snapshot_id,
                "snapshot_manifest",
                1,
                snapshot["canonical_manifest"],
                snapshot["digest"],
            )
        ]
        reconstructed_manifest = _reconstruct_snapshot_manifest(snapshot, inputs)
        artifacts.append(
            ReplayArtifact(
                "facility_snapshot_reconstructed",
                snapshot_id,
                "snapshot_manifest",
                1,
                reconstructed_manifest.canonical_bytes,
                snapshot["digest"],
            )
        )
        artifacts.extend(
            ReplayArtifact(
                "bundle",
                row["resource_id"],
                domains[row["bundle_type"]],
                1,
                row["canonical_payload"],
                row["digest"],
            )
            for row in bundles
        )
        artifacts.extend(
            ReplayArtifact(
                "pipeline_stage_output",
                row["resource_id"],
                "pipeline_stage_output",
                1,
                row["canonical_output"],
                row["output_digest"],
            )
            for row in outputs
        )
        return ReplayPackage(snapshot_id, tuple(artifacts), declared_environment)

    def append_replay_audit(
        self,
        result: ReplayResult,
        actor_id: str,
        correlation_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> None:
        _require_aware(occurred_at)
        result_digest = domain_digest("replay_result", 1, result.canonical_bytes)
        with self._engine.begin() as connection:
            connection.execute(
                insert(audit_event).values(
                    event_id=event_id,
                    actor_id=actor_id,
                    action="snapshot.replay.verify",
                    resource_type="facility_snapshot",
                    resource_id=result.snapshot_id,
                    correlation_id=correlation_id,
                    causation_id=None,
                    before_digest=None,
                    after_digest=result_digest,
                    reason=None,
                    metadata={
                        "level_a": result.level_a.value,
                        "level_b": result.level_b.value,
                        "issues": [issue.code for issue in result.issues],
                    },
                    occurred_at=occurred_at,
                )
            )

    def expire_idempotency_records(self, now: datetime) -> int:
        _require_aware(now)
        with self._engine.begin() as connection:
            records = (
                connection.execute(
                    select(idempotency_record)
                    .where(idempotency_record.c.retain_until <= now)
                    .with_for_update()
                )
                .mappings()
                .all()
            )
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
        row = (
            self._connection.execute(
                select(facility_working_state)
                .where(facility_working_state.c.resource_id == resource_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
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

    def get_bundle(self, resource_id: str) -> VersionBundle | None:
        row = (
            self._connection.execute(
                select(bundle_table).where(bundle_table.c.resource_id == resource_id)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _bundle_from_row(row)

    def find_snapshot_id(self, facility_id: str, working_version: int) -> str | None:
        return self._connection.execute(
            select(facility_snapshot.c.resource_id).where(
                facility_snapshot.c.facility_id == facility_id,
                facility_snapshot.c.facility_working_version == working_version,
            )
        ).scalar_one_or_none()

    def insert_snapshot(self, snapshot: SnapshotData) -> None:
        manifest = snapshot.manifest
        try:
            self._connection.execute(
                insert(facility_snapshot).values(
                    resource_id=manifest.snapshot_id,
                    facility_id=manifest.facility_id,
                    facility_working_version=manifest.facility_working_version,
                    legal_name=snapshot.legal_name,
                    currency=snapshot.currency,
                    facility_commitment=snapshot.facility_commitment,
                    as_of=manifest.as_of,
                    market_bundle_id=manifest.market_bundle.resource_id,
                    market_bundle_digest=manifest.market_bundle.digest,
                    policy_bundle_id=manifest.policy_bundle.resource_id,
                    policy_bundle_digest=manifest.policy_bundle.digest,
                    legal_interpretation_bundle_id=(
                        manifest.legal_interpretation_bundle.resource_id
                    ),
                    legal_interpretation_bundle_digest=(
                        manifest.legal_interpretation_bundle.digest
                    ),
                    computation_bundle_id=manifest.computation_bundle.resource_id,
                    computation_bundle_digest=manifest.computation_bundle.digest,
                    canonical_manifest=manifest.canonical_bytes,
                    digest=manifest.digest,
                    created_by=manifest.created_by,
                    created_at=manifest.created_at,
                )
            )
        except IntegrityError as exc:
            if _constraint_name(exc) == "one_freeze_per_version":
                raise SnapshotAlreadyFrozen("facility working version is already frozen") from None
            raise
        for position, item in enumerate(manifest.inputs):
            self._connection.execute(
                insert(snapshot_input_reference).values(
                    snapshot_id=manifest.snapshot_id,
                    position=position,
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    digest=item.digest,
                )
            )

    def insert_outbox_message(self, message: OutboxMessageData) -> None:
        self._connection.execute(
            insert(outbox_message).values(
                message_id=message.message_id,
                topic=message.topic,
                message_key=message.message_key,
                payload=message.payload,
                payload_digest=message.payload_digest,
                created_at=message.created_at,
                available_at=message.available_at,
            )
        )


def _reconstruct_snapshot_manifest(
    snapshot: RowMapping,
    inputs: Sequence[RowMapping],
) -> SnapshotManifest:
    return SnapshotManifest(
        snapshot_id=snapshot["resource_id"],
        facility_id=snapshot["facility_id"],
        facility_working_version=snapshot["facility_working_version"],
        schema_version="1.0",
        as_of=snapshot["as_of"],
        market_bundle=BundleReference(
            resource_id=snapshot["market_bundle_id"],
            digest=snapshot["market_bundle_digest"],
        ),
        policy_bundle=BundleReference(
            resource_id=snapshot["policy_bundle_id"],
            digest=snapshot["policy_bundle_digest"],
        ),
        legal_interpretation_bundle=BundleReference(
            resource_id=snapshot["legal_interpretation_bundle_id"],
            digest=snapshot["legal_interpretation_bundle_digest"],
        ),
        computation_bundle=BundleReference(
            resource_id=snapshot["computation_bundle_id"],
            digest=snapshot["computation_bundle_digest"],
        ),
        inputs=tuple(
            SnapshotInputReference(
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                digest=row["digest"],
            )
            for row in inputs
        ),
        created_by=snapshot["created_by"],
        created_at=snapshot["created_at"],
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


def _document_version_from_row(row: RowMapping) -> DocumentVersion:
    return DocumentVersion(
        resource_id=row["resource_id"],
        document_id=row["document_id"],
        version=row["version"],
        filename=row["filename"],
        content_type=row["content_type"],
        byte_digest=row["byte_digest"],
        size_bytes=row["size_bytes"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _candidate_fact_from_row(row: RowMapping) -> CandidateFact:
    return CandidateFact(
        fact_id=row["resource_id"],
        identity=FactIdentity(
            fact_type=row["fact_type"],
            subject_id=row["subject_id"],
            period=row["period"],
        ),
        value=dict(row["value"]),
        document_version_id=row["document_version_id"],
        document_byte_digest=row["document_byte_digest"],
        extracted_at=row["extracted_at"],
        page_region=row["page_region"],
        extraction_method=row["extraction_method"],
        extractor_version=row["extractor_version"],
        raw_value=row["raw_value"],
        normalized_value=row["normalized_value"],
    )


def _approved_fact_from_row(row: RowMapping) -> ApprovedFact:
    return ApprovedFact(
        fact_id=row["resource_id"],
        candidate_fact_id=row["candidate_fact_id"],
        identity=FactIdentity(
            fact_type=row["fact_type"],
            subject_id=row["subject_id"],
            period=row["period"],
        ),
        value=dict(row["value"]),
        document_version_id=row["document_version_id"],
        document_byte_digest=row["document_byte_digest"],
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        superseded_by=row["superseded_by"],
    )


def _rejected_fact_from_row(row: RowMapping) -> RejectedFact:
    return RejectedFact(
        fact_id=row["resource_id"],
        candidate_fact_id=row["candidate_fact_id"],
        identity=FactIdentity(
            fact_type=row["fact_type"],
            subject_id=row["subject_id"],
            period=row["period"],
        ),
        rejected_by=row["rejected_by"],
        rejected_at=row["rejected_at"],
        reason=row["reason"],
    )


def _warehouse_receipt_from_row(row: RowMapping) -> WarehouseReceiptRecord:
    return WarehouseReceiptRecord(
        resource_id=row["resource_id"],
        receipt=WarehouseReceiptEvidence(
            receipt_number=row["receipt_number"],
            warehouse_id=row["warehouse_id"],
            lot_id=row["lot_id"],
            quantity=row["quantity"],
            approved_fact_id=row["approved_fact_id"],
        ),
    )


def _ownership_claim_from_row(row: RowMapping) -> OwnershipClaimRecord:
    return OwnershipClaimRecord(
        resource_id=row["resource_id"],
        claim=InventoryOwnershipClaim(
            lot_id=row["lot_id"],
            period=row["period"],
            owner_party_id=row["owner_party_id"],
            pledgee_id=row["pledgee_id"],
            approved_fact_id=row["approved_fact_id"],
        ),
    )


def _lease_from_row(row: RowMapping, attempt_id: str, worker_id: str) -> StageLease:
    return StageLease(
        stage_id=row["resource_id"],
        attempt_id=attempt_id,
        worker_id=worker_id,
        epoch=row["lease_epoch"],
        input_digest=row["input_digest"],
        lease_expires_at=row["lease_expires_at"],
        maximum_lease_expires_at=row["maximum_lease_expires_at"],
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


def _is_serialization_failure(exc: BaseException) -> bool:
    if getattr(exc, "sqlstate", None) == "40001":
        return True
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) == "40001"
