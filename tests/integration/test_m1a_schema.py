"""Executable contract for the complete M1A PostgreSQL resource schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from canopyledger.persistence.schema import metadata

EXPECTED_TABLES = {
    "approved_fact",
    "approval_action",
    "approval_request",
    "audit_event",
    "bundle",
    "candidate_fact",
    "climate_eudr_input",
    "climate_traceability_geometry",
    "credit_early_warning_input",
    "decision_override",
    "evidence_document",
    "evidence_document_version",
    "facility_snapshot",
    "facility_working_state",
    "final_decision",
    "hedge_liquidity_input",
    "scenario_capacity_input",
    "internal_risk_capacity_assessment",
    "idempotency_record",
    "idempotency_tombstone",
    "inbox_receipt",
    "inventory_ownership_claim",
    "outbox_message",
    "pipeline_run",
    "pipeline_stage",
    "pipeline_stage_attempt",
    "pipeline_stage_output",
    "quantity_reconciliation_issue",
    "rejected_fact",
    "recommendation",
    "snapshot_input_reference",
    "warehouse_receipt_evidence",
}

pytestmark = pytest.mark.postgres


def test_metadata_declares_complete_m1a_resource_schema() -> None:
    assert set(metadata.tables) == {f"canopyledger.{table_name}" for table_name in EXPECTED_TABLES}


def test_alembic_upgrade_creates_complete_m1a_resource_schema(
    connection: Connection,
) -> None:
    rows = connection.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'canopyledger'")
    )
    assert {row.tablename for row in rows} == EXPECTED_TABLES


def test_immutable_resources_have_database_update_and_delete_guards(
    connection: Connection,
) -> None:
    guarded_tables = {
        "audit_event",
        "approval_action",
        "approval_request",
        "bundle",
        "candidate_fact",
        "climate_eudr_input",
        "climate_traceability_geometry",
        "credit_early_warning_input",
        "decision_override",
        "evidence_document_version",
        "facility_snapshot",
        "final_decision",
        "hedge_liquidity_input",
        "scenario_capacity_input",
        "internal_risk_capacity_assessment",
        "idempotency_tombstone",
        "inbox_receipt",
        "inventory_ownership_claim",
        "pipeline_stage_output",
        "quantity_reconciliation_issue",
        "rejected_fact",
        "recommendation",
        "snapshot_input_reference",
        "warehouse_receipt_evidence",
    }
    rows = connection.execute(
        text(
            """
            SELECT event_object_table
            FROM information_schema.triggers
            WHERE trigger_schema = 'canopyledger'
              AND trigger_name LIKE '%_immutable'
            """
        )
    )
    assert {row.event_object_table for row in rows} == guarded_tables

    now = datetime(2026, 6, 21, 12, tzinfo=UTC)
    connection.execute(
        text(
            """
            INSERT INTO canopyledger.bundle (
                resource_id, bundle_type, schema_version, canonical_payload,
                digest, created_by, created_at
            ) VALUES (
                'bnd_00000000-0000-7000-8000-000000000001', 'POLICY', '1.0',
                :payload, :digest, 'act_00000000-0000-7000-8000-000000000001', :now
            )
            """
        ),
        {"payload": b"{}", "digest": f"sha256:{'1' * 64}", "now": now},
    )
    connection.commit()

    with pytest.raises(DBAPIError, match="immutable resource bundle cannot be UPDATE"):
        connection.execute(
            text(
                """
                UPDATE canopyledger.bundle
                SET schema_version = '2.0'
                WHERE resource_id = 'bnd_00000000-0000-7000-8000-000000000001'
                """
            )
        )
    connection.rollback()

    with pytest.raises(DBAPIError, match="immutable resource bundle cannot be DELETE"):
        connection.execute(
            text(
                """
                DELETE FROM canopyledger.bundle
                WHERE resource_id = 'bnd_00000000-0000-7000-8000-000000000001'
                """
            )
        )
    connection.rollback()


def test_outbox_allows_delivery_bookkeeping_but_guards_message_content(
    connection: Connection,
) -> None:
    now = datetime(2026, 6, 21, 12, tzinfo=UTC)
    message_id = "msg_00000000-0000-7000-8000-000000000001"
    connection.execute(
        text(
            """
            INSERT INTO canopyledger.outbox_message (
                message_id, topic, message_key, payload, payload_digest, created_at, available_at
            ) VALUES (:message_id, 'pipeline.start', 'snapshot-1', :payload, :digest, :now, :now)
            """
        ),
        {
            "message_id": message_id,
            "payload": b"{}",
            "digest": f"sha256:{'2' * 64}",
            "now": now,
        },
    )
    connection.commit()

    connection.execute(
        text(
            """
            UPDATE canopyledger.outbox_message
            SET delivery_attempts = delivery_attempts + 1, delivered_at = :now
            WHERE message_id = :message_id
            """
        ),
        {"message_id": message_id, "now": now},
    )
    connection.commit()

    with pytest.raises(DBAPIError, match="outbox message identity and payload are immutable"):
        connection.execute(
            text(
                """
                UPDATE canopyledger.outbox_message
                SET payload = :payload
                WHERE message_id = :message_id
                """
            ),
            {"message_id": message_id, "payload": b'{"changed":true}'},
        )
    connection.rollback()

    with pytest.raises(DBAPIError, match="outbox messages cannot be deleted"):
        connection.execute(
            text("DELETE FROM canopyledger.outbox_message WHERE message_id = :message_id"),
            {"message_id": message_id},
        )
    connection.rollback()


def test_approved_fact_only_allows_supersession_update(
    connection: Connection,
) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    connection.execute(
        text(
            """
            INSERT INTO canopyledger.evidence_document (resource_id, created_by, created_at)
            VALUES ('doc_00000000-0000-7000-8000-000000000001',
                    'act_00000000-0000-7000-8000-000000000001', :now)
            """
        ),
        {"now": now},
    )
    connection.execute(
        text(
            """
            INSERT INTO canopyledger.evidence_document_version (
                resource_id, document_id, version, filename, content_type, original_bytes,
                byte_digest, size_bytes, object_key, created_by, created_at
            ) VALUES (
                'dov_00000000-0000-7000-8000-000000000001_v1',
                'doc_00000000-0000-7000-8000-000000000001',
                1, 'ownership.pdf', 'application/pdf', :bytes, :digest, 5,
                'evidence/dov_00000000-0000-7000-8000-000000000001_v1',
                'act_00000000-0000-7000-8000-000000000001', :now
            )
            """
        ),
        {"bytes": b"owned", "digest": f"sha256:{'1' * 64}", "now": now},
    )
    for suffix, owner, lot_id in (
        ("001", "000000000001", "lot_00000000-0000-7000-8000-000000000001"),
        ("002", "000000000002", "lot_00000000-0000-7000-8000-000000000002"),
    ):
        connection.execute(
            text(
                """
                INSERT INTO canopyledger.candidate_fact (
                    resource_id, fact_type, subject_id, period, value,
                    document_version_id, document_byte_digest, page_region,
                    extraction_method, extractor_version, raw_value, normalized_value,
                    extracted_at
                ) VALUES (
                    :candidate_id, 'ownership',
                    :lot_id, '2026-07',
                    CAST(:value AS jsonb),
                    'dov_00000000-0000-7000-8000-000000000001_v1',
                    :digest, 'page=1;box=10,20,300,80',
                    'deterministic_template', 'ownership-template-v1',
                    :owner_id, :owner_id, :now
                )
                """
            ),
            {
                "candidate_id": f"caf_00000000-0000-7000-8000-000000000{suffix}",
                "lot_id": lot_id,
                "value": f'{{"owner_party_id":"pty_00000000-0000-7000-8000-{owner}"}}',
                "owner_id": f"pty_00000000-0000-7000-8000-{owner}",
                "digest": f"sha256:{'1' * 64}",
                "now": now,
            },
        )
    for suffix, lot_id in (
        ("001", "lot_00000000-0000-7000-8000-000000000001"),
        ("002", "lot_00000000-0000-7000-8000-000000000002"),
    ):
        connection.execute(
            text(
                """
                INSERT INTO canopyledger.approved_fact (
                    resource_id, candidate_fact_id, fact_type, subject_id, period,
                    value, document_version_id, document_byte_digest, approved_by,
                    approved_at
                ) VALUES (
                    :approved_id, :candidate_id, 'ownership', :lot_id, '2026-07',
                    CAST(:value AS jsonb),
                    'dov_00000000-0000-7000-8000-000000000001_v1',
                    :digest, 'act_00000000-0000-7000-8000-000000000001', :now
                )
                """
            ),
            {
                "approved_id": f"apf_00000000-0000-7000-8000-000000000{suffix}",
                "candidate_id": f"caf_00000000-0000-7000-8000-000000000{suffix}",
                "lot_id": lot_id,
                "value": '{"owner_party_id":"pty_00000000-0000-7000-8000-000000000001"}',
                "digest": f"sha256:{'1' * 64}",
                "now": now,
            },
        )
    connection.commit()

    with pytest.raises(DBAPIError, match="approved fact content is immutable"):
        connection.execute(
            text(
                """
                UPDATE canopyledger.approved_fact
                SET value = CAST(:value AS jsonb)
                WHERE resource_id = 'apf_00000000-0000-7000-8000-000000000001'
                """
            ),
            {"value": '{"owner_party_id":"changed"}'},
        )
    connection.rollback()

    with pytest.raises(DBAPIError, match="approved facts cannot be deleted"):
        connection.execute(
            text(
                """
                DELETE FROM canopyledger.approved_fact
                WHERE resource_id = 'apf_00000000-0000-7000-8000-000000000001'
                """
            )
        )
    connection.rollback()

    connection.execute(
        text(
            """
            UPDATE canopyledger.approved_fact
            SET superseded_by = 'apf_00000000-0000-7000-8000-000000000002'
            WHERE resource_id = 'apf_00000000-0000-7000-8000-000000000001'
            """
        )
    )
    connection.commit()

    with pytest.raises(DBAPIError, match="approved fact supersession is immutable"):
        connection.execute(
            text(
                """
                UPDATE canopyledger.approved_fact
                SET superseded_by = NULL
                WHERE resource_id = 'apf_00000000-0000-7000-8000-000000000001'
                """
            )
        )
    connection.rollback()


def test_migration_grants_only_required_writer_table_capabilities(
    connection: Connection,
) -> None:
    expected = {
        ("application_writer", "facility_working_state", "SELECT"): True,
        ("application_writer", "facility_working_state", "INSERT"): True,
        ("application_writer", "facility_working_state", "UPDATE"): True,
        ("application_writer", "facility_working_state", "DELETE"): False,
        ("application_writer", "bundle", "INSERT"): True,
        ("application_writer", "bundle", "UPDATE"): False,
        ("application_writer", "evidence_document", "INSERT"): True,
        ("application_writer", "evidence_document", "UPDATE"): False,
        ("application_writer", "evidence_document_version", "INSERT"): True,
        ("application_writer", "evidence_document_version", "UPDATE"): False,
        ("application_writer", "candidate_fact", "INSERT"): True,
        ("application_writer", "candidate_fact", "UPDATE"): False,
        ("application_writer", "approved_fact", "INSERT"): True,
        ("application_writer", "approved_fact", "UPDATE"): True,
        ("application_writer", "approved_fact", "DELETE"): False,
        ("application_writer", "idempotency_record", "DELETE"): True,
        ("application_writer", "hedge_liquidity_input", "INSERT"): True,
        ("application_writer", "hedge_liquidity_input", "UPDATE"): False,
        ("application_writer", "scenario_capacity_input", "INSERT"): True,
        ("application_writer", "scenario_capacity_input", "UPDATE"): False,
        ("application_writer", "climate_eudr_input", "INSERT"): True,
        ("application_writer", "climate_eudr_input", "UPDATE"): False,
        ("application_writer", "climate_traceability_geometry", "INSERT"): True,
        ("application_writer", "climate_traceability_geometry", "UPDATE"): False,
        ("application_writer", "credit_early_warning_input", "INSERT"): True,
        ("application_writer", "credit_early_warning_input", "UPDATE"): False,
        ("application_writer", "recommendation", "SELECT"): True,
        ("application_writer", "recommendation", "INSERT"): True,
        ("application_writer", "recommendation", "UPDATE"): False,
        ("application_writer", "approval_request", "INSERT"): True,
        ("application_writer", "approval_request", "UPDATE"): False,
        ("application_writer", "approval_action", "INSERT"): True,
        ("application_writer", "approval_action", "UPDATE"): False,
        ("application_writer", "decision_override", "INSERT"): True,
        ("application_writer", "decision_override", "UPDATE"): False,
        ("application_writer", "final_decision", "INSERT"): True,
        ("application_writer", "final_decision", "UPDATE"): False,
        ("application_writer", "facility_snapshot", "SELECT"): True,
        ("application_writer", "pipeline_stage_output", "SELECT"): True,
        ("application_writer", "internal_risk_capacity_assessment", "SELECT"): True,
        ("application_writer", "pipeline_stage", "UPDATE"): False,
        ("pipeline_writer", "pipeline_stage", "SELECT"): True,
        ("pipeline_writer", "pipeline_stage", "INSERT"): True,
        ("pipeline_writer", "pipeline_stage", "UPDATE"): True,
        ("pipeline_writer", "pipeline_stage", "DELETE"): False,
        ("pipeline_writer", "pipeline_stage_output", "INSERT"): True,
        ("pipeline_writer", "pipeline_stage_output", "UPDATE"): False,
        ("pipeline_writer", "hedge_liquidity_input", "SELECT"): True,
        ("pipeline_writer", "scenario_capacity_input", "SELECT"): True,
        ("pipeline_writer", "climate_eudr_input", "SELECT"): True,
        ("pipeline_writer", "climate_traceability_geometry", "SELECT"): True,
        ("pipeline_writer", "credit_early_warning_input", "SELECT"): True,
        ("pipeline_writer", "internal_risk_capacity_assessment", "INSERT"): True,
        ("pipeline_writer", "internal_risk_capacity_assessment", "UPDATE"): False,
        ("pipeline_writer", "facility_working_state", "SELECT"): False,
    }
    actual = {
        (role, table_name, privilege): connection.execute(
            text("SELECT has_table_privilege(:role, :table_name, :privilege)"),
            {
                "role": role,
                "table_name": f"canopyledger.{table_name}",
                "privilege": privilege,
            },
        ).scalar_one()
        for role, table_name, privilege in expected
    }
    assert actual == expected
    assert connection.execute(
        text("SELECT has_column_privilege(:role, :table_name, :column_name, 'UPDATE')"),
        {
            "role": "application_writer",
            "table_name": "canopyledger.final_decision",
            "column_name": "superseded_by",
        },
    ).scalar_one()
    assert not connection.execute(
        text("SELECT has_column_privilege(:role, :table_name, :column_name, 'UPDATE')"),
        {
            "role": "application_writer",
            "table_name": "canopyledger.final_decision",
            "column_name": "status",
        },
    ).scalar_one()
