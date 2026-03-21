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
            # ISS-100/217: Query session_summary which carries authoritative CLI totals.
            # Previously queried 'execution_completed' which never existed — always fell
            # through to the token_usage aggregation fallback (double-counting cache tokens).
            exec_result = await conn.fetchrow(
                """
                SELECT
                    (data->>'total_input_tokens')::int as total_input,
                    (data->>'total_output_tokens')::int as total_output,
                    (data->>'cache_creation_tokens')::int as cache_creation,
                    (data->>'cache_read_tokens')::int as cache_read,
                    (data->>'total_cost_usd')::numeric as sdk_cost,
                    (data->>'duration_ms')::bigint as duration_ms_val,
                    data->>'model' as agent_model,
                    data->'model_usage' as model_usage,
                    time as completed_at,
                    execution_id,
                    phase_id
                FROM agent_events
                WHERE session_id = $1 AND event_type = $2
                ORDER BY time DESC
                LIMIT 1
                """,
                session_id,
                SESSION_SUMMARY,
            )

            # Fall back to aggregating token_usage if no session_summary found
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
                        MAX(data->>'workspace_id') as workspace_id,
                        MAX(data->>'model') as agent_model,
                        execution_id,
                        phase_id
                    FROM agent_events
                    WHERE session_id = $1 AND event_type = $2
                    GROUP BY execution_id, phase_id
                    """,
                    session_id,
                    TOKEN_USAGE,
                )
            else:
                # Use session_summary data
                token_result = exec_result

            if not token_result or token_result["total_input"] is None:
                return None

            # Get tool count — session_summary doesn't include it, count events directly
            tool_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM agent_events
                WHERE session_id = $1 AND event_type = $2
                """,
                session_id,
                TOOL_EXECUTION_COMPLETED,
            )

            # ISS-265: Per-model cost breakdown — aggregate token_usage events by model
            # Used as fallback when session_summary.model_usage is absent (orphaned sessions)
            per_model_rows = await conn.fetch(
                """
                SELECT
                    data->>'model' as model,
                    SUM((data->>'input_tokens')::int) as input_tokens,
                    SUM((data->>'output_tokens')::int) as output_tokens,
                    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
                    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read
                FROM agent_events
                WHERE session_id = $1 AND event_type = $2
                  AND data->>'model' IS NOT NULL
                GROUP BY data->>'model'
                """,
                session_id,
                TOKEN_USAGE,
            )

            # Get started_at from session_started event, or fall back to first token_usage
            started_at = await conn.fetchval(
                """
                SELECT MIN(time)
                FROM agent_events
                WHERE session_id = $1 AND event_type = $2
                """,
                session_id,
                SESSION_STARTED,
            )
            if started_at is None and token_result is not None:
                started_at = token_result.get("started_at")

            # Get token counts; session_summary has all four, fallback only has totals
            input_tokens = token_result["total_input"] or 0
            output_tokens = token_result["total_output"] or 0
            cache_creation = token_result.get("cache_creation") or 0
            cache_read = token_result.get("cache_read") or 0

            # Prefer SDK-provided cost (exact per-model pricing from CLI)
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
            # Prefer session_summary model; fall back to most common model in token_usage events
            if exec_result and exec_result["agent_model"]:
                session_cost.agent_model = exec_result["agent_model"]
            elif token_result and token_result.get("agent_model"):
                session_cost.agent_model = token_result["agent_model"]

            # ISS-265: Populate cost_by_model
            # Prefer authoritative model_usage from session_summary (exact SDK cost per model)
            model_usage = exec_result["model_usage"] if exec_result else None
            if model_usage and isinstance(model_usage, dict):
                session_cost.cost_by_model = {
                    model_id: Decimal(str(m.get("costUSD", 0)))
                    for model_id, m in model_usage.items()
                    if isinstance(m, dict)
                }
            elif per_model_rows:
                # Fallback: estimate per-model cost from token_usage aggregation
                session_cost.cost_by_model = {
                    row["model"]: self._cost_calculator.calculate_token_cost(
                        input_tokens=row["input_tokens"] or 0,
                        output_tokens=row["output_tokens"] or 0,
                        cache_creation=row["cache_creation"] or 0,
                        cache_read=row["cache_read"] or 0,
                    )
                    for row in per_model_rows
                    if row["model"]
                }
            session_cost.started_at = started_at
            session_cost.execution_id = token_result.get("execution_id")
            session_cost.phase_id = token_result.get("phase_id")
            session_cost.workspace_id = token_result.get("workspace_id")

            # Duration: prefer CLI-reported value from session_summary, else compute
            completed_at = (
                exec_result["completed_at"] if exec_result else token_result.get("last_observation")
            )
            if completed_at:
                session_cost.completed_at = completed_at
            duration_ms_val = exec_result.get("duration_ms_val") if exec_result else None
            if duration_ms_val is not None:
                session_cost.duration_ms = int(duration_ms_val)
            elif started_at and completed_at:
                session_cost.duration_ms = (completed_at - started_at).total_seconds() * 1000

            return session_cost
