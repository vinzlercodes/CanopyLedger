"""M5 deterministic climate/EUDR controls and financed-emissions tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from canopyledger.climate.engine import (
    ClimateEudrInput,
    ClimateIndicator,
    ClimateScenario,
    FinancedEmissionsInput,
    assess_climate_eudr,
)
from canopyledger.climate.eudr import (
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceNodeType,
    EvidenceStatus,
    LegalInterpretationPolicy,
    TraceabilityLot,
)
from canopyledger.climate.geometry import GeographicPoint, GeographicPolygon
from canopyledger.climate.pipeline import build_climate_eudr_stage_output
from canopyledger.climate.postgres import (
    ClimateEudrPersistenceError,
    PostgresClimateEudrRunner,
)
from canopyledger.climate.providers import ReferenceClimateDataProvider
from canopyledger.integrity.snapshot import (
    BundleReference,
    SnapshotInputReference,
    SnapshotManifest,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
LEGAL = LegalInterpretationPolicy(
    bundle_version="legal-eudr-v1",
    production_cutoff=date(2020, 12, 31),
    evidence_freshness_days=90,
    country_risk_reference_version="country-risk-2026-q3",
)


def _node(kind: EvidenceNodeType, suffix: str) -> EvidenceGraphNode:
    return EvidenceGraphNode(
        node_id=f"{kind.value}-{suffix}",
        node_type=kind,
        approved_fact_id=f"apf_0198a000-0000-7000-8000-000000000{suffix}",
        approved_fact_digest="sha256:" + suffix[-1] * 64,
        document_version_id=f"doc_0198a000-0000-7000-8000-000000000{suffix}",
        document_byte_digest="sha256:" + ("a" if suffix[-1] == "0" else suffix[-1]) * 64,
    )


def _graph() -> EvidenceGraph:
    kinds = tuple(EvidenceNodeType)
    nodes = tuple(_node(kind, str(index + 1).zfill(3)) for index, kind in enumerate(kinds))
    return EvidenceGraph(
        nodes=nodes,
        edges=tuple(
            EvidenceGraphEdge(source_id=nodes[index].node_id, target_id=nodes[index + 1].node_id)
            for index in range(len(nodes) - 1)
        ),
    )


def _lot(
    *,
    geometry: GeographicPoint | GeographicPolygon | None = None,
    production_date: date | None = date(2020, 12, 31),
) -> TraceabilityLot:
    return TraceabilityLot(
        lot_id="lot_0198a000-0000-7000-8000-000000000501",
        origin_country="BR",
        geometry=geometry
        or GeographicPoint(longitude=Decimal("-47.8825"), latitude=Decimal("-15.7942")),
        production_date=production_date,
        country_risk_reference="country-risk-2026-q3",
        evidence_document_digest="sha256:" + "a" * 64,
        evidence_recorded_at=datetime(2026, 6, 20, tzinfo=UTC),
        graph=_graph(),
    )


def _input(*, lot: TraceabilityLot | None = None) -> ClimateEudrInput:
    return ClimateEudrInput(
        assessment_id="clm_0198a000-0000-7000-8000-000000000501",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000501",
        legal_interpretation_bundle_digest="sha256:" + "b" * 64,
        policy_bundle_digest="sha256:" + "c" * 64,
        computation_bundle_digest="sha256:" + "d" * 64,
        legal_policy=LEGAL,
        traceability_lots=(lot or _lot(),),
        climate_indicators=(
            ClimateIndicator(
                origin_country="BR",
                indicator="drought_index",
                value=Decimal("0.62"),
                unit="index",
                observed_at=date(2026, 6, 30),
                provider_id="fixture-climate-provider",
                source_digest="sha256:" + "e" * 64,
            ),
        ),
        climate_scenarios=(
            ClimateScenario(
                scenario_id="drought-stress",
                family="physical_risk",
                yield_shock=Decimal("-0.12"),
                quality_shock=Decimal("-0.04"),
                shipment_delay_days=7,
                evidence_cost=Decimal("1250.00"),
                currency="USD",
            ),
        ),
        financed_emissions=FinancedEmissionsInput(
            borrower_scope_1=Decimal("120.0"),
            borrower_scope_2=Decimal("80.0"),
            borrower_scope_3=Decimal("300.0"),
            attribution_numerator=Decimal("2.5"),
            attribution_denominator=Decimal("10.0"),
            methodology_version="pcaf-fixture-v1",
            data_quality_score=2,
            source_period="2025",
            estimation_method="reported",
            restatement_lineage="emissions-restatement-2026-01",
        ),
    )


def test_m5_assessment_is_repeatable_and_reports_evidence_not_a_legal_conclusion() -> None:
    first = assess_climate_eudr(_input(), completed_at=NOW)
    second = assess_climate_eudr(_input(), completed_at=NOW)

    assert first.to_canonical_dict() == second.to_canonical_dict()
    assert first.eudr_evidence_state == EvidenceStatus.COMPLETE
    assert first.result["eudr_evidence_state"] == "complete"
    assert "compliant" not in str(first.to_canonical_dict()).lower()
    assert first.result["traceability"]["lots"][0]["production_date_class"] == "on_or_after_cutoff"
    assert first.result["financed_emissions"]["scope_1"] == "30.000000"
    assert first.result["financed_emissions"]["total_available"] == "125.000000"
    assert (
        first.result["financed_emissions"]["restatement_lineage"]
        == "emissions-restatement-2026-01"
    )
    assert first.output_digest.startswith("sha256:")


def test_geometry_rejects_wrong_crs_ranges_self_intersections_and_antimeridian_crossings() -> None:
    with pytest.raises(ValueError, match="EPSG:4326"):
        GeographicPoint(longitude=Decimal("0"), latitude=Decimal("0"), crs="EPSG:3857")
    with pytest.raises(ValueError, match="longitude"):
        GeographicPoint(longitude=Decimal("181"), latitude=Decimal("0"))
    with pytest.raises(ValueError, match="self-intersecting"):
        GeographicPolygon(
            coordinates=(
                (Decimal("0"), Decimal("0")),
                (Decimal("1"), Decimal("1")),
                (Decimal("0"), Decimal("1")),
                (Decimal("1"), Decimal("0")),
                (Decimal("0"), Decimal("0")),
            )
        )


def test_traceability_geometries_serialize_to_explicit_wgs84_wkt() -> None:
    assert GeographicPoint(Decimal("1.25"), Decimal("2.5")).to_wkt() == "POINT(1.25 2.5)"
    assert GeographicPolygon(
        coordinates=(
            (Decimal("0"), Decimal("0")),
            (Decimal("1"), Decimal("0")),
            (Decimal("0"), Decimal("1")),
            (Decimal("0"), Decimal("0")),
        )
    ).to_wkt() == "POLYGON((0 0, 1 0, 0 1, 0 0))"
    with pytest.raises(ValueError, match="antimeridian"):
        GeographicPolygon(
            coordinates=(
                (Decimal("179"), Decimal("0")),
                (Decimal("-179"), Decimal("1")),
                (Decimal("179"), Decimal("2")),
                (Decimal("179"), Decimal("0")),
            )
        )


def test_traceability_flags_missing_links_stale_evidence_and_unknown_production_date() -> None:
    graph = _graph()
    incomplete_graph = EvidenceGraph(nodes=graph.nodes[:-1], edges=graph.edges[:-1])
    lot = TraceabilityLot(
        lot_id="lot_0198a000-0000-7000-8000-000000000502",
        origin_country="BR",
        geometry=GeographicPoint(longitude=Decimal("-47.8825"), latitude=Decimal("-15.7942")),
        production_date=None,
        country_risk_reference=None,
        evidence_document_digest="sha256:" + "a" * 64,
        evidence_recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        graph=incomplete_graph,
    )

    result = assess_climate_eudr(_input(lot=lot), completed_at=NOW)

    assert result.eudr_evidence_state == EvidenceStatus.REVIEW_REQUIRED
    assert set(result.reason_codes) >= {
        "TRACEABILITY_MISSING_LINK",
        "PRODUCTION_DATE_NOT_REVIEWED",
        "COUNTRY_RISK_REFERENCE_MISSING",
        "TRACEABILITY_EVIDENCE_STALE",
    }
    assert result.result["traceability"]["lots"][0]["production_date_class"] == "not_reviewed"


def test_duplicate_origin_coordinates_are_explicitly_conflicting() -> None:
    duplicate = TraceabilityLot(
        lot_id="lot_0198a000-0000-7000-8000-000000000503",
        origin_country="BR",
        geometry=_lot().geometry,
        production_date=date(2020, 12, 30),
        country_risk_reference="country-risk-2026-q3",
        evidence_document_digest="sha256:" + "f" * 64,
        evidence_recorded_at=datetime(2026, 6, 20, tzinfo=UTC),
        graph=_graph(),
    )

    result = assess_climate_eudr(
        replace(_input(), traceability_lots=(_lot(), duplicate)), completed_at=NOW
    )

    assert result.eudr_evidence_state == EvidenceStatus.CONFLICTING
    assert "DUPLICATE_ORIGIN_COORDINATE" in result.reason_codes


def test_m5_stage_output_carries_frozen_input_and_every_bundle_digest() -> None:
    output = build_climate_eudr_stage_output(
        _input(),
        stage_output_id="out_0198a000-0000-7000-8000-000000000501",
        started_at=NOW,
        completed_at=NOW,
    )

    payload = output.to_canonical_dict()

    assert payload["stage"] == "climate_eudr"
    assert payload["input_digests"] == [
        _input().input_digest,
        "sha256:" + "b" * 64,
    ]
    assert payload["legal_interpretation_bundle_digest"] == "sha256:" + "b" * 64
    assert payload["policy_bundle_digest"] == "sha256:" + "c" * 64
    assert payload["computation_bundle_digest"] == "sha256:" + "d" * 64
    assert payload["result"]["eudr_evidence_state"] == "complete"
    assert payload["output_digest"].startswith("sha256:")


def test_m5_frozen_input_round_trips_exactly_from_its_canonical_projection() -> None:
    restored = ClimateEudrInput.from_frozen_input(_input().to_input_canonical_dict())

    assert restored.to_input_canonical_dict() == _input().to_input_canonical_dict()
    assert restored.input_digest == _input().input_digest


def test_m5_input_digest_excludes_snapshot_and_bundle_bindings_added_at_freeze() -> None:
    rebound = replace(
        _input(),
        snapshot_id="snp_0198a000-0000-7000-8000-000000000777",
        legal_interpretation_bundle_digest="sha256:" + "1" * 64,
        policy_bundle_digest="sha256:" + "2" * 64,
        computation_bundle_digest="sha256:" + "3" * 64,
    )

    assert rebound.input_digest == _input().input_digest
    assert rebound.to_input_canonical_dict()["snapshot_id"] != _input().to_input_canonical_dict()[
        "snapshot_id"
    ]


def test_reference_climate_provider_is_read_only_and_returns_pinned_observations() -> None:
    indicator = _input().climate_indicators[0]
    provider = ReferenceClimateDataProvider(
        provider_id="fixture-climate-provider", observations=(indicator,)
    )

    assert provider.observations_for("BR", as_of=date(2026, 6, 30)) == (indicator,)
    assert provider.observations_for("BR", as_of=date(2026, 6, 29)) == ()
    assert provider.observations_for("CO", as_of=date(2026, 6, 30)) == ()


def test_m5_evidence_graph_requires_approved_fact_snapshot_lineage() -> None:
    value = _input()
    manifest = SnapshotManifest(
        snapshot_id=value.snapshot_id,
        facility_id="fac_0198a000-0000-7000-8000-000000000501",
        facility_working_version=1,
        schema_version="1.0",
        as_of=NOW,
        market_bundle=BundleReference(
            resource_id="bnd_0198a000-0000-7000-8000-000000000501",
            digest="sha256:" + "1" * 64,
        ),
        policy_bundle=BundleReference(
            resource_id="bnd_0198a000-0000-7000-8000-000000000502",
            digest="sha256:" + "2" * 64,
        ),
        legal_interpretation_bundle=BundleReference(
            resource_id="bnd_0198a000-0000-7000-8000-000000000503",
            digest="sha256:" + "3" * 64,
        ),
        computation_bundle=BundleReference(
            resource_id="bnd_0198a000-0000-7000-8000-000000000504",
            digest="sha256:" + "4" * 64,
        ),
        inputs=(),
        created_by="act_0198a000-0000-7000-8000-000000000501",
        created_at=NOW,
    )

    with pytest.raises(ClimateEudrPersistenceError, match="approved snapshot facts"):
        PostgresClimateEudrRunner._verify_evidence_lineage(value, manifest)

    lineage = tuple(
        SnapshotInputReference(
            resource_type="approved_fact",
            resource_id=node.approved_fact_id,
            digest=node.approved_fact_digest,
        )
        for node in value.traceability_lots[0].graph.nodes
    )
    PostgresClimateEudrRunner._verify_evidence_lineage(
        value, manifest.model_copy(update={"inputs": lineage})
    )
