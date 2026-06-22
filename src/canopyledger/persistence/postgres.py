"""PostgreSQL adapters for M1A integrity resources."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from canopyledger.integrity.bundles import BundleType, VersionBundle

from .schema import bundle as bundle_table


class ImmutableBundleConflict(ValueError):
    """Raised when publication would give a bundle ID new content."""


class PostgresIntegrityStore:
    """Explicit transactional adapter for durable integrity resources."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish_bundle(self, bundle: VersionBundle) -> VersionBundle:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(bundle_table).values(
                        resource_id=bundle.resource_id,
                        bundle_type=bundle.bundle_type.value,
                        schema_version=bundle.schema_version,
                        canonical_payload=bundle.canonical_bytes,
                        digest=bundle.digest,
                        created_by=bundle.created_by,
                        created_at=bundle.created_at,
                    )
                )
        except IntegrityError:
            existing = self.load_bundle(bundle.resource_id)
            if existing == bundle:
                return existing
            raise ImmutableBundleConflict(
                f"bundle {bundle.resource_id} already has different immutable content"
            ) from None
        return bundle

    def load_bundle(self, resource_id: str) -> VersionBundle | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(bundle_table).where(bundle_table.c.resource_id == resource_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        return _bundle_from_row(row)


def _bundle_from_row(row: Any) -> VersionBundle:
    return VersionBundle.restore(
        resource_id=row["resource_id"],
        bundle_type=BundleType(row["bundle_type"]),
        schema_version=row["schema_version"],
        canonical_bytes=row["canonical_payload"],
        digest=row["digest"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )
