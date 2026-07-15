"""Add immutable M7 document extraction provenance.

Revision ID: 20260715_07
Revises: 20260715_06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260715_07"
down_revision: str | None = "20260715_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.document_extraction (
            resource_id varchar(40) PRIMARY KEY,
            request_digest varchar(71) NOT NULL UNIQUE,
            document_version_id varchar(80) NOT NULL,
            document_byte_digest varchar(71) NOT NULL,
            status varchar(32) NOT NULL,
            document_type varchar(80) NOT NULL,
            classification_method varchar(80) NOT NULL,
            classifier_version varchar(120) NOT NULL,
            extractor_version varchar(120) NOT NULL,
            text_digest varchar(71) NOT NULL,
            reconciliation_issue jsonb,
            completed_at timestamptz NOT NULL,
            CONSTRAINT document_extraction_document_version FOREIGN KEY
                (document_version_id, document_byte_digest)
                REFERENCES {SCHEMA}.evidence_document_version (resource_id, byte_digest)
                ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.candidate_fact_extraction (
            candidate_fact_id varchar(40) PRIMARY KEY
                REFERENCES {SCHEMA}.candidate_fact(resource_id) ON DELETE RESTRICT,
            extraction_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.document_extraction(resource_id) ON DELETE RESTRICT,
            confidence varchar(16) NOT NULL
        )
        """
    )
    for table in ("document_extraction", "candidate_fact_extraction"):
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
                GRANT SELECT, INSERT ON {SCHEMA}.document_extraction,
                    {SCHEMA}.candidate_fact_extraction TO application_writer;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.candidate_fact_extraction")
    op.execute(f"DROP TABLE {SCHEMA}.document_extraction")
