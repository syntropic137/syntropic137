"""Read-only query service for execution cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# List all executions with cost data from session_summary (authoritative).
_LIST_ALL_FROM_SUMMARY_QUERY = """
SELECT
    execution_id,
    SUM((data->>'total_input_tokens')::int) as total_input,
    SUM((data->>'total_output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    SUM((data->>'total_cost_usd')::numeric) as sdk_cost,
    SUM(COALESCE((data->>'duration_ms')::bigint, 0)) as duration_ms_val,
    SUM(COALESCE((data->>'num_turns')::int, 0)) as total_turns,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as completed_at
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
ORDER BY MAX(time) DESC
LIMIT $2
"""

# Fallback: list executions from token_usage (in-progress, no summary yet)
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = """
SELECT
    execution_id,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
"""

_TOOL_COUNT_BY_EXECUTION_QUERY = """
SELECT execution_id, COUNT(*) as cnt
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
"""

# Per-execution, per-phase cost breakdown
_COST_BY_PHASE_QUERY = """
SELECT
    execution_id,
    phase_id,
    SUM((data->>'total_cost_usd')::numeric) as phase_cost
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
  AND phase_id IS NOT NULL
GROUP BY execution_id, phase_id
"""

# Per-execution, per-model cost breakdown
_COST_BY_MODEL_QUERY = """
SELECT
    execution_id,
    data->>'model' as model,
    SUM((data->>'total_cost_usd')::numeric) as model_cost
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
  AND data->>'model' IS NOT NULL
GROUP BY execution_id, data->>'model'
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
            summarized_exec_ids = {row["execution_id"] for row in summary_rows}  # type: ignore[index]
            token_rows = await conn.fetch(_LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE)
            tool_counts = await self._fetch_tool_counts(conn)
            phase_map = await self._fetch_breakdown_map(
                conn, _COST_BY_PHASE_QUERY, "phase_id", "phase_cost"
            )
            model_map = await self._fetch_breakdown_map(
                conn, _COST_BY_MODEL_QUERY, "model", "model_cost"
            )

            results: list[ExecutionCost] = []
            for row in summary_rows:
                results.append(self._build_from_summary(row, tool_counts, phase_map, model_map))
            for row in token_rows:
                eid = row["execution_id"]  # type: ignore[index]
                if eid not in summarized_exec_ids:
                    results.append(self._build_from_token_usage(row, tool_counts))
            return results

    async def _fetch_tool_counts(self, conn: object) -> dict[str, int]:
        """Fetch tool call counts per execution."""
        rows = await conn.fetch(_TOOL_COUNT_BY_EXECUTION_QUERY, TOOL_EXECUTION_COMPLETED)  # type: ignore[union-attr]
        return {row["execution_id"]: row["cnt"] for row in rows}  # type: ignore[index]

    async def _fetch_breakdown_map(
        self,
        conn: object,
        query: str,
        key_field: str,
        value_field: str,
    ) -> dict[str, dict[str, Decimal]]:
        """Fetch a per-execution breakdown map (phase or model) from a query."""
        rows = await conn.fetch(query, SESSION_SUMMARY)  # type: ignore[union-attr]
        breakdown: dict[str, dict[str, Decimal]] = {}
        for row in rows:  # type: ignore[union-attr]
            eid = row["execution_id"]  # type: ignore[index]
            if eid not in breakdown:
                breakdown[eid] = {}
            value = row[value_field]  # type: ignore[index]
            if value is not None:
                breakdown[eid][row[key_field]] = Decimal(str(value))  # type: ignore[index]
        return breakdown

    def _resolve_cost(self, row: object) -> Decimal:
        """Resolve cost from sdk_cost field or calculate from token counts."""
        sdk_cost = row["sdk_cost"]  # type: ignore[index]
        if sdk_cost is not None:
            return Decimal(str(sdk_cost))
        return self._cost_calculator.calculate_token_cost(
            input_tokens=row["total_input"] or 0,  # type: ignore[index]
            output_tokens=row["total_output"] or 0,  # type: ignore[index]
            cache_creation=row["cache_creation"] or 0,  # type: ignore[index]
            cache_read=row["cache_read"] or 0,  # type: ignore[index]
        )

    def _build_from_summary(
        self,
        row: object,
        tool_counts: dict[str, int],
        phase_map: dict[str, dict[str, Decimal]],
        model_map: dict[str, dict[str, Decimal]],
    ) -> ExecutionCost:
        """Build an ExecutionCost from a session_summary aggregate row."""
        eid = row["execution_id"]  # type: ignore[index]
        cost = self._resolve_cost(row)
        return ExecutionCost(
            execution_id=eid,
            session_count=row["session_count"] or 0,  # type: ignore[index]
            session_ids=list(row["session_ids"] or []),  # type: ignore[index]
            total_cost_usd=cost,
            token_cost_usd=cost,
            input_tokens=row["total_input"] or 0,  # type: ignore[index]
            output_tokens=row["total_output"] or 0,  # type: ignore[index]
            cache_creation_tokens=row["cache_creation"] or 0,  # type: ignore[index]
            cache_read_tokens=row["cache_read"] or 0,  # type: ignore[index]
            tool_calls=tool_counts.get(eid, 0),
            turns=row["total_turns"] or 0,  # type: ignore[index]
            duration_ms=float(row["duration_ms_val"] or 0),  # type: ignore[index]
            cost_by_phase=phase_map.get(eid, {}),
            cost_by_model=model_map.get(eid, {}),
            started_at=row["started_at"],  # type: ignore[index]
            completed_at=row["completed_at"],  # type: ignore[index]
        )

    def _build_from_token_usage(
        self,
        row: object,
        tool_counts: dict[str, int],
    ) -> ExecutionCost:
        """Build an ExecutionCost from a token_usage aggregate row (in-progress)."""
        eid = row["execution_id"]  # type: ignore[index]
        total_input = row["total_input"] or 0  # type: ignore[index]
        total_output = row["total_output"] or 0  # type: ignore[index]
        cache_creation = row["cache_creation"] or 0  # type: ignore[index]
        cache_read = row["cache_read"] or 0  # type: ignore[index]
        cost = self._cost_calculator.calculate_token_cost(
            input_tokens=total_input,
            output_tokens=total_output,
            cache_creation=cache_creation,
            cache_read=cache_read,
        )
        return ExecutionCost(
            execution_id=eid,
            session_count=row["session_count"] or 0,  # type: ignore[index]
            session_ids=list(row["session_ids"] or []),  # type: ignore[index]
            total_cost_usd=cost,
            token_cost_usd=cost,
            input_tokens=total_input,
            output_tokens=total_output,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            tool_calls=tool_counts.get(eid, 0),
            started_at=row["started_at"],  # type: ignore[index]
            completed_at=row.get("last_observation"),  # type: ignore[union-attr]
        )
