"""Immutable version-bundle contract tests."""

from datetime import UTC, datetime

import pytest

from canopyledger.integrity.bundles import BundleError, BundleType, VersionBundle
from canopyledger.integrity.canonical import domain_digest

NOW = datetime(2026, 6, 21, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"


def test_policy_bundle_is_content_addressed_with_its_own_domain() -> None:
    bundle = VersionBundle.build(
        resource_id="pol_0198a000-0000-7000-8000-000000000001",
        bundle_type=BundleType.POLICY,
        schema_version="1.0",
        payload={"advance_rate": "0.80", "eligible_origins": ["BR", "CO"]},
        created_by=ACTOR_ID,
        created_at=NOW,
    )
    assert bundle.digest == domain_digest("policy_bundle", 1, bundle.canonical_bytes)
    assert bundle.reference.resource_id == bundle.resource_id
    assert bundle.reference.digest == bundle.digest


def test_bundle_copies_canonical_bytes_instead_of_retaining_mutable_payload() -> None:
    payload = {"advance_rate": "0.80"}
    bundle = VersionBundle.build(
        resource_id="pol_0198a000-0000-7000-8000-000000000002",
        bundle_type=BundleType.POLICY,
        schema_version="1.0",
        payload=payload,
        created_by=ACTOR_ID,
        created_at=NOW,
    )
    payload["advance_rate"] = "0.50"
    assert bundle.payload == {"advance_rate": "0.80"}


def test_bundle_type_requires_matching_resource_prefix() -> None:
    with pytest.raises(BundleError, match="resource prefix"):
        VersionBundle.build(
            resource_id="mkt_0198a000-0000-7000-8000-000000000001",
            bundle_type=BundleType.POLICY,
            schema_version="1.0",
            payload={},
            created_by=ACTOR_ID,
            created_at=NOW,
        )

