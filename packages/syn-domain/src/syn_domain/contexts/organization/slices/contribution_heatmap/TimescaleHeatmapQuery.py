"""TimescaleDB aggregation query for contribution heatmap data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from syn_domain.contexts.agent_sessions import CANONICAL_SESSION_USAGE_CTE, CostCalculator
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    HeatmapDayBucket,
)
from syn_shared.events import GIT_COMMIT

# Every observation belonging to a session that STARTED inside the window -
# not every observation that landed inside it.
#
# Filtering rows by time first would hand the canonical CTE a FRAGMENT of a
# session: a run beginning inside the window whose summary arrives after it
# would be priced from its placeholder turn rows, reporting 5 output tokens
# for a session that produced 13,300. That is the bug this whole module
# exists to prevent, reappearing at the window edge. It also made MIN(time)
# the first in-window observation rather than the true start, so a session
# beginning before the window was attributed to the wrong day.
#
# So membership is decided per SESSION, then all of that session's rows are
# loaded regardless of their own timestamps.
_SCOPED_EVENTS = """
session_bounds AS (
    SELECT session_id, MIN(time) AS started_at
    FROM agent_events
    WHERE TRUE {execution_filter}
    GROUP BY session_id
),
sessions_in_window AS (
    SELECT session_id
    FROM session_bounds
    WHERE started_at >= $1::date
      AND started_at < ($2::date + interval '1 day')
),
scoped_events AS (
    -- The execution filter is applied AGAIN here, not just when choosing
    -- sessions. Joining back on session_id alone assumes session ids are
    -- globally unique, and no constraint enforces that: a retried or resumed
    -- session id reused across executions would drag an unselected
    -- execution's rows into a filtered heatmap.
    SELECT a.session_id, a.execution_id, a.event_type, a.data, a.time
    FROM agent_events a
    JOIN sessions_in_window w ON w.session_id = a.session_id
    WHERE TRUE {execution_filter}
)
"""

# Activity markers keep EVENT-time scoping: a commit happens at an instant and
# belongs on that day, whoever's session it was.
_ACTIVITY_SCOPE = """
scoped_events AS (
    SELECT session_id, execution_id, event_type, data, time
    FROM agent_events
    WHERE time >= $1::date
      AND time < ($2::date + interval '1 day')
      {execution_filter}
)
"""

_EXECUTION_FILTER = "AND execution_id = ANY($3)"

# Activity markers, bucketed by the time they actually happened.
#
# Unlike token usage (see canonical_usage), these are NOT re-attributed to a
# session's start day. A commit happens at an instant, and an execution that
# spans days genuinely did work on each of them - showing that is the point
# of the heatmap. Only usage, which has one authoritative record per session,
# collapses onto a single square.
_ACTIVITY_QUERY = f"""
WITH {_ACTIVITY_SCOPE}
SELECT
    time_bucket('1 day', time)::date AS day,
    COUNT(DISTINCT execution_id) AS executions,
    COUNT(*) FILTER (WHERE event_type = '{GIT_COMMIT}') AS commits
FROM scoped_events
GROUP BY day
ORDER BY day
"""

# One session, one square: counted on the day it started rather than on every
# day it emitted an observation. Summing COUNT(DISTINCT session_id) per day
# double-counted any session that crossed midnight.
#
# Counted from session_start, which covers EVERY observed session - including
# one that produced no tokens because it failed during setup. Counting from
# canonical_usage instead would drop those, reintroducing the split between
# this number and the metric card's.
_SESSIONS_QUERY = f"""
WITH {_SCOPED_EVENTS},
{CANONICAL_SESSION_USAGE_CTE}
SELECT started_at::date AS day, COUNT(*) AS sessions
FROM session_start
GROUP BY day
ORDER BY day
"""

# Canonical per-(day, model) token totals, priced per model group.
#
# Grouped by model because a day spans many sessions on many models, and
# pricing a day's mixed tokens at one model's rate is the #788 bug. Grouped
# by START day because that is where the session's single authoritative
# record belongs (see canonical_usage).
_USAGE_QUERY = f"""
WITH {_SCOPED_EVENTS},
{CANONICAL_SESSION_USAGE_CTE}
SELECT
    s.started_at::date AS day,
    u.model AS model,
    SUM(u.vendor_cost_usd) AS vendor_cost_usd,
    SUM(u.input_tokens) AS input_tokens,
    SUM(u.output_tokens) AS output_tokens,
    SUM(u.cache_creation_tokens) AS cache_creation_tokens,
    SUM(u.cache_read_tokens) AS cache_read_tokens
FROM canonical_usage u
JOIN session_start s ON s.session_id = u.session_id
GROUP BY day, u.model, (u.vendor_cost_usd IS NULL)
ORDER BY day
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


@dataclass
class _DayTokens:
    """A day's canonical token totals, summed across every model group."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


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

    @staticmethod
    def _render(template: str, filtered: bool) -> str:
        """Bind the optional execution filter into a query template."""
        return template.format(execution_filter=_EXECUTION_FILTER if filtered else "")

    async def _fetch(
        self,
        conn: asyncpg.pool.PoolConnectionProxy,
        template: str,
        start: date,
        end: date,
        execution_ids: set[str] | None,
    ) -> list[asyncpg.Record]:
        sql = self._render(template, execution_ids is not None)
        if execution_ids is not None:
            return await conn.fetch(sql, start, end, list(execution_ids))
        return await conn.fetch(sql, start, end)

    def _price_by_day_and_model(
        self, usage_rows: list[asyncpg.Record]
    ) -> tuple[dict[str, _DayCost], dict[str, _DayTokens]]:
        """Price canonical usage rows into per-day cost and per-day token totals.

        Each row is one model's canonical token totals for one day. A group
        whose model is unknown/missing contributes zero cost and its tokens
        are counted in ``unpriced_tokens`` instead of being priced as a
        guessed/default model.
        """
        cost_by_day: dict[str, _DayCost] = {}
        tokens_by_day: dict[str, _DayTokens] = {}
        for row in usage_rows:
            day_str = row["day"].isoformat()
            day_cost = cost_by_day.setdefault(day_str, _DayCost())
            day_tokens = tokens_by_day.setdefault(day_str, _DayTokens())

            input_tokens = int(row["input_tokens"])
            output_tokens = int(row["output_tokens"])
            cache_creation = int(row["cache_creation_tokens"])
            cache_read = int(row["cache_read_tokens"])

            day_tokens.input_tokens += input_tokens
            day_tokens.output_tokens += output_tokens
            day_tokens.cache_creation_tokens += cache_creation
            day_tokens.cache_read_tokens += cache_read

            # The harness's own number wins when it gave one. Recomputing it
            # would discard billing truth in favour of our pricing table -
            # which drifts: this session's vendor cost is $0.09440 and the
            # table reprices it at $0.0921.
            vendor_cost = row.get("vendor_cost_usd")
            if vendor_cost is not None:
                day_cost.priced_cost += Decimal(str(vendor_cost))
                continue

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
        return cost_by_day, tokens_by_day

    @staticmethod
    def _build_day_breakdown(
        sessions: int,
        activity: asyncpg.Record | None,
        day_tokens: _DayTokens,
        day_cost: _DayCost,
    ) -> dict[str, float]:
        """Build one day's breakdown from its activity, tokens and priced cost."""
        return {
            "sessions": float(sessions),
            "executions": float(activity["executions"]) if activity else 0.0,
            "commits": float(activity["commits"]) if activity else 0.0,
            "cost_usd": float(day_cost.priced_cost.quantize(Decimal("0.0001"))),
            "tokens": float(day_tokens.total),
            "input_tokens": float(day_tokens.input_tokens),
            "output_tokens": float(day_tokens.output_tokens),
            "cache_creation_tokens": float(day_tokens.cache_creation_tokens),
            "cache_read_tokens": float(day_tokens.cache_read_tokens),
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
            activity_rows = await self._fetch(conn, _ACTIVITY_QUERY, start, end, execution_ids)
            session_rows = await self._fetch(conn, _SESSIONS_QUERY, start, end, execution_ids)
            usage_rows = await self._fetch(conn, _USAGE_QUERY, start, end, execution_ids)

        cost_by_day, tokens_by_day = self._price_by_day_and_model(usage_rows)
        activity_by_day = {row["day"].isoformat(): row for row in activity_rows}
        sessions_by_day = {row["day"].isoformat(): int(row["sessions"]) for row in session_rows}

        # Zero-fill all days in the range
        buckets: list[HeatmapDayBucket] = []
        current = start
        while current <= end:
            day_str = current.isoformat()
            has_data = (
                day_str in activity_by_day or day_str in sessions_by_day or day_str in tokens_by_day
            )
            breakdown = (
                self._build_day_breakdown(
                    sessions_by_day.get(day_str, 0),
                    activity_by_day.get(day_str),
                    tokens_by_day.get(day_str, _DayTokens()),
                    cost_by_day.get(day_str, _DayCost()),
                )
                if has_data
                else dict(_EMPTY_BREAKDOWN)
            )
            buckets.append(
                HeatmapDayBucket(
                    date=day_str,
                    count=0.0,  # Set by handler based on selected metric
                    breakdown=breakdown,
                )
            )
            current += timedelta(days=1)

        return buckets
