"""Read-only query service for session cost data.

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

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# List all sessions with cost data from session_summary (authoritative).
_LIST_ALL_FROM_SUMMARY_QUERY = """
SELECT
    session_id,
    (data->>'total_input_tokens')::int as total_input,
    (data->>'total_output_tokens')::int as total_output,
    COALESCE((data->>'cache_creation_tokens')::int, 0) as cache_creation,
    COALESCE((data->>'cache_read_tokens')::int, 0) as cache_read,
    (data->>'total_cost_usd')::numeric as sdk_cost,
    (data->>'duration_ms')::bigint as duration_ms_val,
    data->>'model' as agent_model,
    (data->>'num_turns')::int as num_turns,
    (data->>'tool_count')::int as tool_count,
    time as completed_at,
    execution_id,
    phase_id
FROM agent_events
WHERE event_type = $1
ORDER BY time DESC
LIMIT $2
"""

# Fallback: list sessions from token_usage events (for in-progress sessions
# that don't yet have a session_summary).
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = """
SELECT
    session_id,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    MAX(data->>'model') as agent_model,
    MAX(execution_id) as execution_id,
    MAX(phase_id) as phase_id
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""

_TOOL_COUNT_BY_SESSION_QUERY = """
SELECT session_id, COUNT(*) as cnt
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""

_STARTED_AT_BY_SESSION_QUERY = """
SELECT session_id, MIN(time) as started_at
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""


class SessionCostQueryService:
    """Read-only query service for session cost data.

    Reads exclusively from TimescaleDB (Lane 2: Observability).
    The projection store is NOT used for reads — it serves only
    the write-side event handlers in SessionCostProjection.

    See #532 for the architectural rationale.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        cost_calculator: CostCalculator | None = None,
    ) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def get(self, session_id: str) -> SessionCost | None:
        """Get cost data for a single session.

        Delegates to TimescaleSessionCostQuery which handles the
        session_summary → token_usage fallback logic.
        """
        query = TimescaleSessionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate(session_id)

    async def list_all(self, limit: int = 500) -> list[SessionCost]:
        """List cost data for all sessions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for sessions that
        haven't completed yet.

        Args:
            limit: Maximum number of results (pushed down to SQL).
        """
        async with self._pool.acquire() as conn:
            summary_rows = await conn.fetch(_LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY, limit)
            summarized_session_ids = {row["session_id"] for row in summary_rows}  # type: ignore[index]
            token_rows = await conn.fetch(_LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE)
            tool_counts = await self._fetch_tool_counts(conn)
            started_map = await self._fetch_started_map(conn)

            results: list[SessionCost] = []
            for row in summary_rows:
                results.append(self._build_from_summary(row, tool_counts, started_map))
            for row in token_rows:
                sid = row["session_id"]  # type: ignore[index]
                if sid not in summarized_session_ids:
                    results.append(self._build_from_token_usage(row, tool_counts, started_map))
            return results

    async def _fetch_tool_counts(self, conn: object) -> dict[str, int]:
        """Fetch tool call counts per session."""
        rows = await conn.fetch(_TOOL_COUNT_BY_SESSION_QUERY, TOOL_EXECUTION_COMPLETED)  # type: ignore[union-attr]
        return {row["session_id"]: row["cnt"] for row in rows}  # type: ignore[index]

    async def _fetch_started_map(self, conn: object) -> dict[str, object]:
        """Fetch the earliest started_at timestamp per session."""
        rows = await conn.fetch(_STARTED_AT_BY_SESSION_QUERY, SESSION_STARTED)  # type: ignore[union-attr]
        return {row["session_id"]: row["started_at"] for row in rows}  # type: ignore[index]

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
        started_map: dict[str, object],
    ) -> SessionCost:
        """Build a SessionCost from a session_summary row."""
        sid = row["session_id"]  # type: ignore[index]
        cost = self._resolve_cost(row)
        sc = SessionCost(session_id=sid)
        sc.input_tokens = row["total_input"] or 0  # type: ignore[index]
        sc.output_tokens = row["total_output"] or 0  # type: ignore[index]
        sc.cache_creation_tokens = row["cache_creation"] or 0  # type: ignore[index]
        sc.cache_read_tokens = row["cache_read"] or 0  # type: ignore[index]
        sc.total_cost_usd = cost
        sc.token_cost_usd = cost
        sc.tool_calls = tool_counts.get(sid, 0)
        sc.turns = row["num_turns"] or 0  # type: ignore[index]
        sc.duration_ms = float(row["duration_ms_val"] or 0)  # type: ignore[index]
        sc.execution_id = row["execution_id"]  # type: ignore[index]
        sc.phase_id = row["phase_id"]  # type: ignore[index]
        sc.started_at = started_map.get(sid)  # type: ignore[arg-type]
        sc.completed_at = row["completed_at"]  # type: ignore[index]
        sc.is_finalized = True
        if row["agent_model"]:  # type: ignore[index]
            sc.agent_model = row["agent_model"]  # type: ignore[index]
        return sc

    def _build_from_token_usage(
        self,
        row: object,
        tool_counts: dict[str, int],
        started_map: dict[str, object],
    ) -> SessionCost:
        """Build a SessionCost from a token_usage aggregate row (in-progress)."""
        sid = row["session_id"]  # type: ignore[index]
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
        sc = SessionCost(session_id=sid)
        sc.input_tokens = total_input
        sc.output_tokens = total_output
        sc.cache_creation_tokens = cache_creation
        sc.cache_read_tokens = cache_read
        sc.total_cost_usd = cost
        sc.token_cost_usd = cost
        sc.tool_calls = tool_counts.get(sid, 0)
        sc.execution_id = row["execution_id"]  # type: ignore[index]
        sc.phase_id = row["phase_id"]  # type: ignore[index]
        sc.started_at = started_map.get(sid) or row["started_at"]  # type: ignore[index,arg-type]
        if row["agent_model"]:  # type: ignore[index]
            sc.agent_model = row["agent_model"]  # type: ignore[index]
        return sc
