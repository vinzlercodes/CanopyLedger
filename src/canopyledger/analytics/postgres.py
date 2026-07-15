"""PostgreSQL M8 execution boundary: curated views, fixed settings, cost gate, rollback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, insert, text

from canopyledger.integrity.canonical import canonical_json_bytes
from canopyledger.persistence.schema import analytics_query_run

from .copilot import (
    AnalyticsCostGate,
    AnalyticsExecution,
    AnalyticsQueryRefused,
    AnalyticsQueryRun,
    CompiledAnalyticsQuery,
)


class PostgresAnalyticsExecutor:
    """Executes validated M8 SQL in a bounded repeatable-read analytics-only transaction."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cost_gate: AnalyticsCostGate | None = None,
        max_rows: int = 100,
        max_cells: int = 2_000,
        max_bytes: int = 1_000_000,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._cost_gate = cost_gate or AnalyticsCostGate()
        self._max_rows = max_rows
        self._max_cells = max_cells
        self._max_bytes = max_bytes

    def execute(self, query: CompiledAnalyticsQuery) -> AnalyticsExecution:
        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                connection.execute(text("SET LOCAL ROLE analytics_reader"))
                connection.execute(text("SET LOCAL search_path TO pg_catalog, analytics"))
                connection.execute(text("SET LOCAL statement_timeout = '2s'"))
                connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '3s'"))
                connection.execute(text("SET LOCAL work_mem = '8MB'"))
                connection.execute(text("SET LOCAL temp_file_limit = '8MB'"))
                explain = connection.execute(
                    text(f"EXPLAIN (FORMAT JSON) {query.sql}"), dict(query.parameters)
                ).scalar_one()
                self._cost_gate.enforce(explain)
                rows = tuple(
                    dict(row)
                    for row in connection.execute(
                        text(query.sql), dict(query.parameters)
                    ).mappings()
                )
                self._enforce_output_limits(rows)
                return AnalyticsExecution(
                    rows=rows,
                    data_cutoff=self._clock(),
                    lineage=_lineage(rows),
                )
            finally:
                transaction.rollback()

    def _enforce_output_limits(self, rows: tuple[dict[str, object], ...]) -> None:
        if len(rows) > self._max_rows:
            raise AnalyticsQueryRefused("Query exceeds the approved row limit")
        cells = sum(len(row) for row in rows)
        if cells > self._max_cells:
            raise AnalyticsQueryRefused("Query exceeds the approved cell limit")
        byte_count = len(repr(rows).encode("utf-8"))
        if byte_count > self._max_bytes:
            raise AnalyticsQueryRefused("Query exceeds the approved byte limit")


class PostgresAnalyticsRunStore:
    """Persists immutable M8 query/answer records outside analytics-reader reach."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def insert(self, run: AnalyticsQueryRun) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                insert(analytics_query_run).values(
                    resource_id=run.resource_id,
                    request_digest=run.request_digest,
                    actor_id=run.actor_id,
                    facility_id=run.facility_id,
                    snapshot_id=run.snapshot_id,
                    question=run.question,
                    analytical_plan=run.plan.canonical_dict(),
                    query_digest=run.query_digest,
                    referenced_views=list(run.referenced_views),
                    data_cutoff=run.data_cutoff,
                    canonical_result=canonical_json_bytes({"rows": run.result}),
                    result_digest=run.result_digest,
                    warnings=list(run.warnings),
                    created_at=run.created_at,
                )
            )


def _lineage(rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    names = (
        "approved_fact_digest",
        "internal_risk_capacity_digest",
        "output_digest",
        "snapshot_digest",
    )
    return tuple(
        sorted(
            {
                value
                for row in rows
                for name in names
                if isinstance((value := row.get(name)), str) and value.startswith("sha256:")
            }
        )
    )
