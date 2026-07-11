"""Durable frozen-input and fenced S5 hedge/liquidity publication."""

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
from canopyledger.domain.ids import new_resource_id
from canopyledger.domain.money import Money
from canopyledger.hedge.engine import HedgeLiquidityError, HedgeLiquidityInput
from canopyledger.hedge.pipeline import (
    HedgeLiquidityStageOutput,
    build_hedge_liquidity_stage_output,
)
from canopyledger.integrity.bundles import VersionBundle
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.integrity.snapshot import SnapshotInputReference, SnapshotManifest
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import (
    hedge_liquidity_input,
    pipeline_run,
    pipeline_stage,
    pipeline_stage_output,
)


class HedgeLiquidityPersistenceError(HedgeLiquidityError):
    """Raised when a hedge input or S5 publication violates frozen-lineage rules."""


@dataclass(frozen=True)
class StoredHedgeLiquidityInput:
    resource_id: str
    digest: str
    canonical_payload: bytes


@dataclass(frozen=True)
class PublishedHedgeLiquidityStage:
    run_id: str
    output_id: str
    output_digest: str
    stage_output: HedgeLiquidityStageOutput


class PostgresHedgeLiquidityInputStore:
    """Store a canonical hedge/liquidity input before it is frozen into a snapshot."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(
        self,
        value: HedgeLiquidityInput,
        *,
        created_by: str,
        created_at: datetime,
    ) -> StoredHedgeLiquidityInput:
        canonical_payload = canonical_json_bytes(value.to_input_canonical_dict())
        stored = StoredHedgeLiquidityInput(
            resource_id=value.assessment_id,
            digest=value.input_digest,
            canonical_payload=canonical_payload,
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(hedge_liquidity_input).values(
                        resource_id=stored.resource_id,
                        canonical_payload=stored.canonical_payload,
                        digest=stored.digest,
                        created_by=created_by,
                        created_at=created_at,
                    )
                )
        except IntegrityError:
            existing = self.load(stored.resource_id)
            if existing != stored:
                raise HedgeLiquidityPersistenceError(
                    "hedge liquidity input ID already has different immutable content"
                ) from None
        return stored

    def load(self, resource_id: str) -> StoredHedgeLiquidityInput | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(hedge_liquidity_input).where(
                        hedge_liquidity_input.c.resource_id == resource_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        payload = bytes(row["canonical_payload"])
        digest = domain_digest("hedge_liquidity_input", 1, payload)
        if row["digest"] != digest:
            raise HedgeLiquidityPersistenceError("stored hedge liquidity input digest mismatch")
        return StoredHedgeLiquidityInput(row["resource_id"], row["digest"], payload)

    def load_value(
        self,
        resource_id: str,
        *,
        snapshot_id: str,
        cbb_output_digest: str,
        market_bundle_digest: str,
        policy_bundle_digest: str,
        computation_bundle_digest: str,
        undrawn_contractual_availability: Money,
    ) -> HedgeLiquidityInput | None:
        stored = self.load(resource_id)
        if stored is None:
            return None
        decoded = json.loads(stored.canonical_payload)
        if not isinstance(decoded, dict):
            raise HedgeLiquidityPersistenceError("stored hedge liquidity input must be an object")
        value = HedgeLiquidityInput.from_frozen_input(
            decoded,
            assessment_id=resource_id,
            snapshot_id=snapshot_id,
            cbb_output_digest=cbb_output_digest,
            market_bundle_digest=market_bundle_digest,
            policy_bundle_digest=policy_bundle_digest,
            computation_bundle_digest=computation_bundle_digest,
            undrawn_contractual_availability=undrawn_contractual_availability,
        )
        if value.input_digest != stored.digest:
            raise HedgeLiquidityPersistenceError("stored hedge liquidity input is not canonical")
        return value

    def validate_snapshot_reference(self, reference: SnapshotInputReference) -> None:
        """Reject freeze-time references to absent or altered immutable hedge inputs."""
        if reference.resource_type != "hedge_liquidity_input":
            raise HedgeLiquidityPersistenceError("invalid hedge liquidity input reference type")
        stored = self.load(reference.resource_id)
        if stored is None or stored.digest != reference.digest:
            raise HedgeLiquidityPersistenceError(
                "hedge liquidity snapshot input is absent or digest-mismatched"
            )


class PostgresHedgeLiquidityRunner:
    """Publish exactly one S5 output only when all frozen references are verified."""

    def __init__(
        self,
        engine: Engine,
        integrity_store: PostgresIntegrityStore,
        input_store: PostgresHedgeLiquidityInputStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._engine = engine
        self._integrity_store = integrity_store
        self._input_store = input_store
        self._clock = clock
        self._id_factory = id_factory

    def publish(
        self,
        snapshot_id: str,
        hedge_input_id: str,
        *,
        worker_id: str,
    ) -> PublishedHedgeLiquidityStage:
        value = self._load_frozen_execution_input(snapshot_id, hedge_input_id)
        now = self._clock()
        output_id = self._id_factory("out")
        stage_output = build_hedge_liquidity_stage_output(
            value,
            stage_output_id=output_id,
            started_at=now,
            completed_at=now,
        )
        run_id = self._create_run(value, stage_output, now)
        lease = self._integrity_store.claim_stage(
            worker_id=worker_id,
            now=now,
            lease_duration=timedelta(minutes=5),
            maximum_lease_lifetime=timedelta(minutes=5),
            attempt_id=self._id_factory("att"),
        )
        if lease is None:
            raise HedgeLiquidityPersistenceError("S5 hedge/liquidity stage was not claimable")
        canonical_output = canonical_json_bytes(_stage_payload(stage_output))
        published = self._integrity_store.publish_stage(
            StagePublicationData(
                stage_id=lease.stage_id,
                worker_id=worker_id,
                epoch=lease.epoch,
                input_digest=lease.input_digest,
                output_schema_version="hedge-liquidity-stage-output-v1",
                canonical_output=canonical_output,
                output_digest=stage_output.output_digest,
                output_id=output_id,
                outbox_message_id=self._id_factory("msg"),
                audit_event_id=self._id_factory("aud"),
                published_at=now + timedelta(seconds=1),
            )
        )
        return PublishedHedgeLiquidityStage(
            run_id=run_id,
            output_id=published.output_id,
            output_digest=published.output_digest,
            stage_output=stage_output,
        )

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
            decoded = json.loads(bytes(row["canonical_output"]))
            if isinstance(decoded, dict) and decoded.get("stage") == "hedge_liquidity":
                decoded["output_digest"] = str(row["output_digest"])
                return cast(dict[str, object], decoded)
        return None

    def _load_frozen_execution_input(
        self,
        snapshot_id: str,
        hedge_input_id: str,
    ) -> HedgeLiquidityInput:
        snapshot = self._integrity_store.get_snapshot_manifest(snapshot_id)
        if snapshot is None:
            raise HedgeLiquidityPersistenceError("frozen snapshot does not exist")
        manifest = snapshot.manifest
        input_references = [
            item
            for item in manifest.inputs
            if item.resource_type == "hedge_liquidity_input" and item.resource_id == hedge_input_id
        ]
        if len(input_references) != 1:
            raise HedgeLiquidityPersistenceError(
                "frozen snapshot does not pin the hedge liquidity input digest"
            )
        cbb_output_digest, undrawn_contractual_availability = self._load_cbb_output(
            snapshot_id
        )
        value = self._input_store.load_value(
            hedge_input_id,
            snapshot_id=snapshot_id,
            cbb_output_digest=cbb_output_digest,
            market_bundle_digest=manifest.market_bundle.digest,
            policy_bundle_digest=manifest.policy_bundle.digest,
            computation_bundle_digest=manifest.computation_bundle.digest,
            undrawn_contractual_availability=undrawn_contractual_availability,
        )
        if value is None or value.input_digest != input_references[0].digest:
            raise HedgeLiquidityPersistenceError(
                "frozen hedge liquidity input is absent or altered"
            )
        self._verify_bundle_payloads(value, manifest)
        return value

    def _verify_bundle_payloads(
        self,
        value: HedgeLiquidityInput,
        manifest: SnapshotManifest,
    ) -> None:
        market = self._load_bundle(manifest.market_bundle.resource_id)
        policy = self._load_bundle(manifest.policy_bundle.resource_id)
        computation = self._load_bundle(manifest.computation_bundle.resource_id)
        expected_sections = (
            ("market", market, value.market_bundle_payload()),
            ("policy", policy, value.policy_bundle_payload()),
            ("computation", computation, value.computation_bundle_payload()),
        )
        for label, bundle, expected in expected_sections:
            payload = bundle.payload
            if not isinstance(payload, dict) or payload.get("hedge_liquidity") != expected:
                raise HedgeLiquidityPersistenceError(
                    f"frozen {label} bundle does not contain the required M3 hedge/liquidity data"
                )

    def _load_bundle(self, resource_id: str) -> VersionBundle:
        bundle = self._integrity_store.load_bundle(resource_id)
        if bundle is None:
            raise HedgeLiquidityPersistenceError("snapshot-pinned bundle is unavailable")
        return bundle

    def _load_cbb_output(self, snapshot_id: str) -> tuple[str, Money]:
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
        for row in rows:
            decoded = json.loads(bytes(row["canonical_output"]))
            if (
                not isinstance(decoded, dict)
                or decoded.get("stage") != "contractual_borrowing_base"
            ):
                continue
            result = decoded.get("result")
            if not isinstance(result, dict):
                break
            currency = result.get("currency")
            availability = result.get("contractual_availability")
            if not isinstance(currency, str) or not isinstance(availability, str):
                break
            try:
                return str(row["output_digest"]), Money(Decimal(availability), currency)
            except (ArithmeticError, ValueError) as exc:
                raise HedgeLiquidityPersistenceError(
                    "published CBB output has invalid contractual availability"
                ) from exc
        raise HedgeLiquidityPersistenceError(
            "S5 requires a published contractual borrowing base output with availability"
        )

    def _create_run(
        self,
        value: HedgeLiquidityInput,
        stage_output: HedgeLiquidityStageOutput,
        now: datetime,
    ) -> str:
        run_id = self._id_factory("run")
        input_digest = domain_digest(
            "hedge_liquidity_stage_input",
            1,
            canonical_json_bytes(
                {
                    "snapshot_id": value.snapshot_id,
                    "input_digests": list(stage_output.input_digests),
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
                        run_key=f"{value.snapshot_id}:hedge_liquidity:1.0.0",
                        input_digest=input_digest,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(pipeline_stage).values(
                        resource_id=self._id_factory("stg"),
                        pipeline_run_id=run_id,
                        stage_definition_id="hedge_liquidity",
                        status="PENDING",
                        input_digest=input_digest,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            raise HedgeLiquidityPersistenceError(
                "S5 hedge/liquidity output already exists for this snapshot"
            ) from exc
        return run_id


def _stage_payload(stage_output: HedgeLiquidityStageOutput) -> dict[str, object]:
    payload = stage_output.to_canonical_dict()
    payload.pop("output_digest")
    return payload
