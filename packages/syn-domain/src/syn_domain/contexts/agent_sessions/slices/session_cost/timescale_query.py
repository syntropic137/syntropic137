"""TimescaleDB fallback query for session cost calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator


class TimescaleSessionCostQuery:
    """Calculates session cost directly from TimescaleDB observations."""

    def __init__(self, pool: Any, cost_calculator: CostCalculator | None = None) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def calculate(self, session_id: str) -> SessionCost | None:
        """Calculate session cost from TimescaleDB.

        Args:
            session_id: The session to calculate cost for

        Returns:
            SessionCost with aggregated metrics, or None if no observations found
        """
        async with self._pool.acquire() as conn:
            # First try execution_completed which has reliable totals
            # (SDK only provides token usage in ResultMessage, not per-turn)
            exec_result = await conn.fetchrow(
                """
                SELECT
                    (data->>'input_tokens')::int as total_input,
                    (data->>'output_tokens')::int as total_output,
                    (data->>'tool_call_count')::int as tool_count,
                    (data->>'total_cost_usd')::numeric as sdk_cost,
                    time as completed_at,
                    execution_id,
                    phase_id
                FROM agent_events
                WHERE session_id = $1 AND event_type = 'execution_completed'
                ORDER BY time DESC
                LIMIT 1
                """,
                session_id,
            )

            # Fall back to aggregating token_usage if no execution_completed
            if not exec_result or exec_result["total_input"] is None:
                token_result = await conn.fetchrow(
                    """
                    SELECT
                        SUM((data->>'input_tokens')::int) as total_input,
                        SUM((data->>'output_tokens')::int) as total_output,
                        SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
                        SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
                        MIN(time) as started_at,
                        MAX(time) as last_observation,
                        execution_id,
                        phase_id
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = 'token_usage'
                    GROUP BY execution_id, phase_id
                    """,
                    session_id,
                )
            else:
                # Use execution_completed data
                token_result = exec_result

            if not token_result or token_result["total_input"] is None:
                return None

            # Get tool count - prefer from exec_result if available, else count events
            if exec_result and exec_result.get("tool_count"):
                tool_count = exec_result["tool_count"]
            else:
                tool_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = 'tool_execution_completed'
                    """,
                    session_id,
                )

            # Get started_at from session_started event, or fall back to first token_usage
            started_at = await conn.fetchval(
                """
                SELECT MIN(time)
                FROM agent_events
                WHERE session_id = $1 AND event_type IN ('session_started', 'execution_started')
                """,
                session_id,
            )
            if started_at is None and token_result is not None:
                started_at = token_result.get("started_at")

            # Get token counts
            input_tokens = token_result["total_input"] or 0
            output_tokens = token_result["total_output"] or 0
            # Cache tokens only available from token_usage aggregation
            cache_creation = token_result.get("cache_creation") or 0
            cache_read = token_result.get("cache_read") or 0

            # Prefer SDK-provided cost (includes tool token costs accurately)
            # Fall back to our calculation if SDK cost not available
            sdk_cost = exec_result.get("sdk_cost") if exec_result else None
            if sdk_cost is not None:
                total_cost = Decimal(str(sdk_cost))
            else:
                total_cost = self._cost_calculator.calculate_token_cost(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation=cache_creation,
                    cache_read=cache_read,
                )

            # Build SessionCost
            session_cost = SessionCost(session_id=session_id)
            session_cost.input_tokens = input_tokens
            session_cost.output_tokens = output_tokens
            session_cost.cache_creation_tokens = cache_creation
            session_cost.cache_read_tokens = cache_read
            session_cost.tool_calls = tool_count or 0
            session_cost.token_cost_usd = total_cost
            session_cost.total_cost_usd = total_cost
            session_cost.started_at = started_at
            session_cost.execution_id = token_result.get("execution_id")
            session_cost.phase_id = token_result.get("phase_id")
            session_cost.workspace_id = token_result.get("workspace_id")

            # Compute duration and completed_at from timestamps
            completed_at = (
                exec_result["completed_at"] if exec_result else token_result.get("last_observation")
            )
            if completed_at:
                session_cost.completed_at = completed_at
            if started_at and completed_at:
                session_cost.duration_ms = (completed_at - started_at).total_seconds() * 1000

            return session_cost
