"""SQLAlchemy Core metadata for the M1A integrity resource model."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType

SCHEMA = "canopyledger"

metadata = MetaData(
    naming_convention={
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
    }
)


class PostGISGeometry(UserDefinedType[object]):
    """PostGIS geometry type kept in Core metadata without a GeoAlchemy dependency."""

    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        return "geometry(Geometry,4326)"

facility_working_state = Table(
    "facility_working_state",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("legal_name", String(200), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("facility_commitment", String(128), nullable=False),
    Column("version", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="positive_version"),
    schema=SCHEMA,
)

bundle = Table(
    "bundle",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("bundle_type", String(32), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", "digest", name="bundle_identity_digest"),
    CheckConstraint(
        "bundle_type IN ('MARKET', 'POLICY', 'LEGAL_INTERPRETATION', 'COMPUTATION')",
        name="known_type",
    ),
    schema=SCHEMA,
)

facility_snapshot = Table(
    "facility_snapshot",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "facility_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_working_state.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("facility_working_version", BigInteger, nullable=False),
    Column("legal_name", String(200), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("facility_commitment", String(128), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("market_bundle_id", String(40), nullable=False),
    Column("market_bundle_digest", String(71), nullable=False),
    Column("policy_bundle_id", String(40), nullable=False),
    Column("policy_bundle_digest", String(71), nullable=False),
    Column("legal_interpretation_bundle_id", String(40), nullable=False),
    Column("legal_interpretation_bundle_digest", String(71), nullable=False),
    Column("computation_bundle_id", String(40), nullable=False),
    Column("computation_bundle_digest", String(71), nullable=False),
    Column("canonical_manifest", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("facility_id", "facility_working_version", name="one_freeze_per_version"),
    ForeignKeyConstraint(
        ["market_bundle_id", "market_bundle_digest"],
        [f"{SCHEMA}.bundle.resource_id", f"{SCHEMA}.bundle.digest"],
        ondelete="RESTRICT",
        name="fk_snapshot_market_bundle",
    ),
    ForeignKeyConstraint(
        ["policy_bundle_id", "policy_bundle_digest"],
        [f"{SCHEMA}.bundle.resource_id", f"{SCHEMA}.bundle.digest"],
        ondelete="RESTRICT",
        name="fk_snapshot_policy_bundle",
    ),
    ForeignKeyConstraint(
        ["legal_interpretation_bundle_id", "legal_interpretation_bundle_digest"],
        [f"{SCHEMA}.bundle.resource_id", f"{SCHEMA}.bundle.digest"],
        ondelete="RESTRICT",
        name="fk_snapshot_legal_bundle",
    ),
    ForeignKeyConstraint(
        ["computation_bundle_id", "computation_bundle_digest"],
        [f"{SCHEMA}.bundle.resource_id", f"{SCHEMA}.bundle.digest"],
        ondelete="RESTRICT",
        name="fk_snapshot_computation_bundle",
    ),
    schema=SCHEMA,
)

snapshot_input_reference = Table(
    "snapshot_input_reference",
    metadata,
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("position", Integer, primary_key=True),
    Column("resource_type", String(64), nullable=False),
    Column("resource_id", String(40), nullable=False),
    Column("digest", String(71), nullable=False),
    UniqueConstraint("snapshot_id", "resource_type", "resource_id", name="input_identity"),
    CheckConstraint("position >= 0", name="nonnegative_position"),
    schema=SCHEMA,
)

evidence_document = Table(
    "evidence_document",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

evidence_document_version = Table(
    "evidence_document_version",
    metadata,
    Column("resource_id", String(80), primary_key=True),
    Column(
        "document_id",
        String(40),
        ForeignKey(f"{SCHEMA}.evidence_document.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("version", Integer, nullable=False),
    Column("filename", String(255), nullable=False),
    Column("content_type", String(120), nullable=False),
    Column("original_bytes", LargeBinary, nullable=False),
    Column("byte_digest", String(71), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("object_key", String(256), nullable=False),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("document_id", "version", name="document_version_number"),
    UniqueConstraint("resource_id", "byte_digest", name="document_version_digest"),
    CheckConstraint("version >= 1", name="positive_version"),
    CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
    schema=SCHEMA,
)

candidate_fact = Table(
    "candidate_fact",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("fact_type", String(80), nullable=False),
    Column("subject_id", String(100), nullable=False),
    Column("period", String(40), nullable=False),
    Column("value", JSONB, nullable=False),
    Column(
        "document_version_id",
        String(80),
        ForeignKey(f"{SCHEMA}.evidence_document_version.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("document_byte_digest", String(71), nullable=False),
    Column("page_region", String(200), nullable=False),
    Column("extraction_method", String(80), nullable=False),
    Column("extractor_version", String(120), nullable=False),
    Column("raw_value", Text, nullable=False),
    Column("normalized_value", Text, nullable=False),
    Column("extracted_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["document_version_id", "document_byte_digest"],
        [
            f"{SCHEMA}.evidence_document_version.resource_id",
            f"{SCHEMA}.evidence_document_version.byte_digest",
        ],
        ondelete="RESTRICT",
        name="candidate_fact_document_version",
    ),
    schema=SCHEMA,
)

approved_fact = Table(
    "approved_fact",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "candidate_fact_id",
        String(40),
        ForeignKey(f"{SCHEMA}.candidate_fact.resource_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("fact_type", String(80), nullable=False),
    Column("subject_id", String(100), nullable=False),
    Column("period", String(40), nullable=False),
    Column("value", JSONB, nullable=False),
    Column(
        "document_version_id",
        String(80),
        ForeignKey(f"{SCHEMA}.evidence_document_version.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("document_byte_digest", String(71), nullable=False),
    Column("approved_by", String(40), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column(
        "superseded_by",
        String(40),
        ForeignKey(
            f"{SCHEMA}.approved_fact.resource_id",
            deferrable=True,
            initially="DEFERRED",
        ),
    ),
    ForeignKeyConstraint(
        ["candidate_fact_id"],
        [f"{SCHEMA}.candidate_fact.resource_id"],
        ondelete="RESTRICT",
        name="approved_fact_candidate",
    ),
    ForeignKeyConstraint(
        ["document_version_id", "document_byte_digest"],
        [
            f"{SCHEMA}.evidence_document_version.resource_id",
            f"{SCHEMA}.evidence_document_version.byte_digest",
        ],
        ondelete="RESTRICT",
        name="approved_fact_document_version",
    ),
    schema=SCHEMA,
)
Index(
    "one_active_approved_fact_per_identity",
    approved_fact.c.fact_type,
    approved_fact.c.subject_id,
    approved_fact.c.period,
    unique=True,
    postgresql_where=approved_fact.c.superseded_by.is_(None),
)

rejected_fact = Table(
    "rejected_fact",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "candidate_fact_id",
        String(40),
        ForeignKey(f"{SCHEMA}.candidate_fact.resource_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("fact_type", String(80), nullable=False),
    Column("subject_id", String(100), nullable=False),
    Column("period", String(40), nullable=False),
    Column("rejected_by", String(40), nullable=False),
    Column("rejected_at", DateTime(timezone=True), nullable=False),
    Column("reason", Text, nullable=False),
    schema=SCHEMA,
)

warehouse_receipt_evidence = Table(
    "warehouse_receipt_evidence",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("receipt_number", String(100), nullable=False),
    Column("warehouse_id", String(40), nullable=False),
    Column("lot_id", String(40), nullable=False),
    Column("quantity", String(80), nullable=False),
    Column(
        "approved_fact_id",
        String(40),
        ForeignKey(f"{SCHEMA}.approved_fact.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    UniqueConstraint("warehouse_id", "receipt_number", name="receipt_number_per_warehouse"),
    schema=SCHEMA,
)

inventory_ownership_claim = Table(
    "inventory_ownership_claim",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("lot_id", String(40), nullable=False),
    Column("period", String(40), nullable=False),
    Column("owner_party_id", String(40), nullable=False),
    Column("pledgee_id", String(40), nullable=False),
    Column(
        "approved_fact_id",
        String(40),
        ForeignKey(f"{SCHEMA}.approved_fact.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    UniqueConstraint("lot_id", "period", name="ownership_claim_identity"),
    schema=SCHEMA,
)

quantity_reconciliation_issue = Table(
    "quantity_reconciliation_issue",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("lot_id", String(40), nullable=False),
    Column("expected_quantity", String(80), nullable=False),
    Column("receipt_quantity", String(80), nullable=False),
    Column("difference", String(80), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)


hedge_liquidity_input = Table(
    "hedge_liquidity_input",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", "digest", name="hedge_liquidity_input_identity_digest"),
    schema=SCHEMA,
)

scenario_capacity_input = Table(
    "scenario_capacity_input",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", "digest", name="scenario_capacity_input_identity_digest"),
    schema=SCHEMA,
)

climate_eudr_input = Table(
    "climate_eudr_input",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", "digest", name="climate_eudr_input_identity_digest"),
    schema=SCHEMA,
)

credit_early_warning_input = Table(
    "credit_early_warning_input",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_by", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("resource_id", "digest", name="credit_early_warning_input_identity_digest"),
    schema=SCHEMA,
)

climate_traceability_geometry = Table(
    "climate_traceability_geometry",
    metadata,
    Column(
        "climate_input_id",
        String(40),
        ForeignKey(f"{SCHEMA}.climate_eudr_input.resource_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("lot_id", String(40), primary_key=True),
    Column("geometry", PostGISGeometry(), nullable=False),
    Column("geometry_digest", String(71), nullable=False),
    CheckConstraint(
        "GeometryType(geometry) IN ('POINT', 'POLYGON')",
        name="climate_geometry_type",
    ),
    schema=SCHEMA,
)
Index(
    "ix_climate_traceability_geometry_spatial",
    climate_traceability_geometry.c.geometry,
    postgresql_using="gist",
)

idempotency_record = Table(
    "idempotency_record",
    metadata,
    Column("actor_id", String(40), primary_key=True),
    Column("operation", String(128), primary_key=True),
    Column("resource_namespace", String(128), primary_key=True),
    Column("idempotency_key", String(128), primary_key=True),
    Column("fingerprint", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("response_status", Integer),
    Column("response_headers", JSONB),
    Column("response_body", LargeBinary),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("retain_until", DateTime(timezone=True), nullable=False),
    CheckConstraint("state IN ('PENDING', 'COMPLETED')", name="known_state"),
    schema=SCHEMA,
)

idempotency_tombstone = Table(
    "idempotency_tombstone",
    metadata,
    Column("actor_id", String(40), primary_key=True),
    Column("operation", String(128), primary_key=True),
    Column("resource_namespace", String(128), primary_key=True),
    Column("idempotency_key", String(128), primary_key=True),
    Column("fingerprint", String(71), nullable=False),
    Column("expired_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

outbox_message = Table(
    "outbox_message",
    metadata,
    Column("message_id", String(40), primary_key=True),
    Column("topic", String(128), nullable=False),
    Column("message_key", String(256), nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column("payload_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True)),
    Column("delivery_attempts", Integer, nullable=False, server_default="0"),
    UniqueConstraint("topic", "message_key", name="topic_message_key"),
    CheckConstraint("delivery_attempts >= 0", name="nonnegative_delivery_attempts"),
    schema=SCHEMA,
)

inbox_receipt = Table(
    "inbox_receipt",
    metadata,
    Column("consumer", String(128), primary_key=True),
    Column("message_id", String(40), primary_key=True),
    Column("message_digest", String(71), nullable=False),
    Column("outcome", LargeBinary, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

pipeline_run = Table(
    "pipeline_run",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("run_key", String(256), nullable=False, unique=True),
    Column("input_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

pipeline_stage = Table(
    "pipeline_stage",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "pipeline_run_id",
        String(40),
        ForeignKey(f"{SCHEMA}.pipeline_run.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("stage_definition_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("lease_epoch", BigInteger, nullable=False, server_default="0"),
    Column("worker_id", String(128)),
    Column("lease_started_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("maximum_lease_expires_at", DateTime(timezone=True)),
    Column("input_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("pipeline_run_id", "stage_definition_id", name="run_stage_definition"),
    CheckConstraint("lease_epoch >= 0", name="nonnegative_lease_epoch"),
    CheckConstraint(
        "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED_TERMINAL')",
        name="known_status",
    ),
    schema=SCHEMA,
)
Index(
    "ix_pipeline_stage_claimable",
    pipeline_stage.c.status,
    pipeline_stage.c.lease_expires_at,
    pipeline_stage.c.created_at,
)

pipeline_stage_attempt = Table(
    "pipeline_stage_attempt",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "pipeline_stage_id",
        String(40),
        ForeignKey(f"{SCHEMA}.pipeline_stage.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("lease_epoch", BigInteger, nullable=False),
    Column("worker_id", String(128), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("outcome", String(32)),
    UniqueConstraint("pipeline_stage_id", "lease_epoch", name="stage_epoch"),
    UniqueConstraint(
        "resource_id",
        "pipeline_stage_id",
        "lease_epoch",
        name="identity_stage_epoch",
    ),
    CheckConstraint("lease_epoch >= 1", name="positive_lease_epoch"),
    schema=SCHEMA,
)

pipeline_stage_output = Table(
    "pipeline_stage_output",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "pipeline_stage_id",
        String(40),
        ForeignKey(f"{SCHEMA}.pipeline_stage.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("computation_bundle_id", String(40), nullable=False),
    Column("computation_bundle_digest", String(71), nullable=False),
    Column("publication_key", String(256), nullable=False, unique=True),
    Column("input_digest", String(71), nullable=False),
    Column("output_schema_version", String(64), nullable=False),
    Column("canonical_output", LargeBinary, nullable=False),
    Column("output_digest", String(71), nullable=False),
    Column("published_attempt_id", String(40), nullable=False),
    Column("published_lease_epoch", BigInteger, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["computation_bundle_id", "computation_bundle_digest"],
        [f"{SCHEMA}.bundle.resource_id", f"{SCHEMA}.bundle.digest"],
        ondelete="RESTRICT",
        name="fk_output_computation_bundle",
    ),
    ForeignKeyConstraint(
        ["published_attempt_id", "pipeline_stage_id", "published_lease_epoch"],
        [
            f"{SCHEMA}.pipeline_stage_attempt.resource_id",
            f"{SCHEMA}.pipeline_stage_attempt.pipeline_stage_id",
            f"{SCHEMA}.pipeline_stage_attempt.lease_epoch",
        ],
        ondelete="RESTRICT",
        name="fk_output_publishing_attempt",
    ),
    schema=SCHEMA,
)

internal_risk_capacity_assessment = Table(
    "internal_risk_capacity_assessment",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "scenario_stage_output_id",
        String(40),
        ForeignKey(f"{SCHEMA}.pipeline_stage_output.resource_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("cbb_output_digest", String(71), nullable=False),
    Column("uncapped_irc", String(128), nullable=False),
    Column("irc", String(128), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("snapshot_id", "digest", name="irc_snapshot_digest"),
    schema=SCHEMA,
)

recommendation = Table(
    "recommendation",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("author_id", String(40), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

approval_request = Table(
    "approval_request",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "recommendation_id",
        String(40),
        ForeignKey(f"{SCHEMA}.recommendation.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requested_by", String(40), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

approval_action = Table(
    "approval_action",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "approval_request_id",
        String(40),
        ForeignKey(f"{SCHEMA}.approval_request.resource_id", ondelete="RESTRICT"),
    ),
    Column(
        "override_id",
        String(40),
        ForeignKey(f"{SCHEMA}.decision_override.resource_id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("actor_id", String(40), nullable=False),
    Column("action", String(32), nullable=False),
    Column("reason", Text, nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "(approval_request_id IS NULL) <> (override_id IS NULL)", name="one_governance_target"
    ),
    schema=SCHEMA,
)

final_decision = Table(
    "final_decision",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "snapshot_id",
        String(40),
        ForeignKey(f"{SCHEMA}.facility_snapshot.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "recommendation_id",
        String(40),
        ForeignKey(f"{SCHEMA}.recommendation.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "approval_request_id",
        String(40),
        ForeignKey(f"{SCHEMA}.approval_request.resource_id", ondelete="RESTRICT"),
    ),
    Column("status", String(16), nullable=False),
    Column("approver_id", String(40), nullable=False),
    Column(
        "override_id",
        String(40),
        ForeignKey(
            f"{SCHEMA}.decision_override.resource_id",
            ondelete="RESTRICT",
            name="fk_final_decision_override",
            use_alter=True,
        ),
    ),
    Column(
        "superseded_by",
        String(40),
        ForeignKey(f"{SCHEMA}.final_decision.resource_id", deferrable=True, initially="DEFERRED"),
    ),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('APPROVED', 'REJECTED')", name="known_status"),
    schema=SCHEMA,
)
Index(
    "one_active_final_decision_per_snapshot",
    final_decision.c.snapshot_id,
    unique=True,
    postgresql_where=final_decision.c.superseded_by.is_(None),
)

decision_override = Table(
    "decision_override",
    metadata,
    Column("resource_id", String(40), primary_key=True),
    Column(
        "original_decision_id",
        String(40),
        ForeignKey(f"{SCHEMA}.final_decision.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "recommendation_id",
        String(40),
        ForeignKey(f"{SCHEMA}.recommendation.resource_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requester_id", String(40), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("requires_dual_control", Integer, nullable=False),
    Column("canonical_payload", LargeBinary, nullable=False),
    Column("digest", String(71), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("requires_dual_control IN (0, 1)", name="boolean_dual_control"),
    schema=SCHEMA,
)

audit_event = Table(
    "audit_event",
    metadata,
    Column("event_id", String(40), primary_key=True),
    Column("actor_id", String(40), nullable=False),
    Column("action", String(128), nullable=False),
    Column("resource_type", String(64), nullable=False),
    Column("resource_id", String(40), nullable=False),
    Column("correlation_id", String(128), nullable=False),
    Column("causation_id", String(128)),
    Column("before_digest", String(71)),
    Column("after_digest", String(71)),
    Column("reason", Text),
    Column("metadata", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)
