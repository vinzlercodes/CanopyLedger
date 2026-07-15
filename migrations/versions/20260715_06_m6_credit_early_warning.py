"""Add immutable M6 frozen early-warning inputs.

Revision ID: 20260715_06
Revises: 20260715_05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260715_06"
down_revision: str | None = "20260715_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.credit_early_warning_input (
            resource_id varchar(40) PRIMARY KEY,
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL CONSTRAINT uq_credit_early_warning_input_digest UNIQUE,
            created_by varchar(40) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT credit_early_warning_input_identity_digest UNIQUE (resource_id, digest)
        )
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER credit_early_warning_input_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.credit_early_warning_input
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.credit_early_warning_input TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
                GRANT SELECT ON {SCHEMA}.credit_early_warning_input TO pipeline_writer;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.credit_early_warning_input")
