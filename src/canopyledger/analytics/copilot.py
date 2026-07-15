"""Bounded M8 analytical plans, SQL compilation, validation, and answer lineage."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Protocol

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from canopyledger.domain.ids import new_resource_id
from canopyledger.integrity.canonical import (
    canonical_json_bytes,
    canonical_timestamp,
    domain_digest,
)


class AnalyticsQueryRefused(ValueError):
    """Raised when an analytical question or SQL statement exceeds M8 authority."""


@dataclass(frozen=True)
class AnalyticalPlan:
    """A validated, declarative question plan; never executable SQL from a model."""

    template_id: str
    facility_id: str
    snapshot_id: str | None
    comparison_snapshot_id: str | None
    row_limit: int = 100

    def canonical_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "facility_id": self.facility_id,
            "snapshot_id": self.snapshot_id,
            "comparison_snapshot_id": self.comparison_snapshot_id,
            "row_limit": self.row_limit,
        }


@dataclass(frozen=True)
class CompiledAnalyticsQuery:
    """Deterministic SQL text and named scalar parameters for one approved template."""

    sql: str
    parameters: Mapping[str, str | int | None]
    referenced_views: tuple[str, ...]


@dataclass(frozen=True)
class AnalyticsExecution:
    """Rows and source lineage supplied by a read-only analytics executor."""

    rows: tuple[Mapping[str, object], ...]
    data_cutoff: datetime
    lineage: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalyticsAnswer:
    """Structured M8 answer; presentation may explain it but cannot alter it."""

    question: str
    scope: Mapping[str, str]
    plan: AnalyticalPlan
    result: tuple[Mapping[str, object], ...]
    units: Mapping[str, str]
    assumptions: tuple[str, ...]
    referenced_views: tuple[str, ...]
    query_digest: str
    lineage: tuple[str, ...]
    data_cutoff: datetime
    warnings: tuple[str, ...]
    query_run_id: str


@dataclass(frozen=True)
class AnalyticsQueryRun:
    """Immutable audit record for one executed M8 answer."""

    resource_id: str
    request_digest: str
    actor_id: str
    facility_id: str
    snapshot_id: str | None
    question: str
    plan: AnalyticalPlan
    query_digest: str
    referenced_views: tuple[str, ...]
    data_cutoff: datetime
    result: tuple[Mapping[str, object], ...]
    result_digest: str
    warnings: tuple[str, ...]
    created_at: datetime


class AnalyticsExecutor(Protocol):
    """Boundary for bounded read-only execution of already validated SQL."""

    def execute(self, query: CompiledAnalyticsQuery) -> AnalyticsExecution: ...


class AnalyticsRunStore(Protocol):
    """Immutable M8 query-record storage boundary."""

    def insert(self, run: AnalyticsQueryRun) -> None: ...


class InMemoryAnalyticsRunStore:
    """Small immutable run store for tests and the in-memory API factory."""

    def __init__(self) -> None:
        self.runs: dict[str, AnalyticsQueryRun] = {}

    def insert(self, run: AnalyticsQueryRun) -> None:
        existing = self.runs.get(run.resource_id)
        if existing is not None and existing != run:
            raise AnalyticsQueryRefused("Analytics query run ID already exists")
        self.runs[run.resource_id] = run


@dataclass(frozen=True)
class InMemoryAnalyticsExecutor:
    """Deterministic test/demo executor; it receives compiled SQL, never a question."""

    execution: AnalyticsExecution

    def execute(self, query: CompiledAnalyticsQuery) -> AnalyticsExecution:
        del query
        return self.execution


class AnalyticsSqlValidator:
    """Defense-in-depth AST containment for SQL emitted by M8's deterministic compiler."""

    _allowed_views = frozenset(
        {
            "approved_fact_snapshot",
            "hedge_ratio_month",
            "receivable_eligibility",
            "reserve_contribution",
            "scenario_result",
            "snapshot_summary",
        }
    )
    _allowed_columns: ClassVar[Mapping[str, frozenset[str]]] = {
        "approved_fact_snapshot": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "approved_fact_id",
                "fact_type",
                "subject_id",
                "period",
                "value",
                "approved_fact_digest",
                "approved_at",
            }
        ),
        "hedge_ratio_month": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "delivery_month",
                "physical_exposure",
                "hedge_delta_exposure",
                "net_price_exposure",
                "exposure_unit",
                "output_digest",
            }
        ),
        "receivable_eligibility": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "receivable_id",
                "open_amount",
                "advanced_value",
                "reason_codes",
                "currency",
                "output_digest",
            }
        ),
        "reserve_contribution": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "reserve_type",
                "reserve_amount",
                "currency",
                "output_digest",
            }
        ),
        "scenario_result": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "scenario_id",
                "scenario_family",
                "stressed_cbb",
                "cbb_deficiency",
                "margin_liquidity_shortfall",
                "currency",
                "output_digest",
            }
        ),
        "snapshot_summary": frozenset(
            {
                "facility_id",
                "snapshot_id",
                "as_of",
                "currency",
                "snapshot_digest",
                "output_digest",
                "contractual_borrowing_base",
                "contractual_availability",
                "internal_risk_capacity",
                "internal_risk_capacity_digest",
            }
        ),
    }
    _allowed_expression_functions = (exp.And, exp.JSONBContains)

    def validate(self, query: CompiledAnalyticsQuery) -> None:
        try:
            statements = parse(query.sql, read="postgres")
        except ParseError as error:
            raise AnalyticsQueryRefused(
                "query does not satisfy the approved SQL grammar"
            ) from error
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            raise AnalyticsQueryRefused("only one SELECT statement is allowed")
        statement = statements[0]
        if statement.find(exp.With) is not None:
            raise AnalyticsQueryRefused("common table expressions are not allowed")
        tables = tuple(statement.find_all(exp.Table))
        aliases: dict[str, str] = {}
        for table in tables:
            if table.db != "analytics" or table.name not in self._allowed_views:
                raise AnalyticsQueryRefused("query references a non-curated relation")
            aliases[table.alias_or_name] = table.name
        actual_views = tuple(sorted({f"analytics.{table.name}" for table in tables}))
        if actual_views != tuple(sorted(query.referenced_views)):
            raise AnalyticsQueryRefused("query lineage does not match its curated relations")
        if statement.find(exp.Star) is not None or statement.find(exp.Subquery) is not None:
            raise AnalyticsQueryRefused("wildcards and subqueries are not allowlisted")
        for column in statement.find_all(exp.Column):
            view = aliases.get(column.table)
            if view is None and len(tables) == 1:
                view = tables[0].name
            if view is None or column.name not in self._allowed_columns[view]:
                raise AnalyticsQueryRefused("query references a non-curated column")
        for parameter in (":facility_id", ":snapshot_id", ":row_limit"):
            if parameter not in query.sql:
                raise AnalyticsQueryRefused("query is missing a required scope or result limit")
        if statement.args.get("limit") is None:
            raise AnalyticsQueryRefused("query is missing the approved row limit")
        for join in statement.find_all(exp.Join):
            if join.args.get("kind") == "CROSS" or join.args.get("on") is None:
                raise AnalyticsQueryRefused("Cartesian joins are not allowed")
        for function in statement.find_all(exp.Func):
            if not isinstance(function, self._allowed_expression_functions):
                raise AnalyticsQueryRefused("SQL functions are not allowlisted")


@dataclass(frozen=True)
class AnalyticsCostGate:
    """Pinned EXPLAIN JSON cost threshold before an analytics statement may execute."""

    maximum_total_cost: float = 10_000

    def enforce(self, explain_result: object) -> None:
        if not isinstance(explain_result, list) or not explain_result:
            raise AnalyticsQueryRefused("Cost gate received an invalid EXPLAIN result")
        first = explain_result[0]
        if not isinstance(first, Mapping):
            raise AnalyticsQueryRefused("Cost gate received an invalid EXPLAIN plan")
        plan = first.get("Plan")
        if not isinstance(plan, Mapping):
            raise AnalyticsQueryRefused("Cost gate received an EXPLAIN result without a plan")
        total_cost = plan.get("Total Cost")
        if not isinstance(total_cost, (float, int)) or total_cost > self.maximum_total_cost:
            raise AnalyticsQueryRefused("Query exceeds the approved cost limit")


class AnalyticsCopilotService:
    """Model-free M8 question path: question -> plan -> SQL -> validation -> bounded answer."""

    def __init__(
        self,
        *,
        executor: AnalyticsExecutor,
        clock: Callable[[], datetime],
        sql_validator: AnalyticsSqlValidator | None = None,
        run_store: AnalyticsRunStore | None = None,
        id_factory: Callable[[str], str] = new_resource_id,
    ) -> None:
        self._executor = executor
        self._clock = clock
        self._sql_validator = sql_validator or AnalyticsSqlValidator()
        self._run_store = run_store or InMemoryAnalyticsRunStore()
        self._id_factory = id_factory

    def answer_question(
        self,
        *,
        actor_id: str,
        facility_id: str,
        snapshot_id: str | None,
        comparison_snapshot_id: str | None,
        question: str,
    ) -> AnalyticsAnswer:
        plan = self._classify(
            facility_id=facility_id,
            snapshot_id=snapshot_id,
            comparison_snapshot_id=comparison_snapshot_id,
            question=question,
        )
        compiled = self._compile(plan)
        self._sql_validator.validate(compiled)
        execution = self._executor.execute(compiled)
        query_digest = domain_digest(
            "analytics_query",
            1,
            canonical_json_bytes(
                {
                    "plan": plan.canonical_dict(),
                    "sql": compiled.sql,
                    "parameters": compiled.parameters,
                }
            ),
        )
        scope = {"facility_id": facility_id}
        if snapshot_id:
            scope["snapshot_id"] = snapshot_id
        created_at = self._clock()
        result = tuple(_result_row(row) for row in execution.rows)
        result_digest = domain_digest(
            "analytics_query_result", 1, canonical_json_bytes({"rows": result})
        )
        run = AnalyticsQueryRun(
            resource_id=self._id_factory("qry"),
            request_digest=domain_digest(
                "analytics_query_request",
                1,
                canonical_json_bytes(
                    {
                        "actor_id": actor_id,
                        "facility_id": facility_id,
                        "question": question,
                        "plan": plan.canonical_dict(),
                        "query_digest": query_digest,
                        "created_at": canonical_timestamp(created_at),
                    }
                ),
            ),
            actor_id=actor_id,
            facility_id=facility_id,
            snapshot_id=snapshot_id,
            question=question,
            plan=plan,
            query_digest=query_digest,
            referenced_views=compiled.referenced_views,
            data_cutoff=execution.data_cutoff,
            result=result,
            result_digest=result_digest,
            warnings=execution.warnings,
            created_at=created_at,
        )
        self._run_store.insert(run)
        return AnalyticsAnswer(
            question=question,
            scope=scope,
            plan=plan,
            result=result,
            units=_units_for_plan(plan),
            assumptions=_assumptions_for_plan(plan),
            referenced_views=compiled.referenced_views,
            query_digest=query_digest,
            lineage=execution.lineage,
            data_cutoff=execution.data_cutoff,
            warnings=execution.warnings,
            query_run_id=run.resource_id,
        )

    @staticmethod
    def _classify(
        *,
        facility_id: str,
        snapshot_id: str | None,
        comparison_snapshot_id: str | None,
        question: str,
    ) -> AnalyticalPlan:
        normalized = " ".join(question.lower().split())
        template_id = {
            "why did availability decline between snapshots?": "availability_change",
            "show snapshot summary": "snapshot_summary",
            "which inventory lots contribute most to reserves?": "reserve_contributors",
            "which receivables were excluded due to age?": "receivable_age_exclusions",
            "what is hedge ratio by delivery month?": "hedge_ratio_month",
            "which scenario produces lowest irc?": "scenario_worst_stressed_cbb",
            "which approved facts changed since previous decision?": "approved_fact_changes",
        }.get(normalized)
        if template_id is None:
            raise AnalyticsQueryRefused(
                "Question is ambiguous or not an approved analytical template"
            )
        requires_comparison = template_id in {"availability_change", "approved_fact_changes"}
        if snapshot_id is None:
            raise AnalyticsQueryRefused("Question requires an immutable snapshot ID")
        if requires_comparison and comparison_snapshot_id is None:
            raise AnalyticsQueryRefused("Availability comparison requires both snapshot IDs")
        return AnalyticalPlan(
            template_id=template_id,
            facility_id=facility_id,
            snapshot_id=snapshot_id,
            comparison_snapshot_id=comparison_snapshot_id,
        )

    @staticmethod
    def _compile(plan: AnalyticalPlan) -> CompiledAnalyticsQuery:
        parameters: dict[str, str | int | None] = {
            "facility_id": plan.facility_id,
            "snapshot_id": plan.snapshot_id,
            "comparison_snapshot_id": plan.comparison_snapshot_id,
            "row_limit": plan.row_limit,
        }
        if plan.template_id == "availability_change":
            return CompiledAnalyticsQuery(
                sql=(
                    "SELECT current.facility_id, current.snapshot_id, "
                    "previous.snapshot_id AS previous_snapshot_id, "
                    "current.contractual_availability, "
                    "previous.contractual_availability AS previous_contractual_availability, "
                    "current.currency "
                    "FROM analytics.snapshot_summary AS current "
                    "JOIN analytics.snapshot_summary AS previous "
                    "ON previous.facility_id = current.facility_id "
                    "WHERE current.facility_id = :facility_id "
                    "AND current.snapshot_id = :snapshot_id "
                    "AND previous.snapshot_id = :comparison_snapshot_id "
                    "LIMIT :row_limit"
                ),
                parameters=parameters,
                referenced_views=("analytics.snapshot_summary",),
            )
        if plan.template_id == "snapshot_summary":
            return _single_snapshot_query(
                "SELECT facility_id, snapshot_id, as_of, currency, contractual_borrowing_base, "
                "contractual_availability, internal_risk_capacity, snapshot_digest "
                "FROM analytics.snapshot_summary",
                "snapshot_summary",
                parameters,
            )
        if plan.template_id == "reserve_contributors":
            return _single_snapshot_query(
                "SELECT facility_id, snapshot_id, reserve_type, reserve_amount, currency, "
                "output_digest "
                "FROM analytics.reserve_contribution",
                "reserve_contribution",
                parameters,
                order_by="reserve_amount DESC",
            )
        if plan.template_id == "receivable_age_exclusions":
            return _single_snapshot_query(
                "SELECT facility_id, snapshot_id, receivable_id, open_amount, advanced_value, "
                "reason_codes, currency, output_digest "
                "FROM analytics.receivable_eligibility "
                "WHERE reason_codes ? 'RECEIVABLE_AGE_EXCEEDED'",
                "receivable_eligibility",
                parameters,
                order_by="open_amount DESC",
            )
        if plan.template_id == "hedge_ratio_month":
            return _single_snapshot_query(
                "SELECT facility_id, snapshot_id, delivery_month, physical_exposure, "
                "hedge_delta_exposure, net_price_exposure, exposure_unit, output_digest "
                "FROM analytics.hedge_ratio_month",
                "hedge_ratio_month",
                parameters,
                order_by="delivery_month",
            )
        if plan.template_id == "scenario_worst_stressed_cbb":
            return _single_snapshot_query(
                "SELECT facility_id, snapshot_id, scenario_id, scenario_family, stressed_cbb, "
                "cbb_deficiency, margin_liquidity_shortfall, currency, output_digest "
                "FROM analytics.scenario_result",
                "scenario_result",
                parameters,
                order_by="stressed_cbb ASC",
            )
        if plan.template_id == "approved_fact_changes":
            return CompiledAnalyticsQuery(
                sql=(
                    "SELECT current.facility_id, current.snapshot_id, "
                    "previous.snapshot_id AS previous_snapshot_id, current.fact_type, "
                    "current.subject_id, current.period, current.value AS current_value, "
                    "previous.value AS previous_value, current.approved_fact_digest "
                    "FROM analytics.approved_fact_snapshot AS current "
                    "LEFT JOIN analytics.approved_fact_snapshot AS previous "
                    "ON previous.facility_id = current.facility_id "
                    "AND previous.snapshot_id = :comparison_snapshot_id "
                    "AND previous.fact_type = current.fact_type "
                    "AND previous.subject_id = current.subject_id "
                    "AND previous.period = current.period "
                    "WHERE current.facility_id = :facility_id "
                    "AND current.snapshot_id = :snapshot_id "
                    "AND current.value IS DISTINCT FROM previous.value "
                    "LIMIT :row_limit"
                ),
                parameters=parameters,
                referenced_views=("analytics.approved_fact_snapshot",),
            )
        raise AnalyticsQueryRefused("Unknown analytical plan template")


def _single_snapshot_query(
    select_sql: str,
    view: str,
    parameters: Mapping[str, str | int | None],
    *,
    order_by: str | None = None,
) -> CompiledAnalyticsQuery:
    predicate = "facility_id = :facility_id AND snapshot_id = :snapshot_id"
    if " WHERE " in select_sql:
        predicate = f"{predicate} AND {select_sql.rsplit(' WHERE ', 1)[1]}"
        select_sql = select_sql.rsplit(" WHERE ", 1)[0]
    ordering = f" ORDER BY {order_by}" if order_by else ""
    return CompiledAnalyticsQuery(
        sql=(f"{select_sql} WHERE {predicate}{ordering} LIMIT :row_limit"),
        parameters=parameters,
        referenced_views=(f"analytics.{view}",),
    )


def _units_for_plan(plan: AnalyticalPlan) -> Mapping[str, str]:
    if plan.template_id == "hedge_ratio_month":
        return {"physical_exposure": "published exposure unit"}
    if plan.template_id == "approved_fact_changes":
        return {"value": "fact-type-specific canonical JSON"}
    return {"currency_values": "snapshot currency amount"}


def _assumptions_for_plan(plan: AnalyticalPlan) -> tuple[str, ...]:
    assumptions = [
        "Read-only curated analytics views only.",
        "Result does not calculate, approve, or alter an authoritative value.",
    ]
    if plan.template_id == "scenario_worst_stressed_cbb":
        assumptions.append(
            "M4A publishes IRC at snapshot scope; scenario rows are ranked by published "
            "stressed CBB, not scenario-specific IRC."
        )
    return tuple(assumptions)


def _result_row(row: Mapping[str, object]) -> Mapping[str, object]:
    return {str(key): _result_value(value) for key, value in row.items()}


def _result_value(value: object) -> object:
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _result_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_result_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)
