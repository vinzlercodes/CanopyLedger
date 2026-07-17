"""PostgreSQL persistence adapter for immutable M10 report packages."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from canopyledger.persistence.schema import report_artifact, report_model
from canopyledger.reporting.core import (
    ReportCompileInput,
    ReportModel,
    ReportModelCompiler,
    ReportPackageKind,
)
from canopyledger.reporting.rendering import (
    PinnedReportRenderer,
    RenderedReportArtifact,
    ReportArtifactFormat,
)
from canopyledger.reporting.service import ReportPackage


class PostgresReportService:
    """Writes report models/artifacts append-only and verifies retry identity by digest."""

    def __init__(
        self, engine: Engine, *, compiler: ReportModelCompiler, renderer: PinnedReportRenderer
    ) -> None:
        self._engine = engine
        self._compiler = compiler
        self._renderer = renderer

    def generate(self, source: ReportCompileInput) -> ReportPackage:
        model = self._compiler.compile(source)
        package = ReportPackage(
            report_model=model,
            artifacts=(self._renderer.render_html(model), self._renderer.render_pdf(model)),
        )
        with self._engine.begin() as connection:
            _insert_or_verify(
                connection,
                report_model,
                {
                    "resource_id": model.resource_id,
                    "snapshot_id": model.snapshot_id,
                    "decision_id": model.decision_id,
                    "package_kind": model.package_kind.value,
                    "canonical_payload": model.canonical_json,
                    "digest": model.digest,
                    "created_at": source.created_at,
                },
            )
            for artifact in package.artifacts:
                _insert_or_verify(
                    connection,
                    report_artifact,
                    {
                        "resource_id": _artifact_id(model.resource_id, artifact.format),
                        "report_model_id": model.resource_id,
                        "artifact_format": artifact.format.value,
                        "rendered_bytes": artifact.bytes,
                        "metadata": artifact.metadata,
                        "digest": artifact.digest,
                        "created_at": source.created_at,
                    },
                )
        return package

    def get(self, report_id: str) -> ReportPackage:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(report_model).where(report_model.c.resource_id == report_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KeyError("report package not found")
            artifacts = (
                connection.execute(
                    select(report_artifact)
                    .where(report_artifact.c.report_model_id == report_id)
                    .order_by(report_artifact.c.artifact_format)
                )
                .mappings()
                .all()
            )
        return _package_from_rows(row, artifacts)

    def list_for_decision(self, decision_id: str) -> tuple[ReportPackage, ...]:
        with self._engine.connect() as connection:
            models = (
                connection.execute(
                    select(report_model)
                    .where(report_model.c.decision_id == decision_id)
                    .order_by(report_model.c.created_at, report_model.c.resource_id)
                )
                .mappings()
                .all()
            )
            if not models:
                return ()
            artifacts = (
                connection.execute(
                    select(report_artifact)
                    .where(
                        report_artifact.c.report_model_id.in_(
                            [str(item["resource_id"]) for item in models]
                        )
                    )
                    .order_by(report_artifact.c.report_model_id, report_artifact.c.artifact_format)
                )
                .mappings()
                .all()
            )
        by_model: dict[str, list[Any]] = {}
        for artifact in artifacts:
            by_model.setdefault(str(artifact["report_model_id"]), []).append(artifact)
        return tuple(
            _package_from_rows(item, by_model.get(str(item["resource_id"]), [])) for item in models
        )


def _insert_or_verify(connection: Any, table: Any, values: dict[str, Any]) -> None:
    inserted = connection.execute(
        postgres_insert(table).values(**values).on_conflict_do_nothing().returning(table.c.digest)
    ).scalar_one_or_none()
    if inserted is None:
        existing = connection.execute(
            select(table.c.digest).where(table.c.resource_id == values["resource_id"])
        ).scalar_one_or_none()
        if existing != values["digest"]:
            raise ValueError("immutable report resource conflicts with existing content")


def _package_from_rows(model_row: Any, artifact_rows: Sequence[Any]) -> ReportPackage:
    payload = json.loads(bytes(model_row["canonical_payload"]))
    model = ReportModel(
        resource_id=str(payload["resource_id"]),
        package_kind=ReportPackageKind(str(payload["package_kind"])),
        snapshot_id=str(payload["snapshot_id"]),
        decision_id=str(payload["decision_id"]),
        sections=dict(payload["sections"]),
        artifact_manifest=dict(payload["artifact_manifest"]),
        canonical_json=bytes(model_row["canonical_payload"]),
        digest=str(model_row["digest"]),
    )
    artifacts = tuple(
        RenderedReportArtifact(
            format=ReportArtifactFormat(str(row["artifact_format"])),
            report_model_digest=model.digest,
            bytes=bytes(row["rendered_bytes"]),
            digest=str(row["digest"]),
            metadata=dict(row["metadata"]),
        )
        for row in artifact_rows
    )
    return ReportPackage(report_model=model, artifacts=artifacts)


def _artifact_id(report_id: str, format: ReportArtifactFormat) -> str:
    return f"rpa_{report_id[4:]}_{format.value.lower()}"
