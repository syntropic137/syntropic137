"""Read-only query service for session cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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

    async def list_all(self) -> list[SessionCost]:
        """List cost data for all sessions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for sessions that
        haven't completed yet.
        """
        async with self._pool.acquire() as conn:
            # 1. Get authoritative data from session_summary events
            summary_rows = await conn.fetch(
                _LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY
            )
            summarized_session_ids = {row["session_id"] for row in summary_rows}

            # 2. Get in-progress sessions from token_usage (no summary yet)
            token_rows = await conn.fetch(
                _LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE
            )

            # 3. Get tool counts per session
            tool_rows = await conn.fetch(
                _TOOL_COUNT_BY_SESSION_QUERY, TOOL_EXECUTION_COMPLETED
            )
            tool_counts: dict[str, int] = {
                row["session_id"]: row["cnt"] for row in tool_rows
            }

            # 4. Get started_at per session
            started_rows = await conn.fetch(
                _STARTED_AT_BY_SESSION_QUERY, SESSION_STARTED
            )
            started_map: dict[str, Any] = {
                row["session_id"]: row["started_at"] for row in started_rows
            }

            results: list[SessionCost] = []

            # Build from session_summary rows (authoritative)
            for row in summary_rows:
                sid = row["session_id"]
                sdk_cost = (
                    Decimal(str(row["sdk_cost"]))
                    if row["sdk_cost"] is not None
                    else self._cost_calculator.calculate_token_cost(
                        input_tokens=row["total_input"] or 0,
                        output_tokens=row["total_output"] or 0,
                        cache_creation=row["cache_creation"] or 0,
                        cache_read=row["cache_read"] or 0,
                    )
                )
                sc = SessionCost(session_id=sid)
                sc.input_tokens = row["total_input"] or 0
                sc.output_tokens = row["total_output"] or 0
                sc.cache_creation_tokens = row["cache_creation"] or 0
                sc.cache_read_tokens = row["cache_read"] or 0
                sc.total_cost_usd = sdk_cost
                sc.token_cost_usd = sdk_cost
                sc.tool_calls = tool_counts.get(sid, 0)
                sc.turns = row["num_turns"] or 0
                sc.duration_ms = float(row["duration_ms_val"] or 0)
                sc.execution_id = row["execution_id"]
                sc.phase_id = row["phase_id"]
                sc.started_at = started_map.get(sid)
                sc.completed_at = row["completed_at"]
                sc.is_finalized = True
                if row["agent_model"]:
                    sc.agent_model = row["agent_model"]
                results.append(sc)

            # Build from token_usage rows (in-progress, no summary yet)
            for row in token_rows:
                sid = row["session_id"]
                if sid in summarized_session_ids:
                    continue  # already covered by session_summary

                total_input = row["total_input"] or 0
                total_output = row["total_output"] or 0
                cache_creation = row["cache_creation"] or 0
                cache_read = row["cache_read"] or 0

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
                sc.execution_id = row["execution_id"]
                sc.phase_id = row["phase_id"]
                sc.started_at = started_map.get(sid) or row["started_at"]
                if row["agent_model"]:
                    sc.agent_model = row["agent_model"]
                results.append(sc)

            return results
