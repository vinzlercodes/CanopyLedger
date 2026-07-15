"""PostgreSQL acceptance gate for frozen M5 climate/EUDR evidence readiness."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from test_m1b_postgres_pipeline import ACTOR_ID, _freeze_snapshot

from canopyledger.application.integrity import IntegrityService
from canopyledger.climate.engine import (
    ClimateEudrInput,
    ClimateIndicator,
    ClimateScenario,
    FinancedEmissionsInput,
)
from canopyledger.climate.eudr import (
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceNodeType,
    LegalInterpretationPolicy,
    TraceabilityLot,
)
from canopyledger.climate.geometry import GeographicPoint
from canopyledger.climate.postgres import (
    PostgresClimateEudrInputStore,
    PostgresClimateEudrRunner,
)
from canopyledger.integrity.bundles import BundleType
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import pipeline_stage_output

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _input() -> ClimateEudrInput:
    nodes = tuple(
        EvidenceGraphNode(
            node_id=kind.value,
            node_type=kind,
            approved_fact_id=f"apf_0198a000-0000-7000-8000-000000000{index:03d}",
            approved_fact_digest=f"sha256:{index:064x}",
            document_version_id=f"doc_0198a000-0000-7000-8000-000000000{index:03d}",
            document_byte_digest=f"sha256:{index + 16:064x}",
        )
        for index, kind in enumerate(EvidenceNodeType, start=1)
    )
    graph = EvidenceGraph(
        nodes=nodes,
        edges=tuple(
            EvidenceGraphEdge(source_id=nodes[index].node_id, target_id=nodes[index + 1].node_id)
            for index in range(len(nodes) - 1)
        ),
    )
    return ClimateEudrInput(
        assessment_id="clm_0198a000-0000-7000-8000-000000000501",
        snapshot_id="snp_0198a000-0000-7000-8000-000000000501",
        legal_interpretation_bundle_digest="sha256:" + "b" * 64,
        policy_bundle_digest="sha256:" + "c" * 64,
        computation_bundle_digest="sha256:" + "d" * 64,
        legal_policy=LegalInterpretationPolicy(
            bundle_version="legal-eudr-v1",
            production_cutoff=date(2020, 12, 31),
            evidence_freshness_days=90,
            country_risk_reference_version="country-risk-2026-q3",
        ),
        traceability_lots=(
            TraceabilityLot(
                lot_id="lot_0198a000-0000-7000-8000-000000000501",
                origin_country="BR",
                geometry=GeographicPoint(Decimal("-47.8825"), Decimal("-15.7942")),
                production_date=date(2020, 12, 31),
                country_risk_reference="country-risk-2026-q3",
                evidence_document_digest="sha256:" + "a" * 64,
                evidence_recorded_at=datetime(2026, 6, 20, tzinfo=UTC),
                graph=graph,
            ),
        ),
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


def test_m5_persists_postgis_geometry_and_publishes_only_from_frozen_lineage(
    database_engine: Engine,
) -> None:
    integrity = PostgresIntegrityStore(database_engine)
    input_store = PostgresClimateEudrInputStore(database_engine)
    draft = _input()
    stored = input_store.publish(draft, created_by=ACTOR_ID, created_at=NOW)
    snapshot_id, bundles = _freeze_snapshot(
        IntegrityService(
            integrity,
            clock=lambda: NOW,
            snapshot_input_validators={
                "climate_eudr_input": input_store.validate_snapshot_reference
            },
        ),
        integrity,
        inputs=(
            SnapshotInputReference(
                resource_type="climate_eudr_input",
                resource_id=draft.assessment_id,
                digest=stored.digest,
            ),
            *(
                SnapshotInputReference(
                    resource_type="approved_fact",
                    resource_id=node.approved_fact_id,
                    digest=node.approved_fact_digest,
                )
                for node in draft.traceability_lots[0].graph.nodes
            ),
        ),
        bundle_payloads={
            BundleType.LEGAL_INTERPRETATION: {
                "climate_eudr": draft.legal_policy.to_canonical_dict()
            },
            BundleType.POLICY: {
                "climate_eudr": {
                    "evidence_freshness_days": draft.legal_policy.evidence_freshness_days,
                    "country_risk_reference_version": (
                        draft.legal_policy.country_risk_reference_version
                    ),
                }
            },
            BundleType.COMPUTATION: {
                "climate_eudr": {
                    "geometry_validation_version": "1.0.0",
                    "financed_emissions_methodology_version": (
                        draft.financed_emissions.methodology_version
                    ),
                }
            },
        },
    )

    published = PostgresClimateEudrRunner(
        database_engine, integrity, input_store, clock=lambda: NOW
    ).publish(snapshot_id, draft.assessment_id, worker_id="climate-worker")

    assert published.snapshot_id == snapshot_id
    assert published.result["eudr_evidence_state"] == "complete"
    assert (
        published.legal_interpretation_bundle_digest
        == bundles[BundleType.LEGAL_INTERPRETATION].digest
    )
    with database_engine.connect() as connection:
        geometry = connection.execute(
            text(
                """
                SELECT ST_SRID(geometry), ST_IsValid(geometry), ST_IsSimple(geometry)
                FROM canopyledger.climate_traceability_geometry
                WHERE climate_input_id = :input_id
                """
            ),
            {"input_id": draft.assessment_id},
        ).one()
        output_count = connection.execute(
            select(func.count())
            .select_from(pipeline_stage_output)
            .where(pipeline_stage_output.c.snapshot_id == snapshot_id)
        ).scalar_one()
    assert geometry == (4326, True, True)
    assert output_count == 1

    with (
        pytest.raises(DBAPIError, match="climate_geometry_type"),
        database_engine.begin() as connection,
    ):
        connection.execute(
            text(
                """
                INSERT INTO canopyledger.climate_traceability_geometry
                    (climate_input_id, lot_id, geometry, geometry_digest)
                VALUES (
                    :input_id,
                    'lot_0198a000-0000-7000-8000-000000000999',
                    ST_GeomFromText('LINESTRING(0 0, 1 1)', 4326),
                    :digest
                )
                """
            ),
            {"input_id": draft.assessment_id, "digest": "sha256:" + "9" * 64},
        )
