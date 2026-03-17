"""TimescaleDB aggregation query for contribution heatmap data."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    HeatmapDayBucket,
)

# SQL fragment shared between filtered and unfiltered queries.
# Metrics are derived from the actual event types in agent_events:
#   sessions   — distinct session_id values active that day
#   executions — distinct execution_id values active that day
#   commits    — count of git_commit events
#   tokens     — broken down by input, output, cache_creation, cache_read
_METRIC_COLUMNS = """
    COUNT(DISTINCT session_id) AS sessions,
    COUNT(DISTINCT execution_id) AS executions,
    COUNT(*) FILTER (WHERE event_type = 'git_commit') AS commits,
    COALESCE(SUM(COALESCE((data->>'input_tokens')::bigint, 0))
        FILTER (WHERE event_type = 'token_usage'), 0) AS input_tokens,
    COALESCE(SUM(COALESCE((data->>'output_tokens')::bigint, 0))
        FILTER (WHERE event_type = 'token_usage'), 0) AS output_tokens,
    COALESCE(SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0))
        FILTER (WHERE event_type = 'token_usage'), 0) AS cache_creation_tokens,
    COALESCE(SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0))
        FILTER (WHERE event_type = 'token_usage'), 0) AS cache_read_tokens
"""

_EMPTY_BREAKDOWN: dict[str, float] = {
    "sessions": 0.0,
    "executions": 0.0,
    "commits": 0.0,
    "cost_usd": 0.0,
    "tokens": 0.0,
    "input_tokens": 0.0,
    "output_tokens": 0.0,
    "cache_creation_tokens": 0.0,
    "cache_read_tokens": 0.0,
}


class TimescaleHeatmapQuery:
    """Queries agent_events with time_bucket aggregation for heatmap data."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._cost_calculator = CostCalculator()

    async def query(
        self,
        start: date,
        end: date,
        execution_ids: set[str] | None = None,
    ) -> list[HeatmapDayBucket]:
        """Query daily activity buckets from TimescaleDB.

        Args:
            start: Start date (inclusive).
            end: End date (inclusive).
            execution_ids: Optional set of execution IDs to filter by.
                If None, returns data for all executions.

        Returns:
            List of HeatmapDayBucket, one per day (zero-filled).
        """
        async with self._pool.acquire() as conn:
            if execution_ids is not None:
                rows = await conn.fetch(
                    f"""
                    SELECT
                        time_bucket('1 day', time)::date AS day,
                        {_METRIC_COLUMNS}
                    FROM agent_events
                    WHERE time >= $1::date
                      AND time < ($2::date + interval '1 day')
                      AND execution_id = ANY($3)
                    GROUP BY day
                    ORDER BY day
                    """,
                    start,
                    end,
                    list(execution_ids),
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT
                        time_bucket('1 day', time)::date AS day,
                        {_METRIC_COLUMNS}
                    FROM agent_events
                    WHERE time >= $1::date
                      AND time < ($2::date + interval '1 day')
                    GROUP BY day
                    ORDER BY day
                    """,
                    start,
                    end,
                )

        # Build lookup from query results
        day_data: dict[str, dict[str, float]] = {}
        for row in rows:
            day_str = row["day"].isoformat()
            input_tokens = int(row["input_tokens"])
            output_tokens = int(row["output_tokens"])
            cache_creation = int(row["cache_creation_tokens"])
            cache_read = int(row["cache_read_tokens"])
            total_tokens = input_tokens + output_tokens

            cost = self._cost_calculator.calculate_token_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation=cache_creation,
                cache_read=cache_read,
            )

            day_data[day_str] = {
                "sessions": float(row["sessions"]),
                "executions": float(row["executions"]),
                "commits": float(row["commits"]),
                "cost_usd": float(cost.quantize(Decimal("0.0001"))),
                "tokens": float(total_tokens),
                "input_tokens": float(input_tokens),
                "output_tokens": float(output_tokens),
                "cache_creation_tokens": float(cache_creation),
                "cache_read_tokens": float(cache_read),
            }

        # Zero-fill all days in the range
        buckets: list[HeatmapDayBucket] = []
        current = start
        while current <= end:
            day_str = current.isoformat()
            breakdown = day_data.get(day_str, dict(_EMPTY_BREAKDOWN))
            buckets.append(HeatmapDayBucket(
                date=day_str,
                count=0.0,  # Set by handler based on selected metric
                breakdown=breakdown,
            ))
            current += timedelta(days=1)

        return buckets
