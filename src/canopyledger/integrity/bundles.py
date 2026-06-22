"""Immutable, content-addressed version-bundle contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .canonical import canonical_json_bytes, domain_digest
from .snapshot import RESOURCE_ID_PATTERN, BundleReference


class BundleError(ValueError):
    """Raised when a version bundle violates its immutable contract."""


class BundleType(StrEnum):
    MARKET = "MARKET"
    POLICY = "POLICY"
    LEGAL_INTERPRETATION = "LEGAL_INTERPRETATION"
    COMPUTATION = "COMPUTATION"


_BUNDLE_DOMAINS = {
    BundleType.MARKET: "market_bundle",
    BundleType.POLICY: "policy_bundle",
    BundleType.LEGAL_INTERPRETATION: "legal_interpretation_bundle",
    BundleType.COMPUTATION: "computation_bundle",
}
_BUNDLE_PREFIXES = {
    BundleType.MARKET: "mkt_",
    BundleType.POLICY: "pol_",
    BundleType.LEGAL_INTERPRETATION: "leg_",
    BundleType.COMPUTATION: "cmp_",
}


@dataclass(frozen=True)
class VersionBundle:
    """One validated bundle whose digest covers its semantic canonical payload."""

    resource_id: str
    bundle_type: BundleType
    schema_version: str
    canonical_bytes: bytes
    digest: str
    created_by: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        resource_id: str,
        bundle_type: BundleType,
        schema_version: str,
        payload: Any,
        created_by: str,
        created_at: datetime,
    ) -> VersionBundle:
        cls._validate_metadata(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version=schema_version,
            created_by=created_by,
            created_at=created_at,
        )
        canonical_bytes = canonical_json_bytes(
            {
                "bundle_type": bundle_type.value,
                "payload": payload,
                "schema_version": schema_version,
            }
        )
        return cls(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version=schema_version,
            canonical_bytes=canonical_bytes,
            digest=domain_digest(_BUNDLE_DOMAINS[bundle_type], 1, canonical_bytes),
            created_by=created_by,
            created_at=created_at,
        )

    @classmethod
    def restore(
        cls,
        *,
        resource_id: str,
        bundle_type: BundleType,
        schema_version: str,
        canonical_bytes: bytes,
        digest: str,
        created_by: str,
        created_at: datetime,
    ) -> VersionBundle:
        cls._validate_metadata(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version=schema_version,
            created_by=created_by,
            created_at=created_at,
        )
        expected = domain_digest(_BUNDLE_DOMAINS[bundle_type], 1, canonical_bytes)
        if digest != expected:
            raise BundleError(f"stored bundle digest mismatch: expected {expected}, got {digest}")
        decoded = json.loads(canonical_bytes)
        if (
            not isinstance(decoded, dict)
            or decoded.get("bundle_type") != bundle_type.value
            or decoded.get("schema_version") != schema_version
            or "payload" not in decoded
        ):
            raise BundleError("stored canonical bundle metadata is inconsistent")
        if canonical_json_bytes(decoded) != canonical_bytes:
            raise BundleError("stored bundle bytes are not canonical")
        return cls(
            resource_id=resource_id,
            bundle_type=bundle_type,
            schema_version=schema_version,
            canonical_bytes=canonical_bytes,
            digest=digest,
            created_by=created_by,
            created_at=created_at,
        )

    @property
    def payload(self) -> Any:
        return json.loads(self.canonical_bytes)["payload"]

    @property
    def reference(self) -> BundleReference:
        return BundleReference(resource_id=self.resource_id, digest=self.digest)

    @staticmethod
    def _validate_metadata(
        *,
        resource_id: str,
        bundle_type: BundleType,
        schema_version: str,
        created_by: str,
        created_at: datetime,
    ) -> None:
        if re.fullmatch(RESOURCE_ID_PATTERN, resource_id) is None:
            raise BundleError("bundle resource ID is invalid")
        if not resource_id.startswith(_BUNDLE_PREFIXES[bundle_type]):
            raise BundleError("bundle resource prefix does not match bundle type")
        if re.fullmatch(r"[1-9][0-9]*\.[0-9]+", schema_version) is None:
            raise BundleError("bundle schema version must use major.minor digits")
        if (
            re.fullmatch(RESOURCE_ID_PATTERN, created_by) is None
            or not created_by.startswith("act_")
        ):
            raise BundleError("bundle creator must be an actor resource ID")
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise BundleError("bundle creation time must be timezone-aware")
