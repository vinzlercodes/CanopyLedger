"""Pinned deterministic HTML/PDF renderers for canonical report models."""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from enum import StrEnum

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.reporting.core import ReportModel


class MissingPinnedFont(ValueError):
    """Raised instead of silently substituting a font during rendering."""


class ReportArtifactFormat(StrEnum):
    HTML = "HTML"
    PDF = "PDF"


@dataclass(frozen=True)
class RenderedReportArtifact:
    """A deterministic rendering and the metadata used to reproduce it."""

    format: ReportArtifactFormat
    report_model_digest: str
    bytes: bytes
    digest: str
    metadata: dict[str, str]


class PinnedReportRenderer:
    """Renders only the supplied model with a verified, pinned local font asset."""

    def __init__(
        self,
        *,
        renderer_version: str,
        font_bytes: bytes | None,
        font_digest: str,
        locale: str,
        timezone: str,
    ) -> None:
        self._renderer_version = renderer_version
        self._font_bytes = font_bytes
        self._font_digest = font_digest
        self._locale = locale
        self._timezone = timezone

    def render_html(self, model: ReportModel) -> RenderedReportArtifact:
        """Render stable semantic HTML without clock, network, or calculation access."""
        self._verify_environment(model)
        section_html = "".join(
            "<section><h2>"
            + html.escape(name.replace("_", " ").title())
            + "</h2><pre>"
            + html.escape(canonical_json_bytes(value).decode("utf-8"))
            + "</pre></section>"
            for name, value in model.sections.items()
        )
        rendered = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="report-renderer" content="'
            + html.escape(self._renderer_version)
            + '"><title>CanopyLedger Committee Pack</title></head><body>'
            "<header><h1>CanopyLedger Committee Pack</h1><p>"
            + html.escape(model.package_kind.value)
            + "</p><code>"
            + html.escape(model.digest)
            + "</code></header>"
            + section_html
            + "</body></html>"
        ).encode("utf-8")
        return self._artifact(ReportArtifactFormat.HTML, model, rendered)

    def render_pdf(self, model: ReportModel) -> RenderedReportArtifact:
        """Render a byte-stable local PDF whose metadata is normalized to epoch values."""
        self._verify_environment(model)
        assert self._font_bytes is not None
        # The page references an embedded, pinned font stream.  No system font is requested,
        # so a renderer cannot silently change a committee pack through font fallback.
        lines = [
            "CanopyLedger Committee Pack",
            model.package_kind.value,
            f"Report model: {model.digest}",
            f"Pinned font: {self._font_digest}",
        ]
        content = (
            "BT /F1 12 Tf 72 760 Td "
            + " Tj T* ".join(f"({_pdf_escape(line)})" for line in lines)
            + " Tj ET"
        )
        pdf = _minimal_pdf(content.encode("ascii"), self._font_bytes)
        return self._artifact(ReportArtifactFormat.PDF, model, pdf)

    def _verify_environment(self, model: ReportModel) -> None:
        renderer = model.artifact_manifest.get("renderer")
        if not isinstance(renderer, dict):
            raise ValueError("report model is missing a renderer manifest")
        if self._font_bytes is None:
            raise MissingPinnedFont("pinned report font is unavailable")
        actual_font_digest = "sha256:" + hashlib.sha256(self._font_bytes).hexdigest()
        if actual_font_digest != self._font_digest:
            raise MissingPinnedFont("pinned report font digest does not match supplied bytes")
        expected = {
            "renderer": self._renderer_version,
            "font_digest": self._font_digest,
            "locale": self._locale,
            "timezone": self._timezone,
        }
        if renderer != expected:
            raise ValueError("renderer environment does not match the report model manifest")

    def _artifact(
        self, format: ReportArtifactFormat, model: ReportModel, rendered: bytes
    ) -> RenderedReportArtifact:
        metadata = {
            "creation_date": "D:19700101000000Z",
            "modification_date": "D:19700101000000Z",
            "font_digest": self._font_digest,
            "locale": self._locale,
            "renderer": self._renderer_version,
            "timezone": self._timezone,
        }
        digest_payload = canonical_json_bytes(
            {
                "format": format.value,
                "report_model_digest": model.digest,
                "rendered_bytes_sha256": hashlib.sha256(rendered).hexdigest(),
                "metadata": metadata,
            }
        )
        return RenderedReportArtifact(
            format=format,
            report_model_digest=model.digest,
            bytes=rendered,
            digest=domain_digest("report_artifact", 1, digest_payload),
            metadata=metadata,
        )


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _minimal_pdf(content: bytes, font_bytes: bytes) -> bytes:
    """Create a compact deterministic PDF with fixed object order and epoch metadata."""
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 6 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        (
            b"<< /Type /FontDescriptor /FontName /CanopyLedgerPinned /Flags 4 "
            b"/FontBBox [0 -200 1000 900] /FontFile2 7 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /CanopyLedgerPinned /FontDescriptor 5 0 R >>",
        (
            b"<< /Length "
            + str(len(font_bytes)).encode()
            + b" >>\nstream\n"
            + font_bytes
            + b"\nendstream"
        ),
        (
            b"<< /Producer (CanopyLedger) /CreationDate (D:19700101000000Z) "
            b"/ModDate (D:19700101000000Z) >>"
        ),
    )
    prefix = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray(prefix)
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(str(number).encode() + b" 0 obj\n" + value + b"\nendobj\n")
    xref = len(body)
    body.extend(b"xref\n0 9\n0000000000 65535 f \n")
    body.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    body.extend(b"trailer\n<< /Size 9 /Root 1 0 R /Info 8 0 R >>\nstartxref\n")
    body.extend(str(xref).encode() + b"\n%%EOF\n")
    return bytes(body)
