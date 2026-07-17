"""Add immutable M10 canonical report models and rendered artifacts.

Revision ID: 20260717_11
Revises: 20260717_10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260717_11"
down_revision: str | None = "20260717_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.report_model (
            resource_id varchar(40) PRIMARY KEY,
            snapshot_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.facility_snapshot(resource_id) ON DELETE RESTRICT,
            decision_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.final_decision(resource_id) ON DELETE RESTRICT,
            package_kind varchar(32) NOT NULL
                CONSTRAINT ck_report_model_known_report_kind
                CHECK (package_kind IN ('CURRENT_OFFICIAL', 'HISTORICAL_AUDIT')),
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL CONSTRAINT uq_report_model_digest UNIQUE,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.report_artifact (
            resource_id varchar(64) PRIMARY KEY,
            report_model_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.report_model(resource_id) ON DELETE RESTRICT,
            artifact_format varchar(8) NOT NULL
                CONSTRAINT ck_report_artifact_known_report_artifact_format
                CHECK (artifact_format IN ('HTML', 'PDF')),
            rendered_bytes bytea NOT NULL,
            metadata jsonb NOT NULL,
            digest varchar(71) NOT NULL CONSTRAINT uq_report_artifact_digest UNIQUE,
            created_at timestamptz NOT NULL,
            CONSTRAINT report_artifact_format UNIQUE (report_model_id, artifact_format)
        )
        """
    )
    for table in ("report_model", "report_artifact"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
            """
        )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.report_model, {SCHEMA}.report_artifact
                    TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'report_reader') THEN
                GRANT SELECT ON {SCHEMA}.report_model, {SCHEMA}.report_artifact TO report_reader;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN
                GRANT SELECT ON {SCHEMA}.report_model, {SCHEMA}.report_artifact TO audit_reader;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.report_artifact")
    op.execute(f"DROP TABLE {SCHEMA}.report_model")
