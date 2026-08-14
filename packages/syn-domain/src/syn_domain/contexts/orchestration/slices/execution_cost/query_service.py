"""Read-only query service for execution cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

    import asyncpg

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
    price_grouped_session_summary,
    price_grouped_token_usage,
    price_phase_rows,
)
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# List all executions with cost data from session_summary (authoritative).
#
# Grouped by (execution_id, model): an execution can span multiple
# sessions/phases on different models, so pricing must happen per model
# group rather than flattening all rows for an execution into one SUM and
# pricing them as a single model (issue #788). The most-recent-N-executions
# selection happens in ``recent_executions`` first, so LIMIT still counts
# executions rather than (execution, model) groups.
#
# Also grouped on `total_cost_usd IS NULL` so that two summaries on the
# SAME model - one SDK-priced, one not - do not merge into a group whose
# non-NULL cost SUM suppresses the token fallback while still carrying the
# unpriced row's tokens. See the matching note in ``timescale_query.py``.
_LIST_ALL_FROM_SUMMARY_QUERY = """
WITH recent_executions AS (
    SELECT execution_id, MAX(time) as last_time
    FROM agent_events
    WHERE event_type = $1
      AND execution_id IS NOT NULL
    GROUP BY execution_id
    ORDER BY last_time DESC
    LIMIT $2
)
SELECT
    a.execution_id,
    a.data->>'model' as model,
    SUM((a.data->>'total_input_tokens')::int) as total_input,
    SUM((a.data->>'total_output_tokens')::int) as total_output,
    SUM(COALESCE((a.data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((a.data->>'cache_read_tokens')::int, 0)) as cache_read,
    SUM((a.data->>'total_cost_usd')::numeric) as sdk_cost,
    SUM(COALESCE((a.data->>'duration_ms')::bigint, 0)) as duration_ms_val,
    SUM(COALESCE((a.data->>'num_turns')::int, 0)) as total_turns,
    COUNT(DISTINCT a.session_id) as session_count,
    ARRAY_AGG(DISTINCT a.session_id) as session_ids,
    MIN(a.time) as started_at,
    MAX(a.time) as completed_at,
    COUNT(*) as observation_count
FROM agent_events a
JOIN recent_executions r ON r.execution_id = a.execution_id
WHERE a.event_type = $1
GROUP BY a.execution_id, a.data->>'model', ((a.data->>'total_cost_usd') IS NULL)
"""

# Fallback: list executions from token_usage (in-progress, no summary yet).
#
# Grouped by (execution_id, model): an execution can span multiple
# sessions/phases on different models, so pricing must happen per model
# group rather than flattening all tokens into one SUM per execution and
# pricing them as a single model (issue #788). Rows for the same
# execution_id are merged in Python via ``price_grouped_token_usage``.
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = """
SELECT
    execution_id,
    data->>'model' as model,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    COUNT(*) as observation_count
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id, data->>'model'
"""

_TOOL_COUNT_BY_EXECUTION_QUERY = """
SELECT execution_id, COUNT(*) as cnt
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
"""

# Per-execution, per-phase cost breakdown.
#
# Carries model + token columns and groups on the null-cost flag so each
# row prices through the same rule as the execution total. A flat
# SUM(total_cost_usd) GROUP BY phase_id drops phases with no SDK cost
# (PostgreSQL excludes NULLs from SUM) while the total prices them, so the
# breakdown sums to less than the total it decomposes (issue #812).
_COST_BY_PHASE_QUERY = """
SELECT
    execution_id,
    phase_id,
    data->>'model' as model,
    SUM((data->>'total_input_tokens')::int) as total_input,
    SUM((data->>'total_output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    SUM((data->>'total_cost_usd')::numeric) as sdk_cost,
    COUNT(*) as observation_count
FROM agent_events
WHERE event_type = $1
  AND execution_id = ANY($2::text[])
GROUP BY execution_id, phase_id, data->>'model', ((data->>'total_cost_usd') IS NULL)
"""


class ExecutionCostQueryService:
    """Read-only query service for execution cost data.

    Reads exclusively from TimescaleDB (Lane 2: Observability).
    The projection store is NOT used for reads — it serves only
    the write-side event handlers in ExecutionCostProjection.

    See #532 for the architectural rationale.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        cost_calculator: CostCalculator | None = None,
    ) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def get(self, execution_id: str) -> ExecutionCost | None:
        """Get cost data for a single execution.

        Delegates to TimescaleExecutionCostQuery which handles the
        session_summary -> token_usage fallback logic.
        """
        query = TimescaleExecutionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate(execution_id)

    async def list_all(self, limit: int = 500) -> list[ExecutionCost]:
        """List cost data for all executions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for executions that
        haven't completed yet.

        Args:
            limit: Maximum number of results (pushed down to SQL).
        """
        async with self._pool.acquire() as conn:
            summary_rows = await conn.fetch(_LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY, limit)
            summary_rows_by_execution = self._group_rows_by_execution(summary_rows)
            token_rows = await conn.fetch(_LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE)
            tool_counts = await self._fetch_tool_counts(conn)
            phase_map = await self._fetch_phase_cost_map(conn, list(summary_rows_by_execution))

            results: list[ExecutionCost] = []
            for eid, rows in summary_rows_by_execution.items():
                results.append(self._build_from_summary(eid, rows, tool_counts, phase_map))

            token_rows_by_execution = self._group_rows_by_execution(
                token_rows, exclude=summary_rows_by_execution.keys()
            )
            for eid, rows in token_rows_by_execution.items():
                results.append(self._build_from_token_usage(eid, rows, tool_counts))
            return results

    @staticmethod
    def _group_rows_by_execution(
        rows: list[asyncpg.Record],
        exclude: Iterable[str] = (),
    ) -> dict[str, list[asyncpg.Record]]:
        """Group model-grouped rows by execution_id, skipping excluded execution IDs."""
        excluded = set(exclude)
        rows_by_execution: dict[str, list[asyncpg.Record]] = {}
        for row in rows:
            eid = row["execution_id"]  # type: ignore[index]
            if eid in excluded:
                continue
            rows_by_execution.setdefault(eid, []).append(row)
        return rows_by_execution

    async def _fetch_tool_counts(self, conn: object) -> dict[str, int]:
        """Fetch tool call counts per execution."""
        rows = await conn.fetch(_TOOL_COUNT_BY_EXECUTION_QUERY, TOOL_EXECUTION_COMPLETED)  # type: ignore[union-attr]
        return {row["execution_id"]: row["cnt"] for row in rows}  # type: ignore[index]

    async def _fetch_phase_cost_map(
        self, conn: object, execution_ids: list[str]
    ) -> dict[str, dict[str, Decimal]]:
        """Fetch per-execution, per-phase costs, priced like the execution total.

        Rows arrive split by (execution, phase, model, priced?) so an
        unpriced summary keeps its own group and can be priced from its own
        tokens. Grouping the rows per execution and delegating to
        ``price_phase_rows`` reuses the exact rule the execution total uses,
        which is what keeps the two reconcilable (issue #812).

        Bounded to ``execution_ids`` - the executions ``list_all`` actually
        selected. The finer grouping returns up to two rows per model per
        phase, so scanning every historical execution to then discard most
        of them costs real transfer and memory.
        """
        if not execution_ids:
            return {}
        rows = await conn.fetch(  # type: ignore[union-attr]
            _COST_BY_PHASE_QUERY, SESSION_SUMMARY, execution_ids
        )
        rows_by_execution: dict[str, list[asyncpg.Record]] = {}
        for row in rows:  # type: ignore[union-attr]
            eid = row["execution_id"]  # type: ignore[index]
            rows_by_execution.setdefault(eid, []).append(row)
        return {
            eid: price_phase_rows(execution_rows, self._cost_calculator)
            for eid, execution_rows in rows_by_execution.items()
        }

    @staticmethod
    def _resolve_duration(
        duration_ms_val: object, started_at: object, completed_at: object
    ) -> float:
        """Resolve duration_ms, falling back to timestamp delta when the payload field is absent.

        session_summary events rarely carry duration_ms in their JSON payload,
        so the SQL SUM is usually 0. In that case compute from event timestamps.
        """
        explicit = float(duration_ms_val or 0)  # type: ignore[arg-type]
        if explicit:
            return explicit
        if started_at and completed_at:
            return (completed_at - started_at).total_seconds() * 1000  # type: ignore[union-attr,operator]
        return 0.0

    def _build_from_summary(
        self,
        execution_id: str,
        rows: list[asyncpg.Record],
        tool_counts: dict[str, int],
        phase_map: dict[str, dict[str, Decimal]],
    ) -> ExecutionCost:
        """Build an ExecutionCost from model-grouped session_summary rows.

        ``rows`` are all (execution_id, model) groups for this execution
        from ``_LIST_ALL_FROM_SUMMARY_QUERY``. Priced per group via
        ``price_grouped_session_summary`` - a plain ``SUM(total_cost_usd)``
        across mixed-model, partially-NULL-cost rows silently drops the NULL
        rows from the total instead of pricing them from that group's own
        tokens (issue #788).
        """
        grouped = price_grouped_session_summary(rows, self._cost_calculator)
        return ExecutionCost(
            execution_id=execution_id,
            session_count=len(grouped.session_ids),
            session_ids=grouped.session_ids,
            total_cost_usd=grouped.total_cost,
            token_cost_usd=grouped.total_cost,
            input_tokens=grouped.input_tokens,
            output_tokens=grouped.output_tokens,
            cache_creation_tokens=grouped.cache_creation,
            cache_read_tokens=grouped.cache_read,
            tool_calls=tool_counts.get(execution_id, 0),
            turns=grouped.total_turns,
            duration_ms=self._resolve_duration(
                grouped.duration_ms_raw, grouped.started_at, grouped.end_at
            ),
            cost_by_phase=phase_map.get(execution_id, {}),
            cost_by_model=grouped.cost_by_model,
            unpriced_observation_count=grouped.unpriced_observation_count,
            started_at=grouped.started_at,
            completed_at=grouped.end_at,
        )

    def _build_from_token_usage(
        self,
        execution_id: str,
        rows: list[asyncpg.Record],
        tool_counts: dict[str, int],
    ) -> ExecutionCost:
        """Build an ExecutionCost from model-grouped token_usage rows (in-progress).

        ``rows`` are all groups for this execution from
        ``_LIST_ALL_FROM_TOKEN_USAGE_QUERY`` (one row per model). They are
        merged and priced per model group via ``price_grouped_token_usage`` -
        an execution can span multiple sessions/models, so a flat SUM priced
        as a single model would be wrong (issue #788).
        """
        grouped = price_grouped_token_usage(rows, self._cost_calculator)
        return ExecutionCost(
            execution_id=execution_id,
            session_count=len(grouped.session_ids),
            session_ids=grouped.session_ids,
            total_cost_usd=grouped.total_cost,
            token_cost_usd=grouped.total_cost,
            input_tokens=grouped.input_tokens,
            output_tokens=grouped.output_tokens,
            cache_creation_tokens=grouped.cache_creation,
            cache_read_tokens=grouped.cache_read,
            tool_calls=tool_counts.get(execution_id, 0),
            duration_ms=self._resolve_duration(None, grouped.started_at, grouped.end_at),
            cost_by_model=grouped.cost_by_model,
            unpriced_observation_count=grouped.unpriced_observation_count,
            started_at=grouped.started_at,
            completed_at=grouped.end_at,
        )
