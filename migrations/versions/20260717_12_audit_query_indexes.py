"""Add query-backed indexes found by the end-to-end audit.

Revision ID: 20260717_12
Revises: 20260717_11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260717_12"
down_revision: str | None = "20260717_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES = (
    ("ix_pipeline_stage_output_snapshot", "pipeline_stage_output", "snapshot_id"),
    ("ix_candidate_fact_review_order", "candidate_fact", "extracted_at DESC, resource_id DESC"),
    (
        "ix_candidate_fact_extraction_extraction_candidate",
        "candidate_fact_extraction",
        "extraction_id, candidate_fact_id",
    ),
    ("ix_report_model_decision_created", "report_model", "decision_id, created_at, resource_id"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns in _INDEXES:
            # The M1A bootstrap creates its tables from current metadata.  On a fresh
            # database it may already have created an index declared on an M1A table;
            # existing installations still receive the missing index here.
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {SCHEMA}.{table} ({columns})"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _, _ in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY {SCHEMA}.{name}")
