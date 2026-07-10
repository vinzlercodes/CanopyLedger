"""Snapshot manifest contract tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from canopyledger.integrity.snapshot import (
    BundleReference,
    SnapshotInputReference,
    SnapshotManifest,
)


def build_manifest(inputs: tuple[SnapshotInputReference, ...]) -> SnapshotManifest:
    return SnapshotManifest(
        snapshot_id="snp_0198a000-0000-7000-8000-000000000001",
        facility_id="fac_0198a000-0000-7000-8000-000000000001",
        facility_working_version=42,
        schema_version="1.0",
        as_of=datetime(2026, 6, 21, 17, 0, tzinfo=UTC),
        market_bundle=BundleReference(
            resource_id="mkt_0198a000-0000-7000-8000-000000000001",
            digest="sha256:" + "a" * 64,
        ),
        policy_bundle=BundleReference(
            resource_id="pol_0198a000-0000-7000-8000-000000000001",
            digest="sha256:" + "b" * 64,
        ),
        legal_interpretation_bundle=BundleReference(
            resource_id="leg_0198a000-0000-7000-8000-000000000001",
            digest="sha256:" + "d" * 64,
        ),
        computation_bundle=BundleReference(
            resource_id="cmp_0198a000-0000-7000-8000-000000000001",
            digest="sha256:" + "c" * 64,
        ),
        inputs=inputs,
        created_by="act_0198a000-0000-7000-8000-000000000001",
        created_at=datetime(2026, 6, 21, 17, 5, tzinfo=UTC),
    )


def test_input_reference_order_does_not_change_manifest_digest() -> None:
    first = SnapshotInputReference(
        resource_type="inventory_lot",
        resource_id="lot_0198a000-0000-7000-8000-000000000002",
        digest="sha256:" + "2" * 64,
    )
    second = SnapshotInputReference(
        resource_type="warehouse_receipt",
        resource_id="whr_0198a000-0000-7000-8000-000000000001",
        digest="sha256:" + "1" * 64,
    )
    assert build_manifest((first, second)).digest == build_manifest((second, first)).digest


def test_bundle_change_changes_manifest_digest() -> None:
    original = build_manifest(())
    changed = original.model_copy(
        update={
            "market_bundle": BundleReference(
                resource_id=original.market_bundle.resource_id,
                digest="sha256:" + "d" * 64,
            )
        }
    )
    assert original.digest != changed.digest


def test_manifest_pins_legal_interpretation_bundle() -> None:
    data = build_manifest(()).model_dump()
    data["legal_interpretation_bundle"] = BundleReference(
        resource_id="leg_0198a000-0000-7000-8000-000000000001",
        digest="sha256:" + "d" * 64,
    )
    manifest = SnapshotManifest.model_validate(data)
    assert manifest.legal_interpretation_bundle.digest == "sha256:" + "d" * 64
    assert b'"legal_interpretation_bundle"' in manifest.canonical_bytes


def test_manifest_records_creation_metadata_separately_from_business_as_of() -> None:
    data = build_manifest(()).model_dump()
    data.update(
        {
            "schema_version": "1.0",
            "created_by": "act_0198a000-0000-7000-8000-000000000001",
            "created_at": datetime(2026, 6, 21, 17, 5, tzinfo=UTC),
        }
    )
    manifest = SnapshotManifest.model_validate(data)
    decoded = manifest.canonical_bytes.decode()
    assert '"as_of":"2026-06-21T17:00:00.000000Z"' in decoded
    assert '"created_at":"2026-06-21T17:05:00.000000Z"' in decoded
    assert '"created_by":"act_0198a000-0000-7000-8000-000000000001"' in decoded
    assert '"schema_version":"1.0"' in decoded


def test_manifest_is_immutable() -> None:
    manifest = build_manifest(())
    with pytest.raises(ValidationError, match="frozen"):
        manifest.facility_working_version = 43  # type: ignore[misc]


def test_manifest_rejects_naive_as_of() -> None:
    data = build_manifest(()).model_dump()
    data["as_of"] = datetime(2026, 6, 21, 17, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        SnapshotManifest.model_validate(data)


def test_manifest_rejects_candidate_fact_inputs() -> None:
    candidate = SnapshotInputReference(
        resource_type="candidate_fact",
        resource_id="caf_0198a000-0000-7000-8000-000000000001",
        digest="sha256:" + "1" * 64,
    )

    with pytest.raises(ValidationError, match="Candidate evidence cannot"):
        build_manifest((candidate,))
