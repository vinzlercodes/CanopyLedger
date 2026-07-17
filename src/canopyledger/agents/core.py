"""Replayable, capability-bounded agent orchestration.

The module deliberately has no financial calculation or decision authority.  It converts a
small, deterministic intent vocabulary into typed tool calls and writes an immutable audit trail
for both allowed and refused actions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from canopyledger.integrity.canonical import canonical_json_bytes, domain_digest


class AgentError(ValueError):
    """Base contract failure for governed orchestration."""


class AgentCapabilityDenied(AgentError):
    """Raised when a planner requests a capability outside the code-owned registry."""


class AgentRole(StrEnum):
    FACILITY_ORCHESTRATOR = "facility_orchestrator"
    EVIDENCE_REVIEW_ASSISTANT = "evidence_review_assistant"
    COLLATERAL_ANALYSIS_ASSISTANT = "collateral_analysis_assistant"
    MARKET_RISK_ASSISTANT = "market_risk_assistant"
    CREDIT_ANALYSIS_ASSISTANT = "credit_analysis_assistant"
    CLIMATE_EVIDENCE_ASSISTANT = "climate_evidence_assistant"
    DECISION_PACK_ASSISTANT = "decision_pack_assistant"
    REPORTING_ASSISTANT = "reporting_assistant"


class CapabilityRisk(StrEnum):
    READ = "read"
    CONTROLLED_WRITE = "controlled_write"
    HUMAN_ROUTE = "human_route"


@dataclass(frozen=True)
class Principal:
    actor_id: str
    roles: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.actor_id or not self.roles:
            raise AgentError("principal resolution requires an actor and at least one role")


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    risk_level: CapabilityRisk
    allowed_agent_roles: tuple[AgentRole, ...]
    allowed_principal_roles: tuple[str, ...]
    input_fields: tuple[str, ...]
    output_schema: str
    requires_human_approval: bool = False


@dataclass(frozen=True)
class PlannedToolCall:
    capability: str
    inputs: Mapping[str, str]
    task_title: str


class AgentPlanner(Protocol):
    """A deterministic or optional BYO planner with no authority of its own."""

    planner_type: str
    planner_version: str

    def plan(self, *, goal: str, snapshot_id: str) -> tuple[PlannedToolCall, ...]: ...


class OptionalPlannerAdapter:
    """Boundary for a local or bring-your-own planner.

    The adapter validates only the typed plan shape.  Capability and principal authorization still
    happens later in :class:`AgentRunner`, so a provider cannot acquire authority by instruction.
    """

    def __init__(
        self,
        *,
        planner_type: str,
        planner_version: str,
        planner: Callable[[str, str], tuple[PlannedToolCall, ...]],
    ) -> None:
        if not planner_type or not planner_version:
            raise AgentError("optional planner requires type and version metadata")
        self.planner_type = planner_type
        self.planner_version = planner_version
        self._planner = planner

    def plan(self, *, goal: str, snapshot_id: str) -> tuple[PlannedToolCall, ...]:
        plan = self._planner(goal, snapshot_id)
        if not isinstance(plan, tuple) or not all(
            _is_typed_planned_call(item)
            for item in plan
        ):
            raise AgentError("optional planner returned an invalid typed plan")
        return plan


def _is_typed_planned_call(value: object) -> bool:
    return (
        isinstance(value, PlannedToolCall)
        and isinstance(value.capability, str)
        and isinstance(value.task_title, str)
        and all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.inputs.items()
        )
    )


@dataclass(frozen=True)
class TaskPlan:
    resource_id: str
    planner_type: str
    planner_version: str
    goal: str
    planned_capabilities: tuple[str, ...]
    created_at: datetime
    digest: str


@dataclass(frozen=True)
class ToolCallRecord:
    resource_id: str
    task_id: str
    capability: str
    inputs: Mapping[str, str]
    authorization: str
    authorization_reason: str
    occurred_at: datetime
    output_digest: str | None = None


@dataclass(frozen=True)
class ToolResultRecord:
    resource_id: str
    call_id: str
    output_schema: str
    status: str
    output: Mapping[str, object]
    output_digest: str
    occurred_at: datetime


@dataclass(frozen=True)
class AgentTask:
    resource_id: str
    title: str
    capability: str
    status: str
    completed_at: datetime | None = None


@dataclass(frozen=True)
class HandoffRecord:
    resource_id: str
    source_role: AgentRole
    target_role: str
    approval_request_id: str
    created_at: datetime


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    event_type: str
    occurred_at: datetime
    detail: str


@dataclass(frozen=True)
class AgentRun:
    resource_id: str
    principal: Principal
    agent_role: AgentRole
    facility_id: str
    snapshot_id: str
    goal: str
    planner_type: str
    planner_version: str
    status: str
    created_at: datetime
    task_plan: TaskPlan | None = None
    tasks: tuple[AgentTask, ...] = ()
    tool_calls: tuple[ToolCallRecord, ...] = ()
    tool_results: tuple[ToolResultRecord, ...] = ()
    handoffs: tuple[HandoffRecord, ...] = ()
    trace: tuple[TraceEvent, ...] = ()
    digest: str = ""

    def with_digest(self) -> AgentRun:
        return replace(
            self,
            digest=domain_digest("agent_run", 1, canonical_json_bytes(agent_run_payload(self))),
        )


def agent_run_payload(run: AgentRun) -> dict[str, object]:
    """Canonical JSON-safe persistence form for an immutable run record."""
    return {
            "resource_id": run.resource_id,
            "principal": {"actor_id": run.principal.actor_id, "roles": list(run.principal.roles)},
            "agent_role": run.agent_role.value,
            "facility_id": run.facility_id,
            "snapshot_id": run.snapshot_id,
            "goal": run.goal,
            "planner_type": run.planner_type,
            "planner_version": run.planner_version,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
            "task_plan": (
                {
                    "id": run.task_plan.resource_id,
                    "planner_type": run.task_plan.planner_type,
                    "planner_version": run.task_plan.planner_version,
                    "goal": run.task_plan.goal,
                    "planned_capabilities": list(run.task_plan.planned_capabilities),
                    "created_at": run.task_plan.created_at.isoformat(),
                    "digest": run.task_plan.digest,
                }
                if run.task_plan is not None
                else None
            ),
            "tasks": [
                {
                    "id": task.resource_id,
                    "title": task.title,
                    "capability": task.capability,
                    "status": task.status,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
                for task in run.tasks
            ],
            "tool_calls": [
                {
                    "id": call.resource_id,
                    "task_id": call.task_id,
                    "capability": call.capability,
                    "inputs": dict(call.inputs),
                    "authorization": call.authorization,
                    "authorization_reason": call.authorization_reason,
                    "occurred_at": call.occurred_at.isoformat(),
                    "output_digest": call.output_digest,
                }
                for call in run.tool_calls
            ],
            "tool_results": [
                {
                    "id": result.resource_id,
                    "call_id": result.call_id,
                    "output_schema": result.output_schema,
                    "status": result.status,
                    "output": dict(result.output),
                    "output_digest": result.output_digest,
                    "occurred_at": result.occurred_at.isoformat(),
                }
                for result in run.tool_results
            ],
            "handoffs": [
                {
                    "id": handoff.resource_id,
                    "target_role": handoff.target_role,
                    "approval_request_id": handoff.approval_request_id,
                    "created_at": handoff.created_at.isoformat(),
                }
                for handoff in run.handoffs
            ],
            "trace": [
                {
                    "sequence": event.sequence,
                    "type": event.event_type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "detail": event.detail,
                }
                for event in run.trace
            ],
    }


class CapabilityRegistry:
    """Code-owned capability policy; no prompt or planner can modify it."""

    def __init__(self, specifications: tuple[CapabilitySpec, ...]) -> None:
        names = [spec.name for spec in specifications]
        if len(names) != len(set(names)):
            raise AgentError("capability registry contains duplicate capability names")
        self._specifications = {spec.name: spec for spec in specifications}

    def get(self, capability: str) -> CapabilitySpec:
        try:
            return self._specifications[capability]
        except KeyError as exc:
            raise AgentCapabilityDenied(f"capability {capability!r} is not permitted") from exc

    def authorize(
        self,
        *,
        capability: str,
        agent_role: AgentRole,
        principal: Principal,
        inputs: Mapping[str, str],
    ) -> CapabilitySpec:
        spec = self.get(capability)
        if agent_role not in spec.allowed_agent_roles:
            raise AgentCapabilityDenied(
                f"capability {capability!r} is not permitted for agent role {agent_role.value}"
            )
        if not set(principal.roles).intersection(spec.allowed_principal_roles):
            raise AgentCapabilityDenied(
                f"capability {capability!r} is not permitted for resolved principal "
                f"{principal.actor_id}"
            )
        inputs_are_strings = all(isinstance(value, str) and value for value in inputs.values())
        if set(inputs) != set(spec.input_fields) or not inputs_are_strings:
            raise AgentCapabilityDenied(f"capability {capability!r} received invalid typed inputs")
        return spec

    def specifications(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specifications.values())


class DeterministicReplayPlanner:
    """Maps a deliberately narrow vocabulary to replayable plans.

    Unknown/prohibited intents are represented as denied calls so refusal itself is auditable.
    """

    planner_type = "deterministic_replay"
    planner_version = "M9/v1"

    def plan(self, *, goal: str, snapshot_id: str) -> tuple[PlannedToolCall, ...]:
        normalized = " ".join(goal.lower().split())
        if "route approval request" in normalized:
            match = re.search(r"\b(arq_[a-z0-9-]+)\b", normalized)
            if match is None:
                return (PlannedToolCall("approval.route", {}, "Route human approval"),)
            return (
                PlannedToolCall(
                    "approval.route",
                    {"approval_request_id": match.group(1)},
                    "Route human approval",
                ),
            )
        if re.search(r"\b(approve|reject|override|release funds|transfer|trade)\b", normalized):
            return (PlannedToolCall("facility.approve", {}, "Denied decision request"),)
        if "unapproved" in normalized or "policy bundle" in normalized:
            return (PlannedToolCall("policy.select", {}, "Denied policy request"),)
        calls = [
            PlannedToolCall("snapshot.read", {"snapshot_id": snapshot_id}, "Read frozen snapshot")
        ]
        if "start" in normalized and "pipeline" in normalized:
            calls.append(
                PlannedToolCall(
                    "pipeline.start", {"snapshot_id": snapshot_id}, "Start approved pipeline"
                )
            )
            return tuple(calls)
        if "pipeline" in normalized and ("status" in normalized or "inspect" in normalized):
            calls.append(
                PlannedToolCall(
                    "pipeline.status", {"snapshot_id": snapshot_id}, "Inspect pipeline status"
                )
            )
            return tuple(calls)
        if "approved evidence" in normalized:
            calls.append(
                PlannedToolCall(
                    "evidence.approved.read",
                    {"snapshot_id": snapshot_id},
                    "Read approved evidence references",
                )
            )
            return tuple(calls)
        if "decision pack" in normalized:
            calls.append(
                PlannedToolCall(
                    "decision-pack.draft",
                    {"snapshot_id": snapshot_id},
                    "Assemble draft decision-pack context",
                )
            )
            return tuple(calls)
        if "conflict" in normalized or "missing fact" in normalized:
            calls.append(
                PlannedToolCall(
                    "conflict.surface",
                    {"snapshot_id": snapshot_id},
                    "Surface frozen input conflicts",
                )
            )
            return tuple(calls)
        stage_by_term = (
            ("scenario", "scenario_capacity"),
            ("hedge", "hedge_liquidity"),
            ("climate", "climate_traceability"),
            ("credit", "credit_early_warning"),
            ("collateral", "collateral_valuation"),
        )
        for term, stage in stage_by_term:
            if term in normalized:
                calls.append(
                    PlannedToolCall(
                        "stage-output.get",
                        {"snapshot_id": snapshot_id, "stage": stage},
                        f"Read published {stage}",
                    )
                )
                break
        return tuple(calls)


class AgentRunStore(Protocol):
    """Immutable agent-run persistence boundary."""

    def get(self, run_id: str) -> AgentRun: ...

    def find(self, run_id: str) -> AgentRun | None: ...

    def save(self, run: AgentRun) -> AgentRun: ...

    def list_for_snapshot(self, snapshot_id: str) -> tuple[AgentRun, ...]: ...


class InMemoryAgentRunStore:
    """Test and demo store with immutable run-id idempotency."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    def get(self, run_id: str) -> AgentRun:
        return self._runs[run_id]

    def find(self, run_id: str) -> AgentRun | None:
        return self._runs.get(run_id)

    def save(self, run: AgentRun) -> AgentRun:
        existing = self._runs.get(run.resource_id)
        if existing is not None:
            return existing
        self._runs[run.resource_id] = run
        return run

    def list_for_snapshot(self, snapshot_id: str) -> tuple[AgentRun, ...]:
        return tuple(run for run in self._runs.values() if run.snapshot_id == snapshot_id)


Tool = Callable[[Mapping[str, str]], Mapping[str, object]]


class AgentRunner:
    """Executes only capability-authorized typed calls and records every outcome."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        planner: AgentPlanner,
        store: AgentRunStore,
        tools: Mapping[str, Tool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.registry = registry
        self.planner = planner
        self.store = store
        self._tools = tools
        self._clock = clock

    def run(
        self,
        *,
        run_id: str,
        principal: Principal,
        role: AgentRole,
        facility_id: str,
        snapshot_id: str,
        goal: str,
    ) -> AgentRun:
        if self.store.find(run_id) is not None:
            return self.store.get(run_id)
        now = self._clock()
        run = AgentRun(
            resource_id=run_id,
            principal=principal,
            agent_role=role,
            facility_id=facility_id,
            snapshot_id=snapshot_id,
            goal=goal,
            planner_type=self.planner.planner_type,
            planner_version=self.planner.planner_version,
            status="RUNNING",
            created_at=now,
        )
        run = self._trace(run, "RUN_STARTED", "resolved principal and deterministic planner")
        planned_calls = self.planner.plan(goal=goal, snapshot_id=snapshot_id)
        task_plan_payload = {
            "resource_id": f"{run_id}:plan",
            "planner_type": self.planner.planner_type,
            "planner_version": self.planner.planner_version,
            "goal": goal,
            "planned_capabilities": [call.capability for call in planned_calls],
            "created_at": now.isoformat(),
        }
        task_plan = TaskPlan(
            resource_id=f"{run_id}:plan",
            planner_type=self.planner.planner_type,
            planner_version=self.planner.planner_version,
            goal=goal,
            planned_capabilities=tuple(call.capability for call in planned_calls),
            created_at=now,
            digest=domain_digest("agent_task_plan", 1, canonical_json_bytes(task_plan_payload)),
        )
        run = replace(run, task_plan=task_plan)
        for index, planned in enumerate(planned_calls, start=1):
            task_id = f"{run_id}:task:{index}"
            task = AgentTask(task_id, planned.task_title, planned.capability, "PLANNED")
            run = replace(run, tasks=(*run.tasks, task))
            run = self._trace(run, "TASK_PLANNED", planned.task_title)
            call_id = f"{run_id}:call:{index}"
            try:
                self.registry.authorize(
                    capability=planned.capability,
                    agent_role=role,
                    principal=principal,
                    inputs=planned.inputs,
                )
            except AgentCapabilityDenied as exc:
                denied = ToolCallRecord(
                    call_id, task_id, planned.capability, planned.inputs, "DENIED", str(exc), now
                )
                run = replace(run, status="DENIED", tool_calls=(*run.tool_calls, denied))
                run = self._trace(run, "CAPABILITY_DENIED", str(exc)).with_digest()
                self.store.save(run)
                raise
            run = self._trace(run, "TOOL_AUTHORIZED", planned.capability)
            tool = self._tools.get(planned.capability)
            if tool is None:
                denial = AgentCapabilityDenied(
                    f"capability {planned.capability!r} has no typed tool binding"
                )
                denied = ToolCallRecord(
                    call_id, task_id, planned.capability, planned.inputs, "DENIED", str(denial), now
                )
                run = replace(run, status="DENIED", tool_calls=(*run.tool_calls, denied))
                run = self._trace(run, "CAPABILITY_DENIED", str(denial)).with_digest()
                self.store.save(run)
                raise denial
            try:
                result = tool(planned.inputs)
            except Exception as exc:
                failure = {"error": "typed tool execution failed"}
                output_digest = domain_digest(
                    "agent_tool_result", 1, canonical_json_bytes(failure)
                )
                failed_call = ToolCallRecord(
                    call_id,
                    task_id,
                    planned.capability,
                    planned.inputs,
                    "ALLOWED",
                    "registry and resolved principal allowed capability",
                    now,
                    output_digest=output_digest,
                )
                failed_result = ToolResultRecord(
                    resource_id=f"{run_id}:result:{index}",
                    call_id=call_id,
                    output_schema=self.registry.get(planned.capability).output_schema,
                    status="FAILED",
                    output=failure,
                    output_digest=output_digest,
                    occurred_at=now,
                )
                failed_task = replace(task, status="FAILED", completed_at=now)
                run = replace(
                    run,
                    status="FAILED",
                    tasks=(*run.tasks[:-1], failed_task),
                    tool_calls=(*run.tool_calls, failed_call),
                    tool_results=(*run.tool_results, failed_result),
                )
                run = self._trace(run, "TOOL_FAILED", planned.capability)
                run = self._trace(run, "RUN_FAILED", "typed tool execution failed").with_digest()
                self.store.save(run)
                raise AgentError(f"typed tool {planned.capability!r} failed") from exc
            output_digest = domain_digest(
                "agent_tool_result", 1, canonical_json_bytes(dict(result))
            )
            call = ToolCallRecord(
                call_id,
                task_id,
                planned.capability,
                planned.inputs,
                "ALLOWED",
                "registry and resolved principal allowed capability",
                now,
                output_digest=output_digest,
            )
            result_record = ToolResultRecord(
                resource_id=f"{run_id}:result:{index}",
                call_id=call_id,
                output_schema=self.registry.get(planned.capability).output_schema,
                status="COMPLETED",
                output=dict(result),
                output_digest=output_digest,
                occurred_at=now,
            )
            completed = replace(task, status="COMPLETED", completed_at=now)
            run = replace(
                run,
                tasks=(*run.tasks[:-1], completed),
                tool_calls=(*run.tool_calls, call),
                tool_results=(*run.tool_results, result_record),
            )
            run = self._trace(run, "TOOL_COMPLETED", planned.capability)
            run = self._trace(run, "TASK_COMPLETED", planned.task_title)
            if planned.capability == "approval.route":
                approval_request_id = planned.inputs["approval_request_id"]
                handoff = HandoffRecord(
                    f"{run_id}:handoff:1", role, "credit_approver", approval_request_id, now
                )
                run = replace(
                    run,
                    status="AWAITING_HUMAN_APPROVAL",
                    handoffs=(*run.handoffs, handoff),
                )
                run = self._trace(run, "HUMAN_APPROVAL_ROUTED", approval_request_id)
        if run.status == "RUNNING":
            run = replace(run, status="COMPLETED")
            run = self._trace(run, "RUN_COMPLETED", "all planned tools completed")
        run = run.with_digest()
        return self.store.save(run)

    def _trace(self, run: AgentRun, event_type: str, detail: str) -> AgentRun:
        event = TraceEvent(len(run.trace) + 1, event_type, self._clock(), detail)
        return replace(run, trace=(*run.trace, event))


def default_capability_registry() -> CapabilityRegistry:
    """Return the fixed v1 capability set.  Deliberately absent capabilities are prohibited."""
    analysts = ("analyst", "credit_approver", "auditor")
    return CapabilityRegistry(
        (
            CapabilitySpec(
                "snapshot.read",
                CapabilityRisk.READ,
                tuple(AgentRole),
                analysts,
                ("snapshot_id",),
                "SnapshotManifest/v1",
            ),
            CapabilitySpec(
                "evidence.approved.read",
                CapabilityRisk.READ,
                (
                    AgentRole.FACILITY_ORCHESTRATOR,
                    AgentRole.EVIDENCE_REVIEW_ASSISTANT,
                    AgentRole.COLLATERAL_ANALYSIS_ASSISTANT,
                    AgentRole.CLIMATE_EVIDENCE_ASSISTANT,
                    AgentRole.DECISION_PACK_ASSISTANT,
                ),
                analysts,
                ("snapshot_id",),
                "ApprovedEvidence/v1",
            ),
            CapabilitySpec(
                "pipeline.start",
                CapabilityRisk.CONTROLLED_WRITE,
                (AgentRole.FACILITY_ORCHESTRATOR,),
                ("analyst",),
                ("snapshot_id",),
                "PipelineRun/v1",
            ),
            CapabilitySpec(
                "pipeline.status",
                CapabilityRisk.READ,
                (AgentRole.FACILITY_ORCHESTRATOR,),
                analysts,
                ("snapshot_id",),
                "PipelineStatus/v1",
            ),
            CapabilitySpec(
                "stage-output.get",
                CapabilityRisk.READ,
                tuple(AgentRole),
                analysts,
                ("snapshot_id", "stage"),
                "PipelineStageOutput/v1",
            ),
            CapabilitySpec(
                "decision-pack.draft",
                CapabilityRisk.READ,
                (AgentRole.DECISION_PACK_ASSISTANT,),
                analysts,
                ("snapshot_id",),
                "DraftDecisionPack/v1",
            ),
            CapabilitySpec(
                "approval.route",
                CapabilityRisk.HUMAN_ROUTE,
                (AgentRole.DECISION_PACK_ASSISTANT,),
                ("analyst", "credit_approver"),
                ("approval_request_id",),
                "HandoffRecord/v1",
                requires_human_approval=True,
            ),
            CapabilitySpec(
                "conflict.surface",
                CapabilityRisk.READ,
                (
                    AgentRole.FACILITY_ORCHESTRATOR,
                    AgentRole.EVIDENCE_REVIEW_ASSISTANT,
                    AgentRole.COLLATERAL_ANALYSIS_ASSISTANT,
                    AgentRole.CREDIT_ANALYSIS_ASSISTANT,
                    AgentRole.CLIMATE_EVIDENCE_ASSISTANT,
                    AgentRole.DECISION_PACK_ASSISTANT,
                ),
                analysts,
                ("snapshot_id",),
                "ConflictSummary/v1",
            ),
        )
    )
