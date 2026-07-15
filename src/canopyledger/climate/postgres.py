"""Durable frozen M5 climate/EUDR inputs and fenced publication."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError

from canopyledger.application.models import StagePublicationData
from canopyledger.climate.engine import ClimateEudrError, ClimateEudrInput
from canopyledger.climate.pipeline import ClimateEudrStageOutput, build_climate_eudr_stage_output
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import SnapshotInputReference, SnapshotManifest
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    climate_eudr_input,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_output,
)


class ClimateEudrPersistenceError(ClimateEudrError):
    """Raised when frozen M5 lineage or output publication is invalid."""


@dataclass(frozen=True)
class StoredClimateEudrInput:
    resource_id: str
    digest: str
    canonical_payload: bytes


class PostgresClimateEudrInputStore:
    """Store canonical M5 source data before a snapshot pins its digest."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(
        self, value: ClimateEudrInput, *, created_by: str, created_at: datetime
    ) -> StoredClimateEudrInput:
        stored = StoredClimateEudrInput(
            value.assessment_id,
            value.input_digest,
            canonical_json_bytes(value.to_stored_input_canonical_dict()),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(climate_eudr_input).values(
                        resource_id=stored.resource_id,
                        digest=stored.digest,
                        canonical_payload=stored.canonical_payload,
                        created_by=created_by,
                        created_at=created_at,
                    )
                )
                for lot in value.traceability_lots:
                    connection.execute(
                        text(
                            """
                            INSERT INTO canopyledger.climate_traceability_geometry
                                (climate_input_id, lot_id, geometry, geometry_digest)
                            VALUES (
                                :climate_input_id,
                                :lot_id,
                                ST_GeomFromText(:geometry_wkt, 4326),
                                :geometry_digest
                            )
                            """
                        ),
                        {
                            "climate_input_id": stored.resource_id,
                            "lot_id": lot.lot_id,
                            "geometry_wkt": lot.geometry.to_wkt(),
                            "geometry_digest": domain_digest(
                                "traceability_geometry",
                                1,
                                canonical_json_bytes(lot.geometry.to_canonical_dict()),
                            ),
                        },
                    )
        except IntegrityError:
            if self.load(stored.resource_id) != stored:
                raise ClimateEudrPersistenceError(
                    "climate/EUDR input ID already has different immutable content"
                ) from None
        return stored

    def load(self, resource_id: str) -> StoredClimateEudrInput | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(climate_eudr_input).where(
                        climate_eudr_input.c.resource_id == resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        payload = bytes(row["canonical_payload"])
        digest = domain_digest("climate_eudr_input", 1, payload)
        if digest != row["digest"]:
            raise ClimateEudrPersistenceError("stored climate/EUDR input digest mismatch")
        return StoredClimateEudrInput(str(row["resource_id"]), str(row["digest"]), payload)

    def load_value(
        self,
        resource_id: str,
        *,
        snapshot_id: str,
        legal_interpretation_bundle_digest: str,
        policy_bundle_digest: str,
        computation_bundle_digest: str,
    ) -> ClimateEudrInput | None:
        stored = self.load(resource_id)
        if stored is None:
            return None
        try:
            decoded = json.loads(stored.canonical_payload)
            if not isinstance(decoded, dict):
                raise ValueError("stored climate/EUDR input must be an object")
            value = ClimateEudrInput.from_frozen_input(
                decoded,
                snapshot_id=snapshot_id,
                legal_interpretation_bundle_digest=legal_interpretation_bundle_digest,
                policy_bundle_digest=policy_bundle_digest,
                computation_bundle_digest=computation_bundle_digest,
            )
        except (ClimateEudrError, TypeError, ValueError) as exc:
            raise ClimateEudrPersistenceError("stored climate/EUDR input is malformed") from exc
        if value.input_digest != stored.digest:
            raise ClimateEudrPersistenceError("stored climate/EUDR input is not canonical")
        return value

    def validate_snapshot_reference(self, reference: SnapshotInputReference) -> None:
        if reference.resource_type != "climate_eudr_input":
            raise ClimateEudrPersistenceError("invalid climate/EUDR input reference type")
        stored = self.load(reference.resource_id)
        if stored is None or stored.digest != reference.digest:
            raise ClimateEudrPersistenceError(
                "climate/EUDR snapshot input is absent or digest-mismatched"
            )


class PostgresClimateEudrRunner:
    """Publish exactly one M5 result after verifying frozen source and bundle lineage."""

    def __init__(
        self,
        engine: Engine,
        store: PostgresIntegrityStore,
        input_store: PostgresClimateEudrInputStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._engine, self._store, self._input_store, self._clock, self._id_factory = (
            engine,
            store,
            input_store,
            clock,
            id_factory,
        )

    def publish(
        self, snapshot_id: str, climate_input_id: str, *, worker_id: str
    ) -> ClimateEudrStageOutput:
        value = self._load_frozen_execution_input(snapshot_id, climate_input_id)
        now = self._clock()
        output = build_climate_eudr_stage_output(
            value, stage_output_id=self._id_factory("out"), started_at=now, completed_at=now
        )
        run_id = self._create_run(value, output, now)
        lease = self._store.claim_stage(
            worker_id=worker_id,
            now=now,
            lease_duration=timedelta(minutes=5),
            maximum_lease_lifetime=timedelta(minutes=5),
            attempt_id=self._id_factory("att"),
            pipeline_run_id=run_id,
        )
        if lease is None:
            raise ClimateEudrPersistenceError("M5 climate/EUDR stage was not claimable")
        published = self._store.publish_stage(
            StagePublicationData(
                stage_id=lease.stage_id,
                worker_id=worker_id,
                epoch=lease.epoch,
                input_digest=lease.input_digest,
                output_schema_version="climate-eudr-stage-output-v1",
                canonical_output=canonical_json_bytes(_stage_payload(output)),
                output_digest=output.output_digest,
                output_id=output.stage_output_id,
                outbox_message_id=self._id_factory("msg"),
                audit_event_id=self._id_factory("aud"),
                published_at=now + timedelta(seconds=1),
            )
        )
        if published.output_digest != output.output_digest:
            raise ClimateEudrPersistenceError("M5 published output digest mismatch")
        return output

    def load_published_output(self, snapshot_id: str) -> dict[str, object] | None:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        pipeline_stage_output.c.canonical_output,
                        pipeline_stage_output.c.output_digest,
                    )
                    .where(pipeline_stage_output.c.snapshot_id == snapshot_id)
                    .order_by(pipeline_stage_output.c.published_at.desc())
                )
                .mappings()
                .all()
            )
        for row in rows:
            payload = json.loads(bytes(row["canonical_output"]))
            if isinstance(payload, dict) and payload.get("stage") == "climate_eudr":
                payload["output_digest"] = str(row["output_digest"])
                return cast(dict[str, object], payload)
        return None

    def _load_frozen_execution_input(
        self, snapshot_id: str, climate_input_id: str
    ) -> ClimateEudrInput:
        snapshot = self._store.get_snapshot_manifest(snapshot_id)
        if snapshot is None:
            raise ClimateEudrPersistenceError("frozen snapshot does not exist")
        manifest = snapshot.manifest
        references = [
            item
            for item in manifest.inputs
            if item.resource_type == "climate_eudr_input" and item.resource_id == climate_input_id
        ]
        value = self._input_store.load_value(
            climate_input_id,
            snapshot_id=snapshot_id,
            legal_interpretation_bundle_digest=manifest.legal_interpretation_bundle.digest,
            policy_bundle_digest=manifest.policy_bundle.digest,
            computation_bundle_digest=manifest.computation_bundle.digest,
        )
        if len(references) != 1 or value is None or references[0].digest != value.input_digest:
            raise ClimateEudrPersistenceError("frozen climate/EUDR input is absent or altered")
        self._verify_evidence_lineage(value, manifest)
        self._verify_bundle_payloads(value, manifest)
        return value

    @staticmethod
    def _verify_evidence_lineage(value: ClimateEudrInput, manifest: SnapshotManifest) -> None:
        """Require every M5 graph node to resolve to a pinned approved-fact digest."""
        frozen_facts = {
            (reference.resource_id, reference.digest)
            for reference in manifest.inputs
            if reference.resource_type == "approved_fact"
        }
        for lot in value.traceability_lots:
            for node in lot.graph.nodes:
                if (node.approved_fact_id, node.approved_fact_digest) not in frozen_facts:
                    raise ClimateEudrPersistenceError(
                        "climate/EUDR evidence graph is not pinned to approved snapshot facts"
                    )

    def _verify_bundle_payloads(self, value: ClimateEudrInput, manifest: SnapshotManifest) -> None:
        expected = (
            (
                manifest.legal_interpretation_bundle.resource_id,
                value.legal_policy.to_canonical_dict(),
            ),
            (
                manifest.policy_bundle.resource_id,
                {
                    "evidence_freshness_days": value.legal_policy.evidence_freshness_days,
                    "country_risk_reference_version": (
                        value.legal_policy.country_risk_reference_version
                    ),
                },
            ),
            (
                manifest.computation_bundle.resource_id,
                {
                    "geometry_validation_version": "1.0.0",
                    "financed_emissions_methodology_version": (
                        value.financed_emissions.methodology_version
                    ),
                },
            ),
        )
        for bundle_id, section in expected:
            bundle = self._store.load_bundle(bundle_id)
            if (
                bundle is None
                or not isinstance(bundle.payload, dict)
                or bundle.payload.get("climate_eudr") != section
            ):
                raise ClimateEudrPersistenceError(
                    "snapshot-pinned bundle lacks required M5 climate/EUDR data"
                )

    def _create_run(
        self, value: ClimateEudrInput, output: ClimateEudrStageOutput, now: datetime
    ) -> str:
        run_id = self._id_factory("run")
        input_digest = domain_digest(
            "climate_eudr_stage_input",
            1,
            canonical_json_bytes(
                {
                    "snapshot_id": value.snapshot_id,
                    "input_digests": list(output.input_digests),
                    "policy_bundle_digest": value.policy_bundle_digest,
                    "computation_bundle_digest": value.computation_bundle_digest,
                }
            ),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(pipeline_run).values(
                        resource_id=run_id,
                        snapshot_id=value.snapshot_id,
                        run_key=f"{value.snapshot_id}:climate_eudr:1.0.0",
                        input_digest=input_digest,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(pipeline_stage).values(
                        resource_id=self._id_factory("stg"),
                        pipeline_run_id=run_id,
                        stage_definition_id="climate_eudr",
                        status="PENDING",
                        input_digest=input_digest,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise ClimateEudrPersistenceError(
                "M5 climate/EUDR output already exists for this snapshot"
            ) from exc
        return run_id


def _stage_payload(stage_output: ClimateEudrStageOutput) -> dict[str, object]:
    payload = stage_output.to_canonical_dict()
    payload.pop("output_digest")
    return payload
