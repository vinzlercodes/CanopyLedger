"""Add immutable frozen hedge/liquidity inputs for M3 S5 publication.

Revision ID: 20260711_02
Revises: 20260621_01
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260711_02"
down_revision: str | None = "20260621_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.hedge_liquidity_input (
            resource_id varchar(40) PRIMARY KEY,
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL UNIQUE,
            created_by varchar(40) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT hedge_liquidity_input_identity_digest UNIQUE (resource_id, digest)
        )
        """
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS hedge_liquidity_input_immutable ON {SCHEMA}.hedge_liquidity_input"
    )
    op.execute(
        f"""
        CREATE TRIGGER hedge_liquidity_input_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.hedge_liquidity_input
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.hedge_liquidity_input TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
                GRANT SELECT ON {SCHEMA}.hedge_liquidity_input TO pipeline_writer;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.hedge_liquidity_input")
