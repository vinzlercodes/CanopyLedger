"""Canonical M10 report-model compilation.

The report model is the authoritative reporting artifact.  It copies only
already-published decision inputs into a fixed section order; it never reads
working state or recalculates CBB, IRC, hedge, scenario, or decision values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from canopyledger.integrity.canonical import (
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)


class ReportIneligible(ValueError):
    """Raised when a decision cannot produce the requested report package."""


class ReportPackageKind(StrEnum):
    """The reader-visible designation of an immutable report package."""

    CURRENT_OFFICIAL = "CURRENT_OFFICIAL"
    HISTORICAL_AUDIT = "HISTORICAL_AUDIT"


@dataclass(frozen=True)
class ReportCompileInput:
    """Pinned immutable inputs required to compile one report model."""

    report_id: str
    package_kind: ReportPackageKind
    decision: Mapping[str, Any]
    snapshot: Mapping[str, Any]
    decision_pack: Mapping[str, Any]
    stage_outputs: Mapping[str, Mapping[str, Any]]
    template_version: str
    renderer_manifest: Mapping[str, str]
    created_at: datetime


@dataclass(frozen=True)
class ReportModel:
    """Canonical JSON and its immutable report-model digest."""

    resource_id: str
    package_kind: ReportPackageKind
    snapshot_id: str
    decision_id: str
    sections: Mapping[str, Mapping[str, Any]]
    artifact_manifest: Mapping[str, Any]
    canonical_json: bytes
    digest: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "schema_version": "report-model-v2",
            "package_kind": self.package_kind.value,
            "snapshot_id": self.snapshot_id,
            "decision_id": self.decision_id,
            "sections": self.sections,
            "artifact_manifest": self.artifact_manifest,
        }


class ReportModelCompiler:
    """Compiles a fixed, source-only committee-pack model from immutable inputs."""

    def compile(self, source: ReportCompileInput) -> ReportModel:
        """Produce a canonical model after enforcing decision/report designation rules."""
        decision_id = _required_text(source.decision, "resource_id", "decision")
        snapshot_id = _required_text(source.decision, "snapshot_id", "decision")
        if snapshot_id != _required_text(source.snapshot, "snapshot_id", "snapshot"):
            raise ReportIneligible("decision and snapshot lineage differ")
        if _required_text(source.decision, "status", "decision") != "APPROVED":
            raise ReportIneligible("only approved final decisions can produce a report")
        if (
            source.package_kind is ReportPackageKind.CURRENT_OFFICIAL
            and source.decision.get("superseded_by") is not None
        ):
            raise ReportIneligible("superseded decision cannot produce a current official report")
        if not source.report_id or not source.template_version:
            raise ReportIneligible("report identity and pinned template are required")
        _required_text(source.renderer_manifest, "renderer", "renderer manifest")
        _required_text(source.renderer_manifest, "font_digest", "renderer manifest")
        _required_text(source.renderer_manifest, "locale", "renderer manifest")
        _required_text(source.renderer_manifest, "timezone", "renderer manifest")

        recommendation = _required_mapping(source.decision_pack, "recommendation", "decision pack")
        final_decision = _required_mapping(source.decision_pack, "final_decision", "decision pack")
        collateral = _required_mapping(source.stage_outputs, "collateral", "stage outputs")
        hedge = _required_mapping(source.stage_outputs, "hedge", "stage outputs")
        scenario = _required_mapping(source.stage_outputs, "scenario", "stage outputs")
        climate = _required_mapping(source.stage_outputs, "climate", "stage outputs")
        credit = _required_mapping(source.stage_outputs, "credit", "stage outputs")

        # Each section copies a versioned source verbatim.  The intentional duplication
        # gives committee readers the fixed plan-defined order without giving renderers
        # permission to derive, aggregate, or otherwise recalculate a reported value.
        sections: dict[str, Mapping[str, Any]] = {
            "facility_summary": {
                "snapshot_id": snapshot_id,
                "snapshot_digest": _required_text(source.snapshot, "digest", "snapshot"),
                "as_of": _required_text(source.snapshot, "as_of", "snapshot"),
            },
            "requested_and_approved_amount": {
                "recommendation": recommendation,
                "final_decision": final_decision,
            },
            "contractual_borrowing_base": _required_mapping(
                source.decision_pack, "contractual_borrowing_base", "decision pack"
            ),
            "inventory_and_receivables_eligibility": collateral,
            "reserves": collateral,
            "hedge_and_basis_exposure": hedge,
            "variation_margin_liquidity": hedge,
            "scenario_results": scenario,
            "internal_risk_capacity": _required_mapping(
                source.decision_pack, "internal_risk_capacity", "decision pack"
            ),
            "credit_early_warning_signal": credit,
            "climate_and_eudr_evidence_state": climate,
            "financed_emissions_information": climate,
            "recommendation": recommendation,
            "approval_or_override": {
                "final_decision": final_decision,
                "decision": dict(source.decision),
            },
            "conditions_and_expiry": {
                "recommendation": recommendation,
                "final_decision": final_decision,
            },
            "data_and_methodology_limitations": {
                "notice": (
                    "Values are copied from pinned immutable outputs; "
                    "renderers do not recalculate them."
                )
            },
        }

        manifest: dict[str, Any] = {
            "report_model_digest_algorithm": "canopyledger:report_model:v1",
            "template_version": source.template_version,
            "renderer": dict(source.renderer_manifest),
            "decision_digest": _required_text(source.decision, "digest", "decision"),
            "snapshot_digest": _required_text(source.snapshot, "digest", "snapshot"),
            "policy_bundle_digest": _nested_text(source.snapshot, "policy_bundle", "digest"),
            "computation_bundle_digest": _nested_text(
                source.snapshot, "computation_bundle", "digest"
            ),
            "stage_output_digests": {
                name: _required_text(output, "output_digest", f"{name} stage")
                for name, output in sorted(source.stage_outputs.items())
            },
            "compiled_at": canonical_timestamp(source.created_at),
        }
        payload = {
            "resource_id": source.report_id,
            "schema_version": "report-model-v2",
            "package_kind": source.package_kind.value,
            "snapshot_id": snapshot_id,
            "decision_id": decision_id,
            "sections": sections,
            "artifact_manifest": manifest,
        }
        canonical_json = canonical_json_bytes(payload)
        return ReportModel(
            resource_id=source.report_id,
            package_kind=source.package_kind,
            snapshot_id=snapshot_id,
            decision_id=decision_id,
            sections=sections,
            artifact_manifest=manifest,
            canonical_json=canonical_json,
            digest=domain_digest("report_model", 2, canonical_json),
        )


def _required_text(source: Mapping[str, Any], key: str, label: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ReportIneligible(f"{label} requires {key}")
    return value


def _required_mapping(source: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise ReportIneligible(f"{label} requires {key}")
    return value


def _nested_text(source: Mapping[str, Any], parent: str, key: str) -> str:
    return _required_text(_required_mapping(source, parent, "snapshot"), key, parent)
