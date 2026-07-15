"""Add M8 immutable query records and curated read-only analytics views.

Revision ID: 20260715_09
Revises: 20260715_08
"""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from canopyledger.persistence.schema import SCHEMA

revision: str = "20260715_09"
down_revision: str | None = "20260715_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.analytics_query_run (
            resource_id varchar(40) PRIMARY KEY,
            request_digest varchar(71) NOT NULL CONSTRAINT uq_analytics_query_run_request_digest UNIQUE,
            actor_id varchar(40) NOT NULL,
            facility_id varchar(40) NOT NULL
                REFERENCES {SCHEMA}.facility_working_state(resource_id) ON DELETE RESTRICT,
            snapshot_id varchar(40)
                REFERENCES {SCHEMA}.facility_snapshot(resource_id) ON DELETE RESTRICT,
            question text NOT NULL,
            analytical_plan jsonb NOT NULL,
            query_digest varchar(71) NOT NULL,
            referenced_views jsonb NOT NULL,
            data_cutoff timestamptz NOT NULL,
            canonical_result bytea NOT NULL,
            result_digest varchar(71) NOT NULL,
            warnings jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT analytics_query_run_identity_digest UNIQUE (resource_id, request_digest)
        )
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER analytics_query_run_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.analytics_query_run
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_immutable_change()
        """
    )
    _create_views()
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'migration_owner') THEN
                GRANT SELECT ON
                    {SCHEMA}.approved_fact,
                    {SCHEMA}.facility_snapshot,
                    {SCHEMA}.internal_risk_capacity_assessment,
                    {SCHEMA}.pipeline_stage,
                    {SCHEMA}.pipeline_stage_output,
                    {SCHEMA}.snapshot_input_reference
                TO migration_owner;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_writer') THEN
                GRANT SELECT, INSERT ON {SCHEMA}.analytics_query_run TO application_writer;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_reader') THEN
                GRANT SELECT ON
                    analytics.snapshot_summary,
                    analytics.reserve_contribution,
                    analytics.receivable_eligibility,
                    analytics.hedge_ratio_month,
                    analytics.scenario_result,
                    analytics.approved_fact_snapshot
                TO analytics_reader;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    for view in (
        "approved_fact_snapshot",
        "scenario_result",
        "hedge_ratio_month",
        "receivable_eligibility",
        "reserve_contribution",
        "snapshot_summary",
    ):
        op.execute(f"DROP VIEW IF EXISTS analytics.{view}")
    op.execute(f"DROP TABLE {SCHEMA}.analytics_query_run")


def _create_views() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.snapshot_summary
        WITH (security_barrier = true) AS
        SELECT
            snapshot.resource_id AS snapshot_id,
            snapshot.facility_id,
            snapshot.as_of,
            snapshot.currency,
            snapshot.digest AS snapshot_digest,
            cbb.output_digest,
            (convert_from(cbb.canonical_output, 'UTF8')::jsonb #>> '{{result,contractual_borrowing_base}}')
                AS contractual_borrowing_base,
            (convert_from(cbb.canonical_output, 'UTF8')::jsonb #>> '{{result,contractual_availability}}')
                AS contractual_availability,
            irc.irc AS internal_risk_capacity,
            irc.digest AS internal_risk_capacity_digest
        FROM {SCHEMA}.facility_snapshot AS snapshot
        LEFT JOIN LATERAL (
            SELECT output.canonical_output, output.output_digest
            FROM {SCHEMA}.pipeline_stage_output AS output
            JOIN {SCHEMA}.pipeline_stage AS stage ON stage.resource_id = output.pipeline_stage_id
            WHERE output.snapshot_id = snapshot.resource_id
              AND stage.stage_definition_id = 'contractual_borrowing_base'
            ORDER BY output.published_at DESC
            LIMIT 1
        ) AS cbb ON true
        LEFT JOIN {SCHEMA}.internal_risk_capacity_assessment AS irc
            ON irc.snapshot_id = snapshot.resource_id
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.reserve_contribution
        WITH (security_barrier = true) AS
        SELECT
            snapshot.facility_id,
            output.snapshot_id,
            reserve.value ->> 'reserve_type' AS reserve_type,
            reserve.value ->> 'amount' AS reserve_amount,
            snapshot.currency,
            output.output_digest
        FROM {SCHEMA}.pipeline_stage_output AS output
        JOIN {SCHEMA}.pipeline_stage AS stage ON stage.resource_id = output.pipeline_stage_id
        JOIN {SCHEMA}.facility_snapshot AS snapshot ON snapshot.resource_id = output.snapshot_id
        CROSS JOIN LATERAL jsonb_array_elements(
            convert_from(output.canonical_output, 'UTF8')::jsonb #> '{{result,reserves}}'
        ) AS reserve(value)
        WHERE stage.stage_definition_id = 'eligibility_and_reserves'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.receivable_eligibility
        WITH (security_barrier = true) AS
        SELECT
            snapshot.facility_id,
            output.snapshot_id,
            receivable.value ->> 'receivable_id' AS receivable_id,
            receivable.value ->> 'open_amount' AS open_amount,
            receivable.value ->> 'advanced_value' AS advanced_value,
            receivable.value -> 'reason_codes' AS reason_codes,
            snapshot.currency,
            output.output_digest
        FROM {SCHEMA}.pipeline_stage_output AS output
        JOIN {SCHEMA}.pipeline_stage AS stage ON stage.resource_id = output.pipeline_stage_id
        JOIN {SCHEMA}.facility_snapshot AS snapshot ON snapshot.resource_id = output.snapshot_id
        CROSS JOIN LATERAL jsonb_array_elements(
            convert_from(output.canonical_output, 'UTF8')::jsonb #> '{{result,receivables}}'
        ) AS receivable(value)
        WHERE stage.stage_definition_id = 'collateral_valuation'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.hedge_ratio_month
        WITH (security_barrier = true) AS
        SELECT
            snapshot.facility_id,
            output.snapshot_id,
            month.value ->> 'delivery_month' AS delivery_month,
            month.value ->> 'physical_exposure' AS physical_exposure,
            month.value ->> 'hedge_delta_exposure' AS hedge_delta_exposure,
            month.value ->> 'net_price_exposure' AS net_price_exposure,
            (convert_from(output.canonical_output, 'UTF8')::jsonb #>> '{{result,exposure,exposure_unit}}')
                AS exposure_unit,
            output.output_digest
        FROM {SCHEMA}.pipeline_stage_output AS output
        JOIN {SCHEMA}.pipeline_stage AS stage ON stage.resource_id = output.pipeline_stage_id
        JOIN {SCHEMA}.facility_snapshot AS snapshot ON snapshot.resource_id = output.snapshot_id
        CROSS JOIN LATERAL jsonb_array_elements(
            convert_from(output.canonical_output, 'UTF8')::jsonb #> '{{result,exposure,delivery_month_mismatch}}'
        ) AS month(value)
        WHERE stage.stage_definition_id = 'hedge_liquidity'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.scenario_result
        WITH (security_barrier = true) AS
        SELECT
            snapshot.facility_id,
            output.snapshot_id,
            scenario.value ->> 'scenario_id' AS scenario_id,
            scenario.value ->> 'family' AS scenario_family,
            scenario.value ->> 'stressed_cbb' AS stressed_cbb,
            scenario.value ->> 'cbb_deficiency' AS cbb_deficiency,
            scenario.value ->> 'margin_liquidity_shortfall' AS margin_liquidity_shortfall,
            (convert_from(output.canonical_output, 'UTF8')::jsonb #>> '{{result,currency}}') AS currency,
            output.output_digest
        FROM {SCHEMA}.pipeline_stage_output AS output
        JOIN {SCHEMA}.pipeline_stage AS stage ON stage.resource_id = output.pipeline_stage_id
        JOIN {SCHEMA}.facility_snapshot AS snapshot ON snapshot.resource_id = output.snapshot_id
        CROSS JOIN LATERAL jsonb_array_elements(
            convert_from(output.canonical_output, 'UTF8')::jsonb #> '{{result,deterministic_scenarios}}'
        ) AS scenario(value)
        WHERE stage.stage_definition_id = 'scenario_capacity'
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.approved_fact_snapshot
        WITH (security_barrier = true) AS
        SELECT
            snapshot.facility_id,
            snapshot.resource_id AS snapshot_id,
            fact.resource_id AS approved_fact_id,
            fact.fact_type,
            fact.subject_id,
            fact.period,
            fact.value,
            input.digest AS approved_fact_digest,
            fact.approved_at
        FROM {SCHEMA}.facility_snapshot AS snapshot
        JOIN {SCHEMA}.snapshot_input_reference AS input ON input.snapshot_id = snapshot.resource_id
        JOIN {SCHEMA}.approved_fact AS fact ON fact.resource_id = input.resource_id
        WHERE input.resource_type = 'approved_fact'
        """
    )
    for view in (
        "snapshot_summary",
        "reserve_contribution",
        "receivable_eligibility",
        "hedge_ratio_month",
        "scenario_result",
        "approved_fact_snapshot",
    ):
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'migration_owner') THEN
                    ALTER VIEW analytics.{view} OWNER TO migration_owner;
                END IF;
            END $$
            """
        )
