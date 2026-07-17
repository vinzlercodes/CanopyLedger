"""PostgreSQL persistence for immutable governed-agent run records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import NoResultFound

from canopyledger.agents.core import (
    AgentRole,
    AgentRun,
    AgentTask,
    HandoffRecord,
    Principal,
    TaskPlan,
    ToolCallRecord,
    ToolResultRecord,
    TraceEvent,
    agent_run_payload,
)
from canopyledger.persistence.schema import agent_run


class PostgresAgentRunStore:
    """Append-only store; primary-key conflict returns the original idempotent run."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, run_id: str) -> AgentRun:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(agent_run.c.payload, agent_run.c.digest).where(
                    agent_run.c.resource_id == run_id
                )
            ).mappings().one()
        payload = cast(dict[str, Any], row["payload"])
        return _run_from_payload(payload, cast(str, row["digest"]))

    def find(self, run_id: str) -> AgentRun | None:
        try:
            return self.get(run_id)
        except NoResultFound:
            return None

    def save(self, run: AgentRun) -> AgentRun:
        with self._engine.begin() as connection:
            result = connection.execute(
                postgres_insert(agent_run)
                .values(
                    resource_id=run.resource_id,
                    facility_id=run.facility_id,
                    snapshot_id=run.snapshot_id,
                    principal_id=run.principal.actor_id,
                    agent_role=run.agent_role.value,
                    planner_type=run.planner_type,
                    status=run.status,
                    payload=agent_run_payload(run),
                    digest=run.digest,
                    created_at=run.created_at,
                )
                .on_conflict_do_nothing(index_elements=[agent_run.c.resource_id])
            )
            if result.rowcount:
                return run
            row = connection.execute(
                select(agent_run.c.payload, agent_run.c.digest).where(
                    agent_run.c.resource_id == run.resource_id
                )
            ).mappings().one()
        return _run_from_payload(cast(dict[str, Any], row["payload"]), cast(str, row["digest"]))

    def list_for_snapshot(self, snapshot_id: str) -> tuple[AgentRun, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(agent_run.c.payload, agent_run.c.digest)
                .where(agent_run.c.snapshot_id == snapshot_id)
                .order_by(agent_run.c.created_at.desc())
            ).mappings().all()
        return tuple(
            _run_from_payload(cast(dict[str, Any], row["payload"]), cast(str, row["digest"]))
            for row in rows
        )


def _run_from_payload(payload: dict[str, Any], digest: str) -> AgentRun:
    principal = cast(dict[str, Any], payload["principal"])
    raw_plan = cast(dict[str, Any] | None, payload.get("task_plan"))
    task_plan = (
        TaskPlan(
            resource_id=cast(str, raw_plan["id"]),
            planner_type=cast(str, raw_plan["planner_type"]),
            planner_version=cast(str, raw_plan["planner_version"]),
            goal=cast(str, raw_plan["goal"]),
            planned_capabilities=tuple(cast(list[str], raw_plan["planned_capabilities"])),
            created_at=_required_timestamp(cast(str, raw_plan["created_at"])),
            digest=cast(str, raw_plan["digest"]),
        )
        if raw_plan is not None
        else None
    )
    tasks = tuple(
        AgentTask(
            resource_id=cast(str, item["id"]),
            title=cast(str, item["title"]),
            capability=cast(str, item["capability"]),
            status=cast(str, item["status"]),
            completed_at=_timestamp(item.get("completed_at")),
        )
        for item in cast(list[dict[str, Any]], payload["tasks"])
    )
    calls = tuple(
        ToolCallRecord(
            resource_id=cast(str, item["id"]),
            task_id=cast(str, item["task_id"]),
            capability=cast(str, item["capability"]),
            inputs=cast(dict[str, str], item["inputs"]),
            authorization=cast(str, item["authorization"]),
            authorization_reason=cast(str, item["authorization_reason"]),
            occurred_at=_required_timestamp(cast(str, item["occurred_at"])),
            output_digest=cast(str | None, item.get("output_digest")),
        )
        for item in cast(list[dict[str, Any]], payload["tool_calls"])
    )
    results = tuple(
        ToolResultRecord(
            resource_id=cast(str, item["id"]),
            call_id=cast(str, item["call_id"]),
            output_schema=cast(str, item["output_schema"]),
            status=cast(str, item["status"]),
            output=cast(dict[str, object], item["output"]),
            output_digest=cast(str, item["output_digest"]),
            occurred_at=_required_timestamp(cast(str, item["occurred_at"])),
        )
        for item in cast(list[dict[str, Any]], payload.get("tool_results", []))
    )
    handoffs = tuple(
        HandoffRecord(
            resource_id=cast(str, item["id"]),
            source_role=AgentRole(cast(str, item["source_role"])),
            target_role=cast(str, item["target_role"]),
            approval_request_id=cast(str, item["approval_request_id"]),
            created_at=_required_timestamp(cast(str, item["created_at"])),
        )
        for item in cast(list[dict[str, Any]], payload["handoffs"])
    )
    trace = tuple(
        TraceEvent(
            sequence=cast(int, item["sequence"]),
            event_type=cast(str, item["type"]),
            occurred_at=_required_timestamp(cast(str, item["occurred_at"])),
            detail=cast(str, item["detail"]),
        )
        for item in cast(list[dict[str, Any]], payload["trace"])
    )
    return AgentRun(
        resource_id=cast(str, payload["resource_id"]),
        principal=Principal(
            actor_id=cast(str, principal["actor_id"]),
            roles=tuple(cast(list[str], principal["roles"])),
        ),
        agent_role=AgentRole(cast(str, payload["agent_role"])),
        facility_id=cast(str, payload["facility_id"]),
        snapshot_id=cast(str, payload["snapshot_id"]),
        goal=cast(str, payload["goal"]),
        planner_type=cast(str, payload["planner_type"]),
        planner_version=cast(str, payload["planner_version"]),
        status=cast(str, payload["status"]),
        created_at=_required_timestamp(cast(str, payload["created_at"])),
        task_plan=task_plan,
        tasks=tasks,
        tool_calls=calls,
        tool_results=results,
        handoffs=handoffs,
        trace=trace,
        digest=digest,
    )


def _timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _required_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
