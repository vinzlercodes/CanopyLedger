"""Immutable snapshot manifest contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import (
    CanonicalSetRule,
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)

RESOURCE_ID_PATTERN = (
    r"^[a-z]{3}_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class FrozenContract(BaseModel):
    """Base for immutable validated domain contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class BundleReference(FrozenContract):
    """Pinned immutable version-bundle reference."""

    resource_id: str = Field(pattern=RESOURCE_ID_PATTERN)
    digest: str = Field(pattern=DIGEST_PATTERN)


class SnapshotInputReference(FrozenContract):
    """One immutable input included in a snapshot."""

    resource_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    resource_id: str = Field(pattern=RESOURCE_ID_PATTERN)
    digest: str = Field(pattern=DIGEST_PATTERN)


class SnapshotManifest(FrozenContract):
    """Complete, content-addressed snapshot input package."""

    snapshot_id: str = Field(pattern=RESOURCE_ID_PATTERN)
    facility_id: str = Field(pattern=RESOURCE_ID_PATTERN)
    facility_working_version: int = Field(ge=1)
    schema_version: Literal["1.0"]
    as_of: datetime
    market_bundle: BundleReference
    policy_bundle: BundleReference
    legal_interpretation_bundle: BundleReference
    computation_bundle: BundleReference
    inputs: tuple[SnapshotInputReference, ...]
    created_by: str = Field(pattern=RESOURCE_ID_PATTERN)
    created_at: datetime

    @field_validator("as_of", "created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_unique_inputs(self) -> SnapshotManifest:
        identities = [(item.resource_type, item.resource_id) for item in self.inputs]
        if len(identities) != len(set(identities)):
            raise ValueError("snapshot input identities must be unique")
        if any(item.resource_type == "candidate_fact" for item in self.inputs):
            raise ValueError(
                "Candidate evidence cannot satisfy an approved-fact requirement"
            )
        return self

    @property
    def canonical_bytes(self) -> bytes:
        payload = {
            "snapshot_id": self.snapshot_id,
            "facility_id": self.facility_id,
            "facility_working_version": self.facility_working_version,
            "schema_version": self.schema_version,
            "as_of": canonical_timestamp(self.as_of),
            "market_bundle": self.market_bundle.model_dump(),
            "policy_bundle": self.policy_bundle.model_dump(),
            "legal_interpretation_bundle": self.legal_interpretation_bundle.model_dump(),
            "computation_bundle": self.computation_bundle.model_dump(),
            "inputs": [item.model_dump() for item in self.inputs],
            "created_by": self.created_by,
            "created_at": canonical_timestamp(self.created_at),
        }
        return canonical_json_bytes(
            payload,
            set_rules=(
                CanonicalSetRule(
                    path=("inputs",),
                    sort_keys=("resource_type", "resource_id", "digest"),
                ),
            ),
        )

    @property
    def digest(self) -> str:
        return domain_digest("snapshot_manifest", 1, self.canonical_bytes)
