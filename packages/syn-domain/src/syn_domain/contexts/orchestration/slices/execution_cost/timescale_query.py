"""TimescaleDB direct query for execution cost calculation.

Queries the agent_events table to aggregate token usage and costs
across all sessions belonging to an execution. This bypasses the
(always-empty) projection store and reads from the actual source of
truth for observability data (Lane 2).

Pattern follows TimescaleSessionCostQuery from the session_cost slice.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# Prefer session_summary rows (authoritative totals from Claude CLI).
# Aggregates across all sessions in the execution.
_SESSION_SUMMARY_QUERY = """
SELECT
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
WHERE execution_id = $1 AND event_type = $2
"""

# Fallback: aggregate from individual token_usage events when no
# session_summary is available (e.g. mid-execution queries).
_TOKEN_USAGE_FALLBACK_QUERY = """
SELECT
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

_TOOL_COUNT_QUERY = """
SELECT COUNT(*)
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

_TURN_COUNT_QUERY = """
SELECT COUNT(*)
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

# Per-phase cost breakdown from session_summary events
_COST_BY_PHASE_QUERY = """
SELECT
    phase_id,
    SUM((data->>'total_cost_usd')::numeric) as phase_cost
FROM agent_events
WHERE execution_id = $1
  AND event_type = $2
  AND phase_id IS NOT NULL
GROUP BY phase_id
"""

# Per-model cost breakdown from session_summary events
_COST_BY_MODEL_QUERY = """
SELECT
    data->>'model' as model,
    SUM((data->>'total_cost_usd')::numeric) as model_cost
FROM agent_events
WHERE execution_id = $1
  AND event_type = $2
  AND data->>'model' IS NOT NULL
GROUP BY data->>'model'
"""


class TimescaleExecutionCostQuery:
    """Calculates execution cost directly from TimescaleDB observations.

    Aggregates across all sessions belonging to an execution,
    producing an ExecutionCost read model.
    """

    def __init__(self, pool: Any, cost_calculator: CostCalculator | None = None) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def calculate(self, execution_id: str) -> ExecutionCost | None:
        """Calculate execution cost from TimescaleDB.

        Prefers session_summary events (authoritative). Falls back to
        token_usage aggregation for in-progress executions.

        Returns:
            ExecutionCost with aggregated metrics, or None if no data found.
        """
        async with self._pool.acquire() as conn:
            # Try session_summary first (authoritative totals)
            summary_row = await conn.fetchrow(
                _SESSION_SUMMARY_QUERY, execution_id, SESSION_SUMMARY
            )

            has_summary = summary_row is not None and summary_row["total_input"] is not None

            if has_summary:
                token_row = summary_row
            else:
                # Fall back to token_usage aggregation
                token_row = await conn.fetchrow(
                    _TOKEN_USAGE_FALLBACK_QUERY, execution_id, TOKEN_USAGE
                )

            if token_row is None or token_row["total_input"] is None:
                return None

            # Extract token counts
            input_tokens = token_row["total_input"] or 0
            output_tokens = token_row["total_output"] or 0
            cache_creation = token_row.get("cache_creation") or 0
            cache_read = token_row.get("cache_read") or 0

            # Calculate cost
            if has_summary and summary_row["sdk_cost"] is not None:
                total_cost = Decimal(str(summary_row["sdk_cost"]))
            else:
                total_cost = self._cost_calculator.calculate_token_cost(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation=cache_creation,
                    cache_read=cache_read,
                )

            # Tool count
            tool_count = await conn.fetchval(
                _TOOL_COUNT_QUERY, execution_id, TOOL_EXECUTION_COMPLETED
            )

            # Turn count (from token_usage events, each = one turn)
            turn_count: int
            if has_summary:
                turn_count = int(summary_row.get("total_turns") or 0)
            else:
                turn_count = await conn.fetchval(
                    _TURN_COUNT_QUERY, execution_id, TOKEN_USAGE
                ) or 0

            # Session info
            session_ids: list[str] = list(token_row.get("session_ids") or [])
            session_count: int = token_row.get("session_count") or 0

            # Duration
            duration_ms: float = 0
            if has_summary:
                duration_ms = float(summary_row.get("duration_ms_val") or 0)
            else:
                started_at = token_row.get("started_at")
                last_obs = token_row.get("last_observation")
                if started_at and last_obs:
                    duration_ms = (last_obs - started_at).total_seconds() * 1000

            # Timestamps
            started_at = token_row.get("started_at")
            completed_at = (
                summary_row.get("completed_at")
                if has_summary
                else token_row.get("last_observation")
            )

            # Per-phase breakdown
            cost_by_phase: dict[str, Decimal] = {}
            if has_summary:
                phase_rows = await conn.fetch(
                    _COST_BY_PHASE_QUERY, execution_id, SESSION_SUMMARY
                )
                for row in phase_rows:
                    if row["phase_id"] and row["phase_cost"] is not None:
                        cost_by_phase[row["phase_id"]] = Decimal(str(row["phase_cost"]))

            # Per-model breakdown
            cost_by_model: dict[str, Decimal] = {}
            if has_summary:
                model_rows = await conn.fetch(
                    _COST_BY_MODEL_QUERY, execution_id, SESSION_SUMMARY
                )
                for row in model_rows:
                    if row["model"] and row["model_cost"] is not None:
                        cost_by_model[row["model"]] = Decimal(str(row["model_cost"]))

            return ExecutionCost(
                execution_id=execution_id,
                session_count=session_count,
                session_ids=session_ids,
                total_cost_usd=total_cost,
                token_cost_usd=total_cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
                tool_calls=tool_count or 0,
                turns=turn_count,
                duration_ms=duration_ms,
                cost_by_phase=cost_by_phase,
                cost_by_model=cost_by_model,
                started_at=started_at,
                completed_at=completed_at,
            )
