"""TimescaleDB aggregation query for contribution heatmap data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    HeatmapDayBucket,
)
from syn_shared.events import GIT_COMMIT, TOKEN_USAGE

# SQL fragment shared between filtered and unfiltered queries.
# Metrics are derived from the actual event types in agent_events:
#   sessions   — distinct session_id values active that day
#   executions — distinct execution_id values active that day
#   commits    — count of GIT_COMMIT events
#   tokens     — broken down by input, output, cache_creation, cache_read
#
# Event type literals come from the shared syn_shared.events constants
# rather than being repeated as magic strings.
_METRIC_COLUMNS = f"""
    COUNT(DISTINCT session_id) AS sessions,
    COUNT(DISTINCT execution_id) AS executions,
    COUNT(*) FILTER (WHERE event_type = '{GIT_COMMIT}') AS commits,
    COALESCE(SUM(COALESCE((data->>'input_tokens')::bigint, 0))
        FILTER (WHERE event_type = '{TOKEN_USAGE}'), 0) AS input_tokens,
    COALESCE(SUM(COALESCE((data->>'output_tokens')::bigint, 0))
        FILTER (WHERE event_type = '{TOKEN_USAGE}'), 0) AS output_tokens,
    COALESCE(SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0))
        FILTER (WHERE event_type = '{TOKEN_USAGE}'), 0) AS cache_creation_tokens,
    COALESCE(SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0))
        FILTER (WHERE event_type = '{TOKEN_USAGE}'), 0) AS cache_read_tokens
"""

# Per-day, per-model token totals. A day's activity can span many sessions
# on many different models, so cost must be priced per model group rather
# than summing all tokens for the day and pricing them as a single model
# (the same class of bug fixed in issue #788 for session/execution cost).
_MODEL_TOKEN_COLUMNS = """
    time_bucket('1 day', time)::date AS day,
    data->>'model' AS model,
    COALESCE(SUM((data->>'input_tokens')::bigint), 0) AS input_tokens,
    COALESCE(SUM((data->>'output_tokens')::bigint), 0) AS output_tokens,
    COALESCE(SUM((data->>'cache_creation_tokens')::bigint), 0) AS cache_creation_tokens,
    COALESCE(SUM((data->>'cache_read_tokens')::bigint), 0) AS cache_read_tokens
"""


@dataclass
class _DayCost:
    """A day's cost, priced per model group.

    ``unpriced_tokens`` counts tokens from model groups that could not be
    priced (unknown/missing model) - these never contribute to
    ``priced_cost``, they are surfaced separately instead of guessed at
    (issue #788).
    """

    priced_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    unpriced_tokens: int = 0


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
    "unpriced_tokens": 0.0,
}


class TimescaleHeatmapQuery:
    """Queries agent_events with time_bucket aggregation for heatmap data."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._cost_calculator = CostCalculator()

    def _price_by_day_and_model(self, model_rows: list[asyncpg.Record]) -> dict[str, _DayCost]:
        """Price token_usage rows grouped by (day, model) into per-day costs.

        Each row is one model's token totals for one day. A group whose
        model is unknown/missing contributes zero cost and its tokens are
        counted in ``unpriced_tokens`` instead of being priced as a
        guessed/default model.
        """
        cost_by_day: dict[str, _DayCost] = {}
        for row in model_rows:
            day_str = row["day"].isoformat()
            day_cost = cost_by_day.setdefault(day_str, _DayCost())

            input_tokens = int(row["input_tokens"])
            output_tokens = int(row["output_tokens"])
            cache_creation = int(row["cache_creation_tokens"])
            cache_read = int(row["cache_read_tokens"])

            raw_model = row.get("model")
            model = raw_model if isinstance(raw_model, str) else None
            pricing = self._cost_calculator.resolve_pricing(model)
            if pricing is None:
                day_cost.unpriced_tokens += (
                    input_tokens + output_tokens + cache_creation + cache_read
                )
                continue
            day_cost.priced_cost += pricing.calculate_cost(
                input_tokens, output_tokens, cache_creation, cache_read
            )
        return cost_by_day

    async def _fetch_rows(
        self,
        conn: asyncpg.pool.PoolConnectionProxy,
        start: date,
        end: date,
        execution_ids: set[str] | None,
    ) -> list[asyncpg.Record]:
        """Fetch per-day metric rows (sessions/executions/commits/tokens)."""
        if execution_ids is not None:
            return await conn.fetch(
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
        return await conn.fetch(
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

    async def _fetch_model_rows(
        self,
        conn: asyncpg.pool.PoolConnectionProxy,
        start: date,
        end: date,
        execution_ids: set[str] | None,
    ) -> list[asyncpg.Record]:
        """Fetch per-day, per-model token rows for pricing (see ``_MODEL_TOKEN_COLUMNS``)."""
        if execution_ids is not None:
            return await conn.fetch(
                f"""
                SELECT
                    {_MODEL_TOKEN_COLUMNS}
                FROM agent_events
                WHERE event_type = '{TOKEN_USAGE}'
                  AND time >= $1::date
                  AND time < ($2::date + interval '1 day')
                  AND execution_id = ANY($3)
                GROUP BY day, model
                """,
                start,
                end,
                list(execution_ids),
            )
        return await conn.fetch(
            f"""
            SELECT
                {_MODEL_TOKEN_COLUMNS}
            FROM agent_events
            WHERE event_type = '{TOKEN_USAGE}'
              AND time >= $1::date
              AND time < ($2::date + interval '1 day')
            GROUP BY day, model
            """,
            start,
            end,
        )

    @staticmethod
    def _build_day_breakdown(row: asyncpg.Record, day_cost: _DayCost) -> dict[str, float]:
        """Build one day's breakdown dict from a metric row and its priced cost."""
        input_tokens = int(row["input_tokens"])
        output_tokens = int(row["output_tokens"])
        cache_creation = int(row["cache_creation_tokens"])
        cache_read = int(row["cache_read_tokens"])
        total_tokens = input_tokens + output_tokens + cache_creation + cache_read
        return {
            "sessions": float(row["sessions"]),
            "executions": float(row["executions"]),
            "commits": float(row["commits"]),
            "cost_usd": float(day_cost.priced_cost.quantize(Decimal("0.0001"))),
            "tokens": float(total_tokens),
            "input_tokens": float(input_tokens),
            "output_tokens": float(output_tokens),
            "cache_creation_tokens": float(cache_creation),
            "cache_read_tokens": float(cache_read),
            "unpriced_tokens": float(day_cost.unpriced_tokens),
        }

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
            rows = await self._fetch_rows(conn, start, end, execution_ids)
            model_rows = await self._fetch_model_rows(conn, start, end, execution_ids)

        cost_by_day = self._price_by_day_and_model(model_rows)

        # Build lookup from query results
        day_data: dict[str, dict[str, float]] = {}
        for row in rows:
            day_str = row["day"].isoformat()
            day_cost = cost_by_day.get(day_str, _DayCost())
            day_data[day_str] = self._build_day_breakdown(row, day_cost)

        # Zero-fill all days in the range
        buckets: list[HeatmapDayBucket] = []
        current = start
        while current <= end:
            day_str = current.isoformat()
            breakdown = day_data.get(day_str, dict(_EMPTY_BREAKDOWN))
            buckets.append(
                HeatmapDayBucket(
                    date=day_str,
                    count=0.0,  # Set by handler based on selected metric
                    breakdown=breakdown,
                )
            )
            current += timedelta(days=1)

        return buckets
