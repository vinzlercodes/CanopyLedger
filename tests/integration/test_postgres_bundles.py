"""PostgreSQL immutable bundle-registry acceptance tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select

from canopyledger.integrity.bundles import BundleType, VersionBundle
from canopyledger.persistence.postgres import ImmutableBundleConflict, PostgresIntegrityStore
from canopyledger.persistence.schema import bundle as bundle_table

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 6, 21, 12, tzinfo=UTC)
ACTOR_ID = "act_0198a000-0000-7000-8000-000000000001"
BUNDLE_ID = "pol_0198a000-0000-7000-8000-000000000101"


def build_policy_bundle(advance_rate: str) -> VersionBundle:
    return VersionBundle.build(
        resource_id=BUNDLE_ID,
        bundle_type=BundleType.POLICY,
        schema_version="1.0",
        payload={"advance_rate": advance_rate},
        created_by=ACTOR_ID,
        created_at=NOW,
    )


def test_identical_bundle_publication_replays_one_immutable_row(
    database_engine: Engine,
) -> None:
    store = PostgresIntegrityStore(database_engine)
    expected = build_policy_bundle("0.80")
    assert store.publish_bundle(expected) == expected
    assert store.publish_bundle(expected) == expected

    with database_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(bundle_table)
            .where(bundle_table.c.resource_id == BUNDLE_ID)
        ).scalar_one()
    assert count == 1


def test_same_bundle_id_with_changed_content_is_rejected(database_engine: Engine) -> None:
    store = PostgresIntegrityStore(database_engine)
    store.publish_bundle(build_policy_bundle("0.80"))
    with pytest.raises(ImmutableBundleConflict, match="different immutable content"):
        store.publish_bundle(build_policy_bundle("0.50"))
