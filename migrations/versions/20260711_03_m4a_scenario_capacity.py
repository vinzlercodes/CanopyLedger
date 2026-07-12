"""Add immutable M4A scenario inputs and separate IRC resources.

Revision ID: 20260711_03
Revises: 20260711_02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260711_03"
down_revision: str | None = "20260711_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.scenario_capacity_input (
            resource_id varchar(40) PRIMARY KEY,
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL UNIQUE,
            created_by varchar(40) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT scenario_capacity_input_identity_digest UNIQUE (resource_id, digest)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.internal_risk_capacity_assessment (
            resource_id varchar(40) PRIMARY KEY,
            snapshot_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.facility_snapshot(resource_id) ON DELETE RESTRICT,
            scenario_stage_output_id varchar(40) NOT NULL UNIQUE
                REFERENCES {SCHEMA}.pipeline_stage_output(resource_id) ON DELETE RESTRICT,
            cbb_output_digest varchar(71) NOT NULL,
            uncapped_irc varchar(128) NOT NULL,
            irc varchar(128) NOT NULL,
            currency varchar(3) NOT NULL,
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL,
            CONSTRAINT irc_snapshot_digest UNIQUE (snapshot_id, digest)
        )
        """
    )
    for table in ("scenario_capacity_input", "internal_risk_capacity_assessment"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {SCHEMA}.{table}")
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
            """
        )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.scenario_capacity_input TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
                GRANT SELECT ON {SCHEMA}.scenario_capacity_input TO pipeline_writer;
                GRANT SELECT, INSERT ON {SCHEMA}.internal_risk_capacity_assessment
                    TO pipeline_writer;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.internal_risk_capacity_assessment")
    op.execute(f"DROP TABLE {SCHEMA}.scenario_capacity_input")
