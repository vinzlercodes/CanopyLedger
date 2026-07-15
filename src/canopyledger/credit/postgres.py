"""Durable M6 frozen inputs and fenced advisory stage publication."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from canopyledger.application.models import StagePublicationData
from canopyledger.credit.engine import (
    CreditEarlyWarningError,
    CreditFeatureDefinition,
    CreditFeatureObservation,
    CreditModelBundle,
)
from canopyledger.credit.pipeline import (
    CreditEarlyWarningStageOutput,
    build_credit_early_warning_stage_output,
)
from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import SnapshotInputReference
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    credit_early_warning_input,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_output,
)


class CreditEarlyWarningPersistenceError(CreditEarlyWarningError):
    """Raised when M6 frozen model/input lineage or publication is invalid."""


@dataclass(frozen=True)
class StoredCreditEarlyWarningInput:
    resource_id: str
    digest: str
    canonical_payload: bytes


class PostgresCreditEarlyWarningInputStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(
        self,
        *,
        resource_id: str,
        bundle: CreditModelBundle,
        observation: CreditFeatureObservation,
        created_by: str,
        created_at: datetime,
    ) -> StoredCreditEarlyWarningInput:
        payload = {
            "bundle": {**bundle.canonical_dict(), "digest": bundle.digest},
            "observation": {
                "borrower_id": observation.borrower_id,
                "as_of": observation.as_of.isoformat(),
                "observed_at": observation.observed_at.isoformat()
                if observation.observed_at is not None
                else None,
                "values": {name: str(value) for name, value in sorted(observation.values.items())},
            },
        }
        stored = StoredCreditEarlyWarningInput(
            resource_id,
            domain_digest("credit_early_warning_input", 1, canonical_json_bytes(payload)),
            canonical_json_bytes(payload),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(credit_early_warning_input).values(
                        resource_id=resource_id,
                        digest=stored.digest,
                        canonical_payload=stored.canonical_payload,
                        created_by=created_by,
                        created_at=created_at,
                    )
                )
        except IntegrityError:
            if self.load(resource_id) != stored:
                raise CreditEarlyWarningPersistenceError(
                    "credit input ID has different immutable content"
                ) from None
        return stored

    def load(self, resource_id: str) -> StoredCreditEarlyWarningInput | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(credit_early_warning_input).where(
                        credit_early_warning_input.c.resource_id == resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        payload = bytes(row["canonical_payload"])
        digest = domain_digest("credit_early_warning_input", 1, payload)
        if digest != row["digest"]:
            raise CreditEarlyWarningPersistenceError("stored credit input digest mismatch")
        return StoredCreditEarlyWarningInput(str(row["resource_id"]), str(row["digest"]), payload)

    def load_value(
        self, resource_id: str
    ) -> tuple[CreditModelBundle, CreditFeatureObservation] | None:
        stored = self.load(resource_id)
        if stored is None:
            return None
        try:
            payload = json.loads(stored.canonical_payload)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("bundle"), dict)
                or not isinstance(payload.get("observation"), dict)
            ):
                raise ValueError
            bundle_data = cast(dict[str, object], payload["bundle"])
            schema_data = bundle_data["feature_schema"]
            if not isinstance(schema_data, list):
                raise ValueError
            schema = tuple(
                CreditFeatureDefinition(
                    str(item["name"]),
                    str(item["reason_code"]),
                    Decimal(str(item["mean"])),
                    Decimal(str(item["scale"])),
                    int(item["direction"]),
                    bool(item["required"]),
                )
                for item in schema_data
                if isinstance(item, dict)
            )
            thresholds_data = bundle_data["policy_thresholds"]
            if not isinstance(thresholds_data, list):
                raise ValueError
            bundle = CreditModelBundle(
                bundle_id=str(bundle_data["bundle_id"]),
                model_version=str(bundle_data["model_version"]),
                horizon_days=int(str(bundle_data["horizon_days"])),
                feature_schema=schema,
                intercept=Decimal(str(bundle_data["intercept"])),
                weights={
                    name: Decimal(str(value))
                    for name, value in cast(dict[str, object], bundle_data["weights"]).items()
                },
                policy_thresholds=tuple(
                    (str(item[0]), Decimal(str(item[1])))
                    for item in thresholds_data
                    if isinstance(item, list) and len(item) == 2
                ),
                digest=str(bundle_data["digest"]),
            )
            observation_data = cast(dict[str, object], payload["observation"])
            observation = CreditFeatureObservation(
                borrower_id=str(observation_data["borrower_id"]),
                as_of=datetime.fromisoformat(str(observation_data["as_of"])),
                observed_at=datetime.fromisoformat(str(observation_data["observed_at"]))
                if observation_data.get("observed_at")
                else None,
                values={
                    name: Decimal(str(value))
                    for name, value in cast(dict[str, object], observation_data["values"]).items()
                },
            )
        except (KeyError, TypeError, ValueError, CreditEarlyWarningError) as exc:
            raise CreditEarlyWarningPersistenceError("stored credit input is malformed") from exc
        return bundle, observation

    def validate_snapshot_reference(self, reference: SnapshotInputReference) -> None:
        stored = self.load(reference.resource_id)
        if (
            reference.resource_type != "credit_early_warning_input"
            or stored is None
            or stored.digest != reference.digest
        ):
            raise CreditEarlyWarningPersistenceError(
                "credit early-warning snapshot input is absent or digest-mismatched"
            )


class PostgresCreditEarlyWarningRunner:
    def __init__(
        self,
        engine: Engine,
        store: PostgresIntegrityStore,
        input_store: PostgresCreditEarlyWarningInputStore,
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
        self, snapshot_id: str, input_id: str, *, worker_id: str
    ) -> CreditEarlyWarningStageOutput:
        snapshot = self._store.get_snapshot_manifest(snapshot_id)
        value = self._input_store.load_value(input_id)
        if snapshot is None or value is None:
            raise CreditEarlyWarningPersistenceError(
                "frozen credit input or snapshot is unavailable"
            )
        reference = [
            item
            for item in snapshot.manifest.inputs
            if item.resource_type == "credit_early_warning_input" and item.resource_id == input_id
        ]
        stored = self._input_store.load(input_id)
        if len(reference) != 1 or stored is None or reference[0].digest != stored.digest:
            raise CreditEarlyWarningPersistenceError(
                "credit input is not pinned by the frozen snapshot"
            )
        bundle, observation = value
        computation = self._store.load_bundle(snapshot.manifest.computation_bundle.resource_id)
        section = (
            computation.payload.get("credit_early_warning")
            if computation and isinstance(computation.payload, dict)
            else None
        )
        if not isinstance(section, dict) or section.get("model_bundle_digest") != bundle.digest:
            raise CreditEarlyWarningPersistenceError(
                "computation bundle does not approve the M6 model bundle"
            )
        now = self._clock()
        output = build_credit_early_warning_stage_output(
            snapshot_id=snapshot_id,
            input_digest=stored.digest,
            policy_bundle_digest=snapshot.manifest.policy_bundle.digest,
            computation_bundle_digest=snapshot.manifest.computation_bundle.digest,
            bundle=bundle,
            observation=observation,
            stage_output_id=self._id_factory("out"),
            started_at=now,
            completed_at=now,
        )
        run_id = self._id_factory("run")
        stage_input_digest = domain_digest(
            "credit_early_warning_stage_input",
            1,
            canonical_json_bytes(
                {
                    "snapshot_id": snapshot_id,
                    "input_digests": list(output.input_digests),
                    "computation_bundle_digest": output.computation_bundle_digest,
                }
            ),
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(pipeline_run).values(
                        resource_id=run_id,
                        snapshot_id=snapshot_id,
                        run_key=f"{snapshot_id}:credit_early_warning:1.0.0",
                        input_digest=stage_input_digest,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(pipeline_stage).values(
                        resource_id=self._id_factory("stg"),
                        pipeline_run_id=run_id,
                        stage_definition_id="credit_early_warning",
                        status="PENDING",
                        input_digest=stage_input_digest,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise CreditEarlyWarningPersistenceError(
                "M6 credit output already exists for this snapshot"
            ) from exc
        lease = self._store.claim_stage(
            worker_id=worker_id,
            now=now,
            lease_duration=timedelta(minutes=5),
            maximum_lease_lifetime=timedelta(minutes=5),
            attempt_id=self._id_factory("att"),
            pipeline_run_id=run_id,
        )
        if lease is None:
            raise CreditEarlyWarningPersistenceError("M6 credit stage was not claimable")
        self._store.publish_stage(
            StagePublicationData(
                stage_id=lease.stage_id,
                worker_id=worker_id,
                epoch=lease.epoch,
                input_digest=lease.input_digest,
                output_schema_version="credit-early-warning-stage-output-v1",
                canonical_output=canonical_json_bytes(_stage_payload(output)),
                output_digest=output.output_digest,
                output_id=output.stage_output_id,
                outbox_message_id=self._id_factory("msg"),
                audit_event_id=self._id_factory("aud"),
                published_at=now + timedelta(seconds=1),
            )
        )
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
            if isinstance(payload, dict) and payload.get("stage") == "credit_early_warning":
                payload["output_digest"] = str(row["output_digest"])
                return cast(dict[str, object], payload)
        return None


def _stage_payload(output: CreditEarlyWarningStageOutput) -> dict[str, object]:
    payload = output.to_canonical_dict()
    payload.pop("output_digest")
    return payload
