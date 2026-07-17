"""Add immutable M9 governed-agent run records.

Revision ID: 20260717_10
Revises: 20260715_09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260717_10"
down_revision: str | None = "20260715_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.agent_run (
            resource_id varchar(64) PRIMARY KEY,
            facility_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.facility_working_state(resource_id) ON DELETE RESTRICT,
            snapshot_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.facility_snapshot(resource_id) ON DELETE RESTRICT,
            principal_id varchar(40) NOT NULL,
            agent_role varchar(64) NOT NULL,
            planner_type varchar(64) NOT NULL,
            status varchar(32) NOT NULL,
            payload jsonb NOT NULL,
            digest varchar(71) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT uq_agent_run_digest UNIQUE (digest)
        )
        """
    )
    op.execute(
        f"CREATE INDEX agent_run_snapshot_created "
        f"ON {SCHEMA}.agent_run (snapshot_id, created_at DESC)"
    )
    op.execute(
        f"""
        CREATE TRIGGER agent_run_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.agent_run
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.agent_run TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN
                GRANT SELECT ON {SCHEMA}.agent_run TO audit_reader;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.agent_run")
