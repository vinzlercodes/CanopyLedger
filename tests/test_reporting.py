"""M10 canonical reporting contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from canopyledger.reporting.core import (
    ReportCompileInput,
    ReportIneligible,
    ReportModelCompiler,
    ReportPackageKind,
)
from canopyledger.reporting.rendering import MissingPinnedFont, PinnedReportRenderer

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
FONT_BYTES = b"fixture-pinned-font-v1"
FONT_DIGEST = "sha256:" + hashlib.sha256(FONT_BYTES).hexdigest()


def _source(*, status: str = "APPROVED", superseded_by: str | None = None) -> ReportCompileInput:
    return ReportCompileInput(
        report_id="rpt_0198a000-0000-7000-8000-000000000001",
        package_kind=ReportPackageKind.CURRENT_OFFICIAL,
        decision={
            "resource_id": "fdc_0198a000-0000-7000-8000-000000000001",
            "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
            "status": status,
            "superseded_by": superseded_by,
            "digest": "sha256:" + "a" * 64,
        },
        snapshot={
            "snapshot_id": "snp_0198a000-0000-7000-8000-000000000001",
            "digest": "sha256:" + "b" * 64,
            "as_of": "2026-07-11T00:00:00.000000+00:00",
            "policy_bundle": {"digest": "sha256:" + "c" * 64},
            "computation_bundle": {"digest": "sha256:" + "d" * 64},
        },
        decision_pack={
            "contractual_borrowing_base": {"amount": "100000.00", "currency": "USD"},
            "contractual_availability": {"amount": "75000.00", "currency": "USD"},
            "internal_risk_capacity": {"amount": "90000.00", "currency": "USD"},
            "recommendation": {
                "recommended_incremental_draw": {"amount": "60000.00", "currency": "USD"}
            },
            "final_decision": {"resource_id": "fdc_0198a000-0000-7000-8000-000000000001"},
        },
        stage_outputs={
            "collateral": {"output_digest": "sha256:" + "e" * 64},
            "hedge": {"output_digest": "sha256:" + "f" * 64},
            "scenario": {"output_digest": "sha256:" + "1" * 64},
            "climate": {"output_digest": "sha256:" + "2" * 64},
            "credit": {"output_digest": "sha256:" + "3" * 64},
        },
        template_version="committee-pack-v1",
        renderer_manifest={
            "renderer": "canopyledger-html-v1",
            "font_digest": FONT_DIGEST,
            "locale": "en-US",
            "timezone": "UTC",
        },
        created_at=NOW,
    )


def test_report_model_is_canonical_replayable_and_keeps_authoritative_caps_distinct() -> None:
    compiler = ReportModelCompiler()

    first = compiler.compile(_source())
    replay = compiler.compile(_source())

    assert first.digest == replay.digest
    assert first.canonical_json == replay.canonical_json
    assert first.sections["facility_summary"]["snapshot_id"].startswith("snp_")
    capacity = first.sections["capacity_and_decision"]
    assert capacity["contractual_borrowing_base"]["amount"] == "100000.00"
    assert first.sections["capacity_and_decision"]["internal_risk_capacity"]["amount"] == "90000.00"
    assert capacity["recommended_incremental_draw"]["amount"] == "60000.00"
    assert first.artifact_manifest["template_version"] == "committee-pack-v1"


@pytest.mark.parametrize("status,superseded_by", [("REJECTED", None), ("APPROVED", "fdc_new")])
def test_official_report_rejects_noncurrent_or_nonapproved_decisions(
    status: str, superseded_by: str | None
) -> None:
    with pytest.raises(ReportIneligible):
        ReportModelCompiler().compile(_source(status=status, superseded_by=superseded_by))


def test_pinned_renderer_normalizes_metadata_and_fails_closed_without_the_declared_font() -> None:
    model = ReportModelCompiler().compile(_source())
    renderer = PinnedReportRenderer(
        renderer_version="canopyledger-html-v1",
        font_bytes=FONT_BYTES,
        font_digest=FONT_DIGEST,
        locale="en-US",
        timezone="UTC",
    )

    first_html = renderer.render_html(model)
    replay_html = renderer.render_html(model)
    first_pdf = renderer.render_pdf(model)
    replay_pdf = renderer.render_pdf(model)

    assert first_html.bytes == replay_html.bytes
    assert first_pdf.bytes == replay_pdf.bytes
    assert first_pdf.bytes.startswith(b"%PDF-1.4")
    assert first_pdf.metadata["creation_date"] == "D:19700101000000Z"

    with pytest.raises(MissingPinnedFont):
        PinnedReportRenderer(
            renderer_version="canopyledger-html-v1",
            font_bytes=None,
            font_digest=FONT_DIGEST,
            locale="en-US",
            timezone="UTC",
        ).render_pdf(model)
