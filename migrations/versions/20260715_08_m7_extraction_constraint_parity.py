"""Align M7 extraction constraint names with SQLAlchemy metadata.

Revision ID: 20260715_08
Revises: 20260715_07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260715_08"
down_revision: str | None = "20260715_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE connamespace = '{SCHEMA}'::regnamespace
                  AND conname = 'document_extraction_request_digest_key'
            ) THEN
                ALTER TABLE {SCHEMA}.document_extraction
                    RENAME CONSTRAINT document_extraction_request_digest_key
                    TO uq_document_extraction_request_digest;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE connamespace = '{SCHEMA}'::regnamespace
                  AND conname = 'uq_document_extraction_request_digest'
            ) THEN
                ALTER TABLE {SCHEMA}.document_extraction
                    RENAME CONSTRAINT uq_document_extraction_request_digest
                    TO document_extraction_request_digest_key;
            END IF;
        END
        $$
        """
    )
