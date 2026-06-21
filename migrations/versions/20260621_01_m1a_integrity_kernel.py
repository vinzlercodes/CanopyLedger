"""Create the M1A integrity kernel resource schema.

Revision ID: 20260621_01
Revises: None
Create Date: 2026-06-21 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA, metadata

revision: str = "20260621_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    "bundle",
    "facility_snapshot",
    "snapshot_input_reference",
    "pipeline_stage_output",
    "audit_event",
    "idempotency_tombstone",
    "inbox_receipt",
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    metadata.create_all(bind=op.get_bind(), checkfirst=False)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_immutable_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'immutable resource % cannot be %', TG_TABLE_NAME, TG_OP
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
            """
        )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.guard_outbox_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'outbox messages cannot be deleted' USING ERRCODE = '55000';
            END IF;
            IF NEW.message_id IS DISTINCT FROM OLD.message_id
               OR NEW.topic IS DISTINCT FROM OLD.topic
               OR NEW.message_key IS DISTINCT FROM OLD.message_key
               OR NEW.payload IS DISTINCT FROM OLD.payload
               OR NEW.payload_digest IS DISTINCT FROM OLD.payload_digest
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.available_at IS DISTINCT FROM OLD.available_at THEN
                RAISE EXCEPTION 'outbox message identity and payload are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER outbox_message_guarded
        BEFORE UPDATE OR DELETE ON {SCHEMA}.outbox_message
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.guard_outbox_change()
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.facility_working_state,
                    {SCHEMA}.idempotency_record, {SCHEMA}.outbox_message
                    TO application_writer;
                GRANT SELECT, INSERT ON {SCHEMA}.bundle, {SCHEMA}.facility_snapshot,
                    {SCHEMA}.snapshot_input_reference, {SCHEMA}.idempotency_tombstone,
                    {SCHEMA}.audit_event TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
                GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.pipeline_run,
                    {SCHEMA}.pipeline_stage, {SCHEMA}.pipeline_stage_attempt,
                    {SCHEMA}.outbox_message TO pipeline_writer;
                GRANT SELECT, INSERT ON {SCHEMA}.pipeline_stage_output,
                    {SCHEMA}.inbox_receipt, {SCHEMA}.audit_event TO pipeline_writer;
                GRANT SELECT ON {SCHEMA}.facility_snapshot, {SCHEMA}.bundle,
                    {SCHEMA}.snapshot_input_reference TO pipeline_writer;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.guard_outbox_change() CASCADE")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_immutable_change() CASCADE")
    metadata.drop_all(bind=op.get_bind(), checkfirst=False)
