"""Frozen-input, fenced M4A scenario publication and separate IRC persistence."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from canopyledger.application.models import StagePublicationData
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import SnapshotInputReference, SnapshotManifest
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    internal_risk_capacity_assessment,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_output,
    scenario_capacity_input,
)
from canopyledger.scenario.engine import ScenarioCapacityError, ScenarioCapacityInput
from canopyledger.scenario.pipeline import (
    ScenarioCapacityStageOutput,
    build_scenario_capacity_stage_output,
)


class ScenarioCapacityPersistenceError(ScenarioCapacityError):
    """Raised when frozen M4A lineage or publication requirements are not met."""


@dataclass(frozen=True)
class StoredScenarioCapacityInput:
    resource_id: str
    digest: str
    canonical_payload: bytes


class PostgresScenarioCapacityInputStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(
        self, value: ScenarioCapacityInput, *, created_by: str, created_at: datetime
    ) -> StoredScenarioCapacityInput:
        stored = StoredScenarioCapacityInput(
            value.assessment_id,
            value.input_digest,
            canonical_json_bytes(value.to_input_canonical_dict()),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(scenario_capacity_input).values(
                        resource_id=stored.resource_id,
                        digest=stored.digest,
                        canonical_payload=stored.canonical_payload,
                        created_by=created_by,
                        created_at=created_at,
                    )
                )
        except IntegrityError:
            if self.load(stored.resource_id) != stored:
                raise ScenarioCapacityPersistenceError(
                    "scenario capacity input ID already has different immutable content"
                ) from None
        return stored

    def load(self, resource_id: str) -> StoredScenarioCapacityInput | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(scenario_capacity_input).where(
                        scenario_capacity_input.c.resource_id == resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        payload = bytes(row["canonical_payload"])
        digest = domain_digest("scenario_capacity_input", 1, payload)
        if digest != row["digest"]:
            raise ScenarioCapacityPersistenceError("stored scenario capacity input digest mismatch")
        return StoredScenarioCapacityInput(str(row["resource_id"]), str(row["digest"]), payload)

    def validate_snapshot_reference(self, reference: SnapshotInputReference) -> None:
        if reference.resource_type != "scenario_capacity_input":
            raise ScenarioCapacityPersistenceError("invalid scenario capacity input reference type")
        stored = self.load(reference.resource_id)
        if stored is None or stored.digest != reference.digest:
            raise ScenarioCapacityPersistenceError(
                "scenario capacity snapshot input is absent or digest-mismatched"
            )


class PostgresScenarioCapacityRunner:
    """Publish one fenced S6 output and a separately immutable IRC assessment."""

    def __init__(
        self,
        engine: Engine,
        store: PostgresIntegrityStore,
        input_store: PostgresScenarioCapacityInputStore,
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
        self, value: ScenarioCapacityInput, *, worker_id: str
    ) -> ScenarioCapacityStageOutput:
        self._verify_frozen_lineage(value)
        value = self._hydrate_authoritative_inputs(value)
        now = self._clock()
        output = build_scenario_capacity_stage_output(
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
            raise ScenarioCapacityPersistenceError("M4A scenario stage was not claimable")
        canonical = canonical_json_bytes(_stage_payload(output))
        published = self._store.publish_stage(
            StagePublicationData(
                stage_id=lease.stage_id,
                worker_id=worker_id,
                epoch=lease.epoch,
                input_digest=lease.input_digest,
                output_schema_version="scenario-capacity-stage-output-v1",
                canonical_output=canonical,
                output_digest=output.output_digest,
                output_id=output.stage_output_id,
                outbox_message_id=self._id_factory("msg"),
                audit_event_id=self._id_factory("aud"),
                published_at=now + timedelta(seconds=1),
            )
        )
        self._publish_irc(output, published.output_id, now)
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
            if isinstance(payload, dict) and payload.get("stage") == "scenario_capacity":
                payload["output_digest"] = str(row["output_digest"])
                return cast(dict[str, object], payload)
        return None

    def _verify_frozen_lineage(self, value: ScenarioCapacityInput) -> None:
        snapshot = self._store.get_snapshot_manifest(value.snapshot_id)
        if snapshot is None:
            raise ScenarioCapacityPersistenceError("frozen snapshot does not exist")
        refs = [
            item
            for item in snapshot.manifest.inputs
            if item.resource_type == "scenario_capacity_input"
            and item.resource_id == value.assessment_id
        ]
        stored = self._input_store.load(value.assessment_id)
        if (
            len(refs) != 1
            or stored is None
            or refs[0].digest != stored.digest
            or stored.digest != value.input_digest
        ):
            raise ScenarioCapacityPersistenceError(
                "frozen scenario capacity input is absent or altered"
            )
        if (
            snapshot.manifest.market_bundle.digest != value.market_bundle_digest
            or snapshot.manifest.policy_bundle.digest != value.policy_bundle_digest
            or snapshot.manifest.computation_bundle.digest != value.computation_bundle_digest
        ):
            raise ScenarioCapacityPersistenceError(
                "scenario capacity bundle digests do not match the frozen snapshot"
            )
        self._verify_bundle_payloads(value, snapshot.manifest)
        seen = self._published_stage_digests(value.snapshot_id)
        if (
            seen.get("contractual_borrowing_base") != value.cbb_output_digest
            or seen.get("hedge_liquidity") != value.hedge_liquidity_output_digest
        ):
            raise ScenarioCapacityPersistenceError(
                "M4A requires matching published CBB and hedge/liquidity outputs"
            )

    def _published_stage_digests(self, snapshot_id: str) -> dict[str, str]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        pipeline_stage_output.c.canonical_output,
                        pipeline_stage_output.c.output_digest,
                    ).where(pipeline_stage_output.c.snapshot_id == snapshot_id)
                )
                .mappings()
                .all()
            )
        values: dict[str, str] = {}
        for row in rows:
            payload = json.loads(bytes(row["canonical_output"]))
            if isinstance(payload, dict) and isinstance(payload.get("stage"), str):
                values[payload["stage"]] = str(row["output_digest"])
        return values

    def _verify_bundle_payloads(
        self, value: ScenarioCapacityInput, manifest: SnapshotManifest
    ) -> None:
        expected_sections = (
            ("market", manifest.market_bundle.resource_id, value.market_bundle_payload()),
            ("policy", manifest.policy_bundle.resource_id, value.policy_bundle_payload()),
            (
                "computation",
                manifest.computation_bundle.resource_id,
                value.computation_bundle_payload(),
            ),
        )
        for label, bundle_id, expected in expected_sections:
            bundle = self._store.load_bundle(bundle_id)
            if (
                bundle is None
                or not isinstance(bundle.payload, dict)
                or bundle.payload.get("scenario_capacity") != expected
            ):
                raise ScenarioCapacityPersistenceError(
                    f"frozen {label} bundle does not contain the required M4A scenario data"
                )

    def _hydrate_authoritative_inputs(self, value: ScenarioCapacityInput) -> ScenarioCapacityInput:
        """Derive CBB, exposure, and liquidity only from published predecessor outputs."""
        payloads = self._published_stage_payloads(value.snapshot_id)
        cbb = payloads.get("contractual_borrowing_base")
        hedge = payloads.get("hedge_liquidity")
        if cbb is None or hedge is None:
            raise ScenarioCapacityPersistenceError("M4A predecessor output payload is unavailable")
        try:
            cbb_result = cast(dict[str, object], cbb["result"])
            hedge_result = cast(dict[str, object], hedge["result"])
            assessment = cast(dict[str, object], hedge_result["assessment"])
            liquidity_values = cast(dict[str, object], assessment["liquidity"])
            exposure_values = cast(dict[str, object], assessment["exposure"])
            currency = str(cbb_result["currency"])
            exposure = sum(
                (
                    Decimal(str(cbb_result[name]))
                    for name in ("current_principal", "lc_exposure", "other_contractual_usage")
                ),
                Decimal(0),
            )
            return replace(
                value,
                cbb=Money(Decimal(str(cbb_result["contractual_borrowing_base"])), currency),
                facility_commitment=Money(Decimal(str(cbb_result["facility_limit"])), currency),
                outstanding_exposure=Money(exposure, currency),
                base_margin_call=Money(
                    Decimal(str(liquidity_values["multi_day_margin_stress"])), currency
                ),
                available_liquidity=Money(
                    Decimal(str(liquidity_values["total_liquidity_available"])), currency
                ),
                hedge_effectiveness=_hedge_effectiveness(exposure_values),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise ScenarioCapacityPersistenceError(
                "published M4A predecessor output is malformed"
            ) from exc

    def _published_stage_payloads(self, snapshot_id: str) -> dict[str, dict[str, object]]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(pipeline_stage_output.c.canonical_output).where(
                        pipeline_stage_output.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .all()
            )
        values: dict[str, dict[str, object]] = {}
        for row in rows:
            payload = json.loads(bytes(row["canonical_output"]))
            if isinstance(payload, dict) and isinstance(payload.get("stage"), str):
                values[payload["stage"]] = cast(dict[str, object], payload)
        return values

    def _create_run(
        self, value: ScenarioCapacityInput, output: ScenarioCapacityStageOutput, now: datetime
    ) -> str:
        run_id = self._id_factory("run")
        input_digest = domain_digest(
            "scenario_capacity_stage_input",
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
                        run_key=f"{value.snapshot_id}:scenario_capacity:1.0.0",
                        input_digest=input_digest,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(pipeline_stage).values(
                        resource_id=self._id_factory("stg"),
                        pipeline_run_id=run_id,
                        stage_definition_id="scenario_capacity",
                        status="PENDING",
                        input_digest=input_digest,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise ScenarioCapacityPersistenceError(
                "M4A scenario output already exists for this snapshot"
            ) from exc
        return run_id

    def _publish_irc(
        self, output: ScenarioCapacityStageOutput, output_id: str, now: datetime
    ) -> None:
        irc = output.internal_risk_capacity
        payload: dict[str, Any] = {
            "snapshot_id": output.snapshot_id,
            "scenario_stage_output_id": output_id,
            "cbb_output_digest": output.input_digests[0],
            "internal_risk_capacity": irc,
        }
        digest = domain_digest(
            "internal_risk_capacity_assessment", 1, canonical_json_bytes(payload)
        )
        with self._engine.begin() as connection:
            connection.execute(
                insert(internal_risk_capacity_assessment).values(
                    resource_id=self._id_factory("irc"),
                    snapshot_id=output.snapshot_id,
                    scenario_stage_output_id=output_id,
                    cbb_output_digest=output.input_digests[0],
                    uncapped_irc=str(irc["uncapped_irc"]),
                    irc=str(irc["irc"]),
                    currency=str(output.scenario["result"]["currency"]),
                    canonical_payload=canonical_json_bytes(payload),
                    digest=digest,
                    created_at=now,
                )
            )


def _stage_payload(output: ScenarioCapacityStageOutput) -> dict[str, object]:
    payload = output.to_canonical_dict()
    payload.pop("output_digest")
    return payload


def _hedge_effectiveness(exposure: dict[str, object]) -> Decimal:
    gross_physical = abs(Decimal(str(exposure["gross_physical_exposure"])))
    net_price = abs(Decimal(str(exposure["net_price_exposure"])))
    if gross_physical == 0:
        return Decimal(0)
    return min(Decimal(1), max(Decimal(0), Decimal(1) - net_price / gross_physical))
