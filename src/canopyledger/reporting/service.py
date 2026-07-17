"""In-memory report package service; durable adapters preserve the same immutable contract."""

from __future__ import annotations

from dataclasses import dataclass

from canopyledger.reporting.core import ReportCompileInput, ReportModel, ReportModelCompiler
from canopyledger.reporting.rendering import PinnedReportRenderer, RenderedReportArtifact

REFERENCE_FONT_BYTES = b"CanopyLedger report renderer reference font v1\n"


def reference_report_renderer() -> PinnedReportRenderer:
    """Return the checked-in deterministic reference renderer configuration."""
    manifest = reference_renderer_manifest()
    return PinnedReportRenderer(
        renderer_version=str(manifest["renderer_version"]),
        font_bytes=manifest["font_bytes"] if isinstance(manifest["font_bytes"], bytes) else None,
        font_digest=str(manifest["font_digest"]),
        locale=str(manifest["locale"]),
        timezone=str(manifest["timezone"]),
    )


def reference_renderer_manifest() -> dict[str, str | bytes]:
    """Return the renderer parameters that must be pinned into a report model."""
    import hashlib

    return {
        "renderer_version": "canopyledger-html-v1",
        "font_bytes": REFERENCE_FONT_BYTES,
        "font_digest": "sha256:" + hashlib.sha256(REFERENCE_FONT_BYTES).hexdigest(),
        "locale": "en-US",
        "timezone": "UTC",
    }


def reference_report_service() -> InMemoryReportService:
    """Return a report service suitable for local and synthetic reference deployments."""
    return InMemoryReportService(
        compiler=ReportModelCompiler(), renderer=reference_report_renderer()
    )


@dataclass(frozen=True)
class ReportPackage:
    """One report model and its deterministic HTML/PDF renderings."""

    report_model: ReportModel
    artifacts: tuple[RenderedReportArtifact, ...]


class InMemoryReportService:
    """Stores reports append-only by report id for local/demo API delivery."""

    def __init__(self, *, compiler: ReportModelCompiler, renderer: PinnedReportRenderer) -> None:
        self._compiler = compiler
        self._renderer = renderer
        self._packages: dict[str, ReportPackage] = {}

    def generate(self, source: ReportCompileInput) -> ReportPackage:
        """Compile and render one immutable report, preserving retry idempotency."""
        model = self._compiler.compile(source)
        package = ReportPackage(
            report_model=model,
            artifacts=(self._renderer.render_html(model), self._renderer.render_pdf(model)),
        )
        existing = self._packages.get(model.resource_id)
        if existing is not None:
            if existing.report_model.digest != model.digest:
                raise ValueError("report id already represents different immutable content")
            return existing
        self._packages[model.resource_id] = package
        return package

    def get(self, report_id: str) -> ReportPackage:
        try:
            return self._packages[report_id]
        except KeyError as exc:
            raise KeyError("report package not found") from exc

    def list_for_decision(self, decision_id: str) -> tuple[ReportPackage, ...]:
        return tuple(
            package
            for _, package in sorted(self._packages.items())
            if package.report_model.decision_id == decision_id
        )
