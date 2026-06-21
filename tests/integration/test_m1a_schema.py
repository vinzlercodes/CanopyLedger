"""Executable contract for the complete M1A PostgreSQL resource schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from canopyledger.persistence.schema import metadata

EXPECTED_TABLES = {
    "audit_event",
    "bundle",
    "facility_snapshot",
    "facility_working_state",
    "idempotency_record",
    "idempotency_tombstone",
    "inbox_receipt",
    "outbox_message",
    "pipeline_run",
    "pipeline_stage",
    "pipeline_stage_attempt",
    "pipeline_stage_output",
    "snapshot_input_reference",
}

pytestmark = pytest.mark.postgres


def test_metadata_declares_complete_m1a_resource_schema() -> None:
    assert set(metadata.tables) == {
        f"canopyledger.{table_name}" for table_name in EXPECTED_TABLES
    }


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
        "bundle",
        "facility_snapshot",
        "idempotency_tombstone",
        "inbox_receipt",
        "pipeline_stage_output",
        "snapshot_input_reference",
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
        ("application_writer", "pipeline_stage", "UPDATE"): False,
        ("pipeline_writer", "pipeline_stage", "SELECT"): True,
        ("pipeline_writer", "pipeline_stage", "INSERT"): True,
        ("pipeline_writer", "pipeline_stage", "UPDATE"): True,
        ("pipeline_writer", "pipeline_stage", "DELETE"): False,
        ("pipeline_writer", "pipeline_stage_output", "INSERT"): True,
        ("pipeline_writer", "pipeline_stage_output", "UPDATE"): False,
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
