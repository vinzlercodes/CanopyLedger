"""Add immutable M4B decision-governance resources.

Revision ID: 20260711_04
Revises: 20260711_03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260711_04"
down_revision: str | None = "20260711_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.recommendation (
            resource_id varchar(40) PRIMARY KEY,
            snapshot_id varchar(40) NOT NULL REFERENCES {SCHEMA}.facility_snapshot(resource_id),
            author_id varchar(40) NOT NULL, expires_at timestamptz NOT NULL,
            canonical_payload bytea NOT NULL, digest varchar(71) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL)"""
    )
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.approval_request (
            resource_id varchar(40) PRIMARY KEY,
            recommendation_id varchar(40) NOT NULL REFERENCES {SCHEMA}.recommendation(resource_id),
            requested_by varchar(40) NOT NULL, expires_at timestamptz NOT NULL,
            canonical_payload bytea NOT NULL, digest varchar(71) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL)"""
    )
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.final_decision (
            resource_id varchar(40) PRIMARY KEY,
            snapshot_id varchar(40) NOT NULL REFERENCES {SCHEMA}.facility_snapshot(resource_id),
            recommendation_id varchar(40) NOT NULL REFERENCES {SCHEMA}.recommendation(resource_id),
            approval_request_id varchar(40) REFERENCES {SCHEMA}.approval_request(resource_id),
            status varchar(16) NOT NULL, approver_id varchar(40) NOT NULL, override_id varchar(40),
            superseded_by varchar(40) REFERENCES {SCHEMA}.final_decision(resource_id)
                DEFERRABLE INITIALLY DEFERRED,
            canonical_payload bytea NOT NULL, digest varchar(71) NOT NULL UNIQUE,
            approved_at timestamptz NOT NULL,
            CONSTRAINT final_decision_known_status CHECK (status IN ('APPROVED', 'REJECTED')))"""
    )
    op.execute(
        f"""CREATE UNIQUE INDEX IF NOT EXISTS one_active_final_decision_per_snapshot
            ON {SCHEMA}.final_decision (snapshot_id) WHERE superseded_by IS NULL"""
    )
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.decision_override (
            resource_id varchar(40) PRIMARY KEY,
            original_decision_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.final_decision(resource_id),
            recommendation_id varchar(40) NOT NULL REFERENCES {SCHEMA}.recommendation(resource_id),
            requester_id varchar(40) NOT NULL, expires_at timestamptz NOT NULL,
            requires_dual_control integer NOT NULL, canonical_payload bytea NOT NULL,
            digest varchar(71) NOT NULL UNIQUE, created_at timestamptz NOT NULL,
            CONSTRAINT decision_override_dual_control CHECK (requires_dual_control IN (0, 1)))"""
    )
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.approval_action (
            resource_id varchar(40) PRIMARY KEY,
            approval_request_id varchar(40) REFERENCES {SCHEMA}.approval_request(resource_id),
            override_id varchar(40) REFERENCES {SCHEMA}.decision_override(resource_id),
            actor_id varchar(40) NOT NULL, action varchar(32) NOT NULL, reason text NOT NULL,
            canonical_payload bytea NOT NULL, digest varchar(71) NOT NULL UNIQUE,
            occurred_at timestamptz NOT NULL,
            CONSTRAINT approval_action_one_target
                CHECK ((approval_request_id IS NULL) <> (override_id IS NULL)))"""
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_final_decision_override'
                  AND conrelid = '{SCHEMA}.final_decision'::regclass
            ) THEN
                ALTER TABLE {SCHEMA}.final_decision
                ADD CONSTRAINT fk_final_decision_override
                FOREIGN KEY (override_id) REFERENCES {SCHEMA}.decision_override(resource_id)
                ON DELETE RESTRICT;
            END IF;
        END
        $$
        """
    )
    for table in ("recommendation", "approval_request", "approval_action", "decision_override"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {SCHEMA}.{table}")
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
            ON {SCHEMA}.{table} FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()""")
    op.execute(
        f"""CREATE OR REPLACE FUNCTION {SCHEMA}.guard_final_decision_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR NEW.superseded_by IS NULL
              OR OLD.superseded_by IS NOT NULL
              OR NEW.resource_id <> OLD.resource_id
              OR NEW.snapshot_id <> OLD.snapshot_id
              OR NEW.recommendation_id <> OLD.recommendation_id
              OR NEW.approval_request_id IS DISTINCT FROM OLD.approval_request_id
              OR NEW.status <> OLD.status
              OR NEW.approver_id <> OLD.approver_id
              OR NEW.override_id IS DISTINCT FROM OLD.override_id
              OR NEW.canonical_payload <> OLD.canonical_payload
              OR NEW.digest <> OLD.digest
              OR NEW.approved_at <> OLD.approved_at THEN
                RAISE EXCEPTION 'final decision mutation is forbidden' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$"""
    )
    op.execute(f"DROP TRIGGER IF EXISTS final_decision_immutable ON {SCHEMA}.final_decision")
    op.execute(
        f"""CREATE TRIGGER final_decision_immutable BEFORE UPDATE OR DELETE
        ON {SCHEMA}.final_decision FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.guard_final_decision_change()"""
    )
    op.execute(
        f"""CREATE OR REPLACE FUNCTION {SCHEMA}.verify_final_decision_supersession()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_snapshot varchar(40); target_recommendation varchar(40);
        BEGIN
            IF NEW.superseded_by IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT snapshot_id, recommendation_id
            INTO target_snapshot, target_recommendation
            FROM {SCHEMA}.final_decision WHERE resource_id = NEW.superseded_by;
            IF target_snapshot IS NULL
              OR target_snapshot <> NEW.snapshot_id
              OR target_recommendation <> NEW.recommendation_id THEN
                RAISE EXCEPTION 'final decision supersession target is invalid'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                WITH RECURSIVE chain(resource_id, superseded_by, path, cycle) AS (
                    SELECT resource_id, superseded_by, ARRAY[resource_id]::varchar[], false
                    FROM {SCHEMA}.final_decision WHERE resource_id = NEW.resource_id
                    UNION ALL
                    SELECT decision.resource_id, decision.superseded_by,
                        chain.path || decision.resource_id,
                        decision.resource_id = ANY(chain.path)
                    FROM {SCHEMA}.final_decision AS decision
                    JOIN chain ON decision.resource_id = chain.superseded_by
                    WHERE chain.superseded_by IS NOT NULL AND NOT chain.cycle
                )
                SELECT 1 FROM chain WHERE cycle
            ) THEN
                RAISE EXCEPTION 'final decision supersession cannot be cyclic'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NULL;
        END;
        $$"""
    )
    op.execute(f"DROP TRIGGER IF EXISTS final_decision_supersession ON {SCHEMA}.final_decision")
    op.execute(
        f"""CREATE CONSTRAINT TRIGGER final_decision_supersession
        AFTER INSERT OR UPDATE ON {SCHEMA}.final_decision DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.verify_final_decision_supersession()"""
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.recommendation,
                    {SCHEMA}.approval_request, {SCHEMA}.approval_action,
                    {SCHEMA}.decision_override, {SCHEMA}.final_decision TO application_writer;
                GRANT UPDATE (superseded_by) ON {SCHEMA}.final_decision TO application_writer;
                GRANT SELECT ON {SCHEMA}.facility_snapshot,
                    {SCHEMA}.pipeline_stage_output,
                    {SCHEMA}.internal_risk_capacity_assessment TO application_writer;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.final_decision DROP CONSTRAINT IF EXISTS fk_final_decision_override"
    )
    for table in (
        "approval_action",
        "decision_override",
        "final_decision",
        "approval_request",
        "recommendation",
    ):
        op.execute(f"DROP TABLE {SCHEMA}.{table}")
