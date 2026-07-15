"""PostgreSQL M6 frozen-input and advisory publication acceptance gate."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from test_m1b_postgres_pipeline import ACTOR_ID, _freeze_snapshot

from canopyledger.application.integrity import IntegrityService
from canopyledger.credit.engine import CreditFeatureObservation, build_reference_bundle
from canopyledger.credit.postgres import (
    PostgresCreditEarlyWarningInputStore,
    PostgresCreditEarlyWarningRunner,
)
from canopyledger.integrity.bundles import BundleType
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def test_m6_publishes_only_from_frozen_input_and_approved_computation_bundle(
    database_engine: Engine,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresCreditEarlyWarningInputStore(database_engine)
    bundle = build_reference_bundle()
    stored = input_store.publish(
        resource_id="cei_0198a000-0000-7000-8000-000000000601",
        bundle=bundle,
        observation=CreditFeatureObservation(
            borrower_id="bor_0198a000-0000-7000-8000-000000000601",
            as_of=NOW,
            observed_at=NOW,
            values={
                "liquidity_ratio": Decimal("1.1"),
                "receivable_days": Decimal("58"),
                "margin_coverage_ratio": Decimal("1.0"),
                "payment_delay_days": Decimal("11"),
            },
        ),
        created_by=ACTOR_ID,
        created_at=NOW,
    )
    snapshot_id, bundles = _freeze_snapshot(
        IntegrityService(
            integrity,
            clock=lambda: NOW,
            snapshot_input_validators={
                "credit_early_warning_input": input_store.validate_snapshot_reference
            },
        ),
        integrity,
        inputs=(
            SnapshotInputReference(
                resource_type="credit_early_warning_input",
                resource_id=stored.resource_id,
                digest=stored.digest,
            ),
        ),
        bundle_payloads={
            BundleType.COMPUTATION: {"credit_early_warning": {"model_bundle_digest": bundle.digest}}
        },
    )

    output = PostgresCreditEarlyWarningRunner(
        database_engine, integrity, input_store, clock=lambda: NOW
    ).publish(snapshot_id, stored.resource_id, worker_id="credit-worker")

    assert output.result["advisory_only"] is True
    assert output.result["model_bundle_digest"] == bundle.digest
    assert output.computation_bundle_digest == bundles[BundleType.COMPUTATION].digest
