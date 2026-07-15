"""Add immutable M5 climate/EUDR inputs and PostGIS traceability geometry.

Revision ID: 20260715_05
Revises: 20260711_04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260715_05"
down_revision: str | None = "20260711_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.climate_eudr_input (
            resource_id varchar(40) PRIMARY KEY,
            canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL CONSTRAINT uq_climate_eudr_input_digest UNIQUE,
            created_by varchar(40) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT climate_eudr_input_identity_digest UNIQUE (resource_id, digest)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.climate_traceability_geometry (
            climate_input_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.climate_eudr_input(resource_id) ON DELETE RESTRICT,
            lot_id varchar(40) NOT NULL,
            geometry geometry(Geometry, 4326) NOT NULL,
            geometry_digest varchar(71) NOT NULL,
            PRIMARY KEY (climate_input_id, lot_id),
            CONSTRAINT ck_climate_traceability_geometry_climate_geometry_type CHECK (
                GeometryType(geometry) IN ('POINT', 'POLYGON')
            ),
            CONSTRAINT climate_geometry_srid CHECK (ST_SRID(geometry) = 4326),
            CONSTRAINT climate_geometry_valid CHECK (ST_IsValid(geometry)),
            CONSTRAINT climate_geometry_simple CHECK (ST_IsSimple(geometry)),
            CONSTRAINT climate_geometry_antimeridian CHECK (
                GeometryType(geometry) = 'POINT' OR ST_XMax(geometry) - ST_XMin(geometry) <= 180
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_climate_traceability_geometry_spatial "
        f"ON {SCHEMA}.climate_traceability_geometry USING gist (geometry)"
    )
    for table in ("climate_eudr_input", "climate_traceability_geometry"):
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
                GRANT SELECT, INSERT ON {SCHEMA}.climate_eudr_input,
                    {SCHEMA}.climate_traceability_geometry TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') THEN
                GRANT SELECT ON {SCHEMA}.climate_eudr_input,
                    {SCHEMA}.climate_traceability_geometry TO pipeline_writer;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.climate_traceability_geometry")
    op.execute(f"DROP TABLE {SCHEMA}.climate_eudr_input")
