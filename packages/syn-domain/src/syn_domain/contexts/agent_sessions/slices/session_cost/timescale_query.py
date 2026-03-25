"""TimescaleDB fallback query for session cost calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

_SESSION_SUMMARY_QUERY = """
SELECT
    (data->>'total_input_tokens')::int as total_input,
    (data->>'total_output_tokens')::int as total_output,
    (data->>'cache_creation_tokens')::int as cache_creation,
    (data->>'cache_read_tokens')::int as cache_read,
    (data->>'total_cost_usd')::numeric as sdk_cost,
    (data->>'duration_ms')::bigint as duration_ms_val,
    data->>'model' as agent_model,
    time as completed_at,
    execution_id,
    phase_id
FROM agent_events
WHERE session_id = $1 AND event_type = $2
ORDER BY time DESC
LIMIT 1
"""

_TOKEN_USAGE_FALLBACK_QUERY = """
SELECT
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    MAX(data->>'workspace_id') as workspace_id,
    MAX(data->>'model') as agent_model,
    execution_id,
    phase_id
FROM agent_events
WHERE session_id = $1 AND event_type = $2
GROUP BY execution_id, phase_id
"""

_COUNT_QUERY = """
SELECT COUNT(*)
FROM agent_events
WHERE session_id = $1 AND event_type = $2
"""

_MIN_TIME_QUERY = """
SELECT MIN(time)
FROM agent_events
WHERE session_id = $1 AND event_type = $2
"""


def _extract_tokens(token_result: Any) -> tuple[int, int, int, int]:
    """Extract token counts from a DB result row."""
    return (
        token_result["total_input"] or 0,
        token_result["total_output"] or 0,
        token_result.get("cache_creation") or 0,
        token_result.get("cache_read") or 0,
    )


def _resolve_agent_model(exec_result: Any, token_result: Any) -> str | None:
    """Resolve agent model from session_summary or token_usage results."""
    if exec_result and exec_result["agent_model"]:
        return exec_result["agent_model"]
    if token_result and token_result.get("agent_model"):
        return token_result["agent_model"]
    return None


def _resolve_duration(
    exec_result: Any,
    token_result: Any,
    started_at: Any,
) -> tuple[Any, int | None]:
    """Resolve completed_at and duration_ms from available data."""
    completed_at = (
        exec_result["completed_at"] if exec_result else token_result.get("last_observation")
    )
    duration_ms_val = exec_result.get("duration_ms_val") if exec_result else None

    if duration_ms_val is not None:
        return completed_at, int(duration_ms_val)
    if started_at and completed_at:
        return completed_at, int((completed_at - started_at).total_seconds() * 1000)
    return completed_at, None


class TimescaleSessionCostQuery:
    """Calculates session cost directly from TimescaleDB observations."""

    def __init__(self, pool: Any, cost_calculator: CostCalculator | None = None) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def _query_token_data(self, conn: Any, session_id: str) -> tuple[Any, Any]:
        """Query session_summary or fall back to token_usage aggregation.

        Returns (exec_result, token_result) tuple.
        """
        exec_result = await conn.fetchrow(_SESSION_SUMMARY_QUERY, session_id, SESSION_SUMMARY)

        if not exec_result or exec_result["total_input"] is None:
            token_result = await conn.fetchrow(_TOKEN_USAGE_FALLBACK_QUERY, session_id, TOKEN_USAGE)
        else:
            token_result = exec_result

        return exec_result, token_result

    def _calculate_cost(
        self,
        exec_result: Any,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
    ) -> Decimal:
        """Calculate cost from SDK value or token-based estimation."""
        sdk_cost = exec_result.get("sdk_cost") if exec_result else None
        if sdk_cost is not None:
            return Decimal(str(sdk_cost))
        return self._cost_calculator.calculate_token_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation=cache_creation,
            cache_read=cache_read,
        )

    @staticmethod
    def _build_session_cost(
        session_id: str,
        exec_result: Any,
        token_result: Any,
        total_cost: Decimal,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        tool_count: int,
        started_at: Any,
        completed_at: Any,
        duration_ms: int | None,
    ) -> SessionCost:
        """Assemble a SessionCost from resolved query fields."""
        sc = SessionCost(session_id=session_id)
        sc.input_tokens = input_tokens
        sc.output_tokens = output_tokens
        sc.cache_creation_tokens = cache_creation
        sc.cache_read_tokens = cache_read
        sc.tool_calls = tool_count
        sc.token_cost_usd = total_cost
        sc.total_cost_usd = total_cost
        agent_model = _resolve_agent_model(exec_result, token_result)
        if agent_model:
            sc.agent_model = agent_model
        sc.started_at = started_at
        sc.execution_id = token_result.get("execution_id")
        sc.phase_id = token_result.get("phase_id")
        sc.workspace_id = token_result.get("workspace_id")
        if completed_at:
            sc.completed_at = completed_at
        if duration_ms is not None:
            sc.duration_ms = duration_ms
        return sc

    async def calculate(self, session_id: str) -> SessionCost | None:
        """Calculate session cost from TimescaleDB."""
        async with self._pool.acquire() as conn:
            exec_result, token_result = await self._query_token_data(conn, session_id)
            if not token_result or token_result["total_input"] is None:
                return None

            tool_count = await conn.fetchval(_COUNT_QUERY, session_id, TOOL_EXECUTION_COMPLETED)

            started_at = await conn.fetchval(_MIN_TIME_QUERY, session_id, SESSION_STARTED)
            if started_at is None and token_result is not None:
                started_at = token_result.get("started_at")

            input_tokens, output_tokens, cache_creation, cache_read = _extract_tokens(token_result)
            total_cost = self._calculate_cost(
                exec_result, input_tokens, output_tokens, cache_creation, cache_read
            )
            completed_at, duration_ms = _resolve_duration(exec_result, token_result, started_at)

            return self._build_session_cost(
                session_id=session_id,
                exec_result=exec_result,
                token_result=token_result,
                total_cost=total_cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation=cache_creation,
                cache_read=cache_read,
                tool_count=tool_count or 0,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
