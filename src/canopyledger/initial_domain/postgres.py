"""PostgreSQL publication for M1B initial-domain stage outputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, insert

from canopyledger.application.models import StagePublicationData
from canopyledger.borrowing_base.certificate import CbbCertificate
from canopyledger.domain.ids import new_resource_id
from canopyledger.initial_domain.pipeline import (
    M1BPipelineInput,
    M1BPipelineResult,
    StageOutput,
    run_initial_domain_pipeline,
)
from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest
from canopyledger.persistence.postgres import PostgresIntegrityStore
from canopyledger.persistence.schema import pipeline_run, pipeline_stage


@dataclass(frozen=True)
class PersistedM1BPipeline:
    run_id: str
    stage_output_ids: tuple[str, ...]
    output_digests: tuple[str, ...]
    certificate_output_digest: str


@dataclass(frozen=True)
class PublishedM1BPipeline:
    run_id: str
    stage_output_ids: tuple[str, ...]
    output_digests: tuple[str, ...]
    certificate: CbbCertificate


class PostgresM1BPipelineRunner:
    """Create and publish a deterministic M1B run through fenced stage outputs."""

    def __init__(
        self,
        engine: Engine,
        store: PostgresIntegrityStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._engine = engine
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def publish(self, value: M1BPipelineInput, *, worker_id: str) -> PublishedM1BPipeline:
        now = self._clock()
        result = run_initial_domain_pipeline(value)
        run_id = self._create_run(value, result, now)
        stage_output_ids = []
        output_digests = []
        for index, stage_output in enumerate(result.stage_outputs):
            lease = self._store.claim_stage(
                worker_id=worker_id,
                now=now + timedelta(microseconds=index),
                lease_duration=timedelta(minutes=5),
                maximum_lease_lifetime=timedelta(minutes=5),
                attempt_id=self._id_factory("att"),
            )
            if lease is None:
                raise RuntimeError("M1B pipeline stage was not claimable")
            payload = _stage_payload(stage_output)
            canonical_output = canonical_json_bytes(payload)
            published = self._store.publish_stage(
                StagePublicationData(
                    stage_id=lease.stage_id,
                    worker_id=worker_id,
                    epoch=lease.epoch,
                    input_digest=lease.input_digest,
                    output_schema_version="m1b-stage-output-v1",
                    canonical_output=canonical_output,
                    output_digest=stage_output.output_digest,
                    output_id=self._id_factory("out"),
                    outbox_message_id=self._id_factory("msg"),
                    audit_event_id=self._id_factory("aud"),
                    published_at=now + timedelta(seconds=1, microseconds=index),
                )
            )
            stage_output_ids.append(published.output_id)
            output_digests.append(published.output_digest)
        return PublishedM1BPipeline(
            run_id=run_id,
            stage_output_ids=tuple(stage_output_ids),
            output_digests=tuple(output_digests),
            certificate=result.certificate,
        )

    def _create_run(
        self,
        value: M1BPipelineInput,
        result: M1BPipelineResult,
        now: datetime,
    ) -> str:
        run_id = self._id_factory("run")
        run_payload = {
            "snapshot_id": value.snapshot_id,
            "stage_digests": [stage.output_digest for stage in result.stage_outputs],
        }
        with self._engine.begin() as connection:
            connection.execute(
                insert(pipeline_run).values(
                    resource_id=run_id,
                    snapshot_id=value.snapshot_id,
                    run_key=f"{value.snapshot_id}:m1b:1.0.0",
                    input_digest=domain_digest(
                        "initial_domain_pipeline_input", 1, canonical_json_bytes(run_payload)
                    ),
                    created_at=now,
                )
            )
            for position, stage in enumerate(result.stage_outputs):
                connection.execute(
                    insert(pipeline_stage).values(
                        resource_id=self._id_factory("stg"),
                        pipeline_run_id=run_id,
                        stage_definition_id=stage.stage,
                        status="PENDING",
                        input_digest=stage.input_digests[0],
                        created_at=now + timedelta(microseconds=position),
                        updated_at=now + timedelta(microseconds=position),
                    )
                )
        return run_id


def _stage_payload(stage_output: StageOutput) -> dict[str, object]:
    payload = stage_output.to_canonical_dict()
    payload.pop("output_digest")
    return payload
