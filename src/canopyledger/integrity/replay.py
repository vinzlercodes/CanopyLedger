"""Deterministic Level A bitwise and Level B semantic replay verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .canonical import canonical_json_bytes, domain_digest


class ReplayStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True)
class ReplayArtifact:
    resource_type: str
    resource_id: str
    digest_domain: str
    digest_schema_version: int
    canonical_bytes: bytes
    stored_digest: str
    replayed_semantic_bytes: bytes | None = None


@dataclass(frozen=True)
class ReplayPackage:
    snapshot_id: str
    artifacts: tuple[ReplayArtifact, ...]
    declared_environment: dict[str, str]

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> ReplayPackage:
        artifacts = tuple(
            ReplayArtifact(
                resource_type=item["resource_type"],
                resource_id=item["resource_id"],
                digest_domain=item["digest_domain"],
                digest_schema_version=item["digest_schema_version"],
                canonical_bytes=item["canonical_json"].encode(),
                stored_digest=item["stored_digest"],
                replayed_semantic_bytes=(
                    item["replayed_semantic_json"].encode()
                    if item.get("replayed_semantic_json") is not None
                    else None
                ),
            )
            for item in value.get("artifacts", [])
        )
        return cls(value["snapshot_id"], artifacts, dict(value["declared_environment"]))


@dataclass(frozen=True, order=True)
class ReplayIssue:
    code: str
    resource_type: str
    resource_id: str
    detail: str


@dataclass(frozen=True)
class ArtifactVerification:
    resource_type: str
    resource_id: str
    stored_digest: str
    recomputed_digest: str


@dataclass(frozen=True)
class ReplayResult:
    snapshot_id: str
    level_a: ReplayStatus
    level_b: ReplayStatus
    artifacts: tuple[ArtifactVerification, ...]
    issues: tuple[ReplayIssue, ...]

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "artifacts": [artifact.__dict__ for artifact in self.artifacts],
                "issues": [issue.__dict__ for issue in self.issues],
                "level_a": self.level_a.value,
                "level_b": self.level_b.value,
                "snapshot_id": self.snapshot_id,
            }
        )


def verify_replay(
    package: ReplayPackage,
    *,
    current_environment: dict[str, str],
) -> ReplayResult:
    issues: list[ReplayIssue] = []
    artifacts: list[ArtifactVerification] = []
    if package.declared_environment != current_environment:
        issues.append(
            ReplayIssue(
                "ENVIRONMENT_MISMATCH",
                "replay_environment",
                package.snapshot_id,
                "current environment differs from the declared bitwise envelope",
            )
        )
    for artifact in sorted(
        package.artifacts, key=lambda item: (item.resource_type, item.resource_id)
    ):
        recomputed = domain_digest(
            artifact.digest_domain,
            artifact.digest_schema_version,
            artifact.canonical_bytes,
        )
        artifacts.append(
            ArtifactVerification(
                artifact.resource_type,
                artifact.resource_id,
                artifact.stored_digest,
                recomputed,
            )
        )
        if recomputed != artifact.stored_digest:
            issues.append(
                ReplayIssue(
                    "DIGEST_MISMATCH",
                    artifact.resource_type,
                    artifact.resource_id,
                    "stored digest differs from recomputed canonical-byte digest",
                )
            )
        try:
            semantic_bytes = canonical_json_bytes(json.loads(artifact.canonical_bytes))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            semantic_bytes = b""
        if semantic_bytes != artifact.canonical_bytes:
            issues.append(
                ReplayIssue(
                    "NON_CANONICAL_BYTES",
                    artifact.resource_type,
                    artifact.resource_id,
                    "stored artifact bytes are not canonical JSON",
                )
            )
        if (
            artifact.replayed_semantic_bytes is not None
            and canonical_json_bytes(json.loads(artifact.replayed_semantic_bytes)) != semantic_bytes
        ):
            issues.append(
                ReplayIssue(
                    "SEMANTIC_MISMATCH",
                    artifact.resource_type,
                    artifact.resource_id,
                    "replayed semantic value differs from stored canonical value",
                )
            )
    ordered = tuple(sorted(issues))
    bitwise_codes = {"ENVIRONMENT_MISMATCH", "DIGEST_MISMATCH", "NON_CANONICAL_BYTES"}
    semantic_codes = {"DIGEST_MISMATCH", "NON_CANONICAL_BYTES", "SEMANTIC_MISMATCH"}
    return ReplayResult(
        package.snapshot_id,
        ReplayStatus.MISMATCH
        if any(issue.code in bitwise_codes for issue in ordered)
        else ReplayStatus.MATCH,
        ReplayStatus.MISMATCH
        if any(issue.code in semantic_codes for issue in ordered)
        else ReplayStatus.MATCH,
        tuple(artifacts),
        ordered,
    )
