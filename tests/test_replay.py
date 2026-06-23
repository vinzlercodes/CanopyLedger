"""Level A bitwise and Level B semantic replay verification tests."""

from __future__ import annotations

import json

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.replay import (
    ReplayArtifact,
    ReplayPackage,
    ReplayStatus,
    verify_replay,
)


def artifact(*, stored_digest: str | None = None, replayed: bytes | None = None) -> ReplayArtifact:
    content = canonical_json_bytes({"amount": "10.00", "decision": "ELIGIBLE"})
    return ReplayArtifact(
        resource_type="pipeline_stage_output",
        resource_id="out_0198a000-0000-7000-8000-000000000001",
        digest_domain="pipeline_stage_output",
        digest_schema_version=1,
        canonical_bytes=content,
        stored_digest=stored_digest or domain_digest("pipeline_stage_output", 1, content),
        replayed_semantic_bytes=replayed,
    )


def test_exact_envelope_and_semantics_match_both_levels() -> None:
    environment = {"git_commit": "abc123", "python": "3.12.8", "timezone": "UTC"}
    result = verify_replay(
        ReplayPackage("snp_0198a000-0000-7000-8000-000000000001", (artifact(),), environment),
        current_environment=environment,
    )
    assert result.level_a is ReplayStatus.MATCH
    assert result.level_b is ReplayStatus.MATCH
    assert result.issues == ()


def test_environment_mismatch_only_fails_level_a() -> None:
    package = ReplayPackage(
        "snp_0198a000-0000-7000-8000-000000000001",
        (artifact(),),
        {"cpu": "arm64"},
    )
    result = verify_replay(package, current_environment={"cpu": "x86_64"})
    assert result.level_a is ReplayStatus.MISMATCH
    assert result.level_b is ReplayStatus.MATCH
    assert [issue.code for issue in result.issues] == ["ENVIRONMENT_MISMATCH"]


def test_digest_and_semantic_mismatches_have_deterministic_issue_order() -> None:
    replayed = canonical_json_bytes({"amount": "11.00", "decision": "ELIGIBLE"})
    result = verify_replay(
        ReplayPackage(
            "snp_0198a000-0000-7000-8000-000000000001",
            (artifact(stored_digest=f"sha256:{'0' * 64}", replayed=replayed),),
            {},
        ),
        current_environment={},
    )
    assert result.level_a is ReplayStatus.MISMATCH
    assert result.level_b is ReplayStatus.MISMATCH
    assert [issue.code for issue in result.issues] == [
        "DIGEST_MISMATCH",
        "SEMANTIC_MISMATCH",
    ]
    assert json.loads(result.canonical_bytes)["level_b"] == "MISMATCH"
