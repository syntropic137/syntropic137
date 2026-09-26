"""TimescaleDB aggregation query for contribution heatmap data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from syn_domain.contexts.agent_sessions import (
    CANONICAL_SESSION_USAGE_CTE,
    CANONICAL_USAGE_EVENT_FILTER,
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
    CostCalculator,
    recorded_model_from_row,
)
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    HeatmapDayBucket,
)
from syn_domain.storable_text import pg_safe
from syn_shared.pricing import parse_vendor_cost

# WHAT THIS MODULE COSTS, AND WHY THAT IS THE POINT (#1253)
#
# The heatmap returns one row per day. It used to cost one read per
# agent_events ROW in the window instead - 13.6-14.8s in production, the
# slowest endpoint in the system by ~5x, on the dashboard landing page.
#
# Two things drove that, and both are fixed below:
#
#   1. `scoped_events` joined back to EVERY row of every member session, of
#      every event type, selecting the JSONB `data` blob with them. Three
#      CTEs read it, so PostgreSQL could not inline it and materialised the
#      lot into a work table - tool calls, stream chunks and all - to compute
#      token totals that only ever look at two event types.
#   2. It computed `session_start` from that same unnarrowed join, which is
#      what forced the join to exist at all.
#
#   3. Every "how many distinct X on day D" number was computed by reading
#      every event in the window, because that is what a DISTINCT costs when
#      you ask it of raw rows.
#
# Each query below now reads only rows that can change its own answer: the
# three distinct-counts come from a per-day rollup (see below), and the usage
# join reads only the two event types that carry tokens. Nothing on this path
# grows with telemetry that does not change the output.

# WHERE THE THREE "HOW MANY DISTINCT" NUMBERS COME FROM (#1253)
#
# executions-per-day, commits-per-day and "which sessions started inside the
# window" are all questions about DISTINCT values. No index answers a DISTINCT
# without visiting the rows carrying the values, so asking agent_events costs
# one read per EVENT in the window - a million tool-call rows on executions
# that already appear cost a million reads and change nothing in the output.
# That is what made this endpoint the slowest in the system.
#
# They are asked of agent_event_day_rollup instead: one row per
# (day, session_id, execution_id), maintained by a trigger on agent_events
# (EventStoreSchema._create_day_rollup; migration 005 documents it but is not
# executed). That grain IS the grain of the three answers, so the reads
# are bounded by days x sessions x executions - what the heatmap returns -
# rather than by how much telemetry those sessions happened to emit.
#
# The rollup is NOT a projection: it never reads the event store, so it does
# not replay from position zero and does not stall the projection coordinator
# (#1318). See migration 005 for why it is a trigger and not an application
# hook (insert_batch uses COPY, which no application hook sees).
#
# EQUIVALENCE WITH THE QUERIES THIS REPLACED.
#   - rollup.day is the UTC calendar day of `time` (see the contract below), so
#     `day BETWEEN $1 AND $2` selects exactly the rows `time >= $1 AND
#     time < $2 + 1 day` did, for a caller whose window is UTC days.
#   - a rollup row exists for every (day, session, execution) triple that has
#     an event, and for no other, so COUNT(DISTINCT execution_id) per day is
#     unchanged and so is the set of days that appear at all.
#   - first_time is MIN(time) of the triple, so MIN(first_time) per session is
#     MIN(time) per session.

# THE DAY IS A UTC DAY. THAT IS THE CONTRACT (#1371).
#
# `start` and `end` name UTC calendar days, every `day` returned is a UTC
# calendar day, and an event belongs to the UTC day its `time` falls in. There
# is no per-user or per-server zone anywhere on this path, by design: the
# rollup row is written once, by whichever connection happened to insert the
# event, and can never be re-decided afterwards - so the day it is filed under
# has to be a fact about the instant and nothing else.
#
# That makes the spelling below load-bearing, not stylistic. A timestamptz cast
# with a bare `::date` resolves in the CONNECTION's TimeZone, so `started_at::date`
# would attribute a session to whatever day the READING connection thought it
# was - which for an 01:00Z start under America/Los_Angeles is the day before
# the one the WRITING trigger filed its rollup row under. Sessions would then
# land on a day whose executions and commits came from somewhere else.
#
# `AT TIME ZONE 'UTC'` is therefore the same expression the writer uses, and is
# meant to stay that way: it is `utc_day()` in syn_adapters/events/schema.py,
# and test_day_rollup_utc_day.py fails if the two ever drift apart. They cannot
# share one definition directly - the package dependency runs adapters ->
# domain, not back - so that test is what holds them together.


def _utc_day(timestamp_expr: str) -> str:
    """The UTC calendar day of a `timestamptz` SQL expression.

    Character-for-character `utc_day()` in syn_adapters/events/schema.py, which
    is what writes `agent_event_day_rollup.day`. See the contract above.
    """
    return f"({timestamp_expr} AT TIME ZONE 'UTC')::date"


# A session is counted on the day it STARTED. Membership and start time both
# come from ONE date-bounded read of the rollup, and nothing joins back to the
# session's history.
#
# Filtering rows by time and then taking MIN() would be wrong, not just slow:
# a session beginning before the window would report its first IN-WINDOW
# observation as its start and land on the wrong day. So membership is decided
# first, per session:
#
#     a session started inside the window IFF it has an observation inside
#     the window and none before it.
#
# The NOT EXISTS is an index probe per candidate session on
# idx_rollup_session_day (session_id, day) that stops at the first earlier row.
#
# WHY MIN OVER THE WINDOW IS THE TRUE START HERE, not a fragment of one.
# The anti-join has already established that a member session has no row
# before $1, so every row it owns is >= $1. At least one is <= $2, so the
# smallest of them cannot be one of the rows the upper bound excludes.
# Therefore MIN over the window equals MIN over the session's whole history -
# the same value the original `session_start` computed by reading all of it.
_WINDOW_STARTS = """
window_starts AS (
    SELECT session_id, MIN(first_time) AS started_at
    FROM agent_event_day_rollup
    WHERE day >= $1::date
      AND day <= $2::date
      {execution_filter}
    GROUP BY session_id
),
session_start AS (
    SELECT w.session_id, w.started_at
    FROM window_starts w
    WHERE NOT EXISTS (
        SELECT 1
        FROM agent_event_day_rollup r
        WHERE r.session_id = w.session_id
          AND r.day < $1::date
          {execution_filter}
    )
)
"""

_EXECUTION_FILTER = "AND execution_id = ANY($3)"

# Executions are NOT re-attributed to a start day the way sessions and usage
# are. An execution that spans days genuinely did work on each of them, and
# showing that is the point of the heatmap. The rollup keeps that: it has a row
# per (day, execution), so an execution still appears on every day it emitted.
_EXECUTIONS_QUERY = """
SELECT
    day,
    COUNT(DISTINCT execution_id) AS executions
FROM agent_event_day_rollup
WHERE day >= $1::date
  AND day <= $2::date
  {execution_filter}
GROUP BY day
ORDER BY day
"""

# Commits, on the day each one happened.
#
# HAVING keeps the old result shape exactly: the previous statement selected
# git_commit rows, so a day with events but no commits produced NO row. Rollup
# rows exist for every day with any event, so without the HAVING this would
# start emitting commits=0 rows the caller never used to see.
_COMMITS_QUERY = """
SELECT
    day,
    SUM(commits)::bigint AS commits
FROM agent_event_day_rollup
WHERE day >= $1::date
  AND day <= $2::date
  {execution_filter}
GROUP BY day
HAVING SUM(commits) > 0
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
WITH {_WINDOW_STARTS}
SELECT {_utc_day("started_at")} AS day, COUNT(*) AS sessions
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
#
# `scoped_events` deliberately carries a member session's usage rows WHATEVER
# their timestamps, including ones after the window ends. Narrowing them by
# time would hand the canonical CTE a FRAGMENT of a session: a run beginning
# inside the window whose summary arrives after it would be priced from its
# placeholder turn rows, reporting 5 output tokens for a session that produced
# 13,300. That is the bug this whole module exists to prevent, reappearing at
# the window edge.
#
# It is narrowed by EVENT TYPE, which is a different thing and safe: those are
# the only rows canonical usage reads, and the start day it is bucketed by
# comes from `session_start` above, which saw every event type.
_USAGE_QUERY = f"""
WITH {_WINDOW_STARTS},
scoped_events AS (
    -- The execution filter is applied AGAIN here, not just when choosing
    -- sessions. Joining back on session_id alone assumes session ids are
    -- globally unique, and no constraint enforces that: a retried or resumed
    -- session id reused across executions would drag an unselected
    -- execution's rows into a filtered heatmap.
    SELECT a.session_id, a.event_type, a.data, a.time
    FROM agent_events a
    JOIN session_start w ON w.session_id = a.session_id
    WHERE {CANONICAL_USAGE_EVENT_FILTER}
      {{execution_filter}}
),
{CANONICAL_SESSION_USAGE_CTE}
SELECT
    {_utc_day("s.started_at")} AS day,
    u.model AS model,
    u.{REQUESTED_MODEL_COLUMN} AS {REQUESTED_MODEL_COLUMN},
    u.{HAS_REQUESTED_MODEL_COLUMN} AS {HAS_REQUESTED_MODEL_COLUMN},
    SUM(u.vendor_cost_usd) AS vendor_cost_usd,
    SUM(u.input_tokens) AS input_tokens,
    SUM(u.output_tokens) AS output_tokens,
    SUM(u.cache_creation_tokens) AS cache_creation_tokens,
    SUM(u.cache_read_tokens) AS cache_read_tokens
FROM canonical_usage u
JOIN session_start s ON s.session_id = u.session_id
GROUP BY day, u.model, u.{REQUESTED_MODEL_COLUMN}, u.{HAS_REQUESTED_MODEL_COLUMN},
    (u.vendor_cost_usd IS NULL)
ORDER BY day
"""


def _count_by_day(rows: list[asyncpg.Record], column: str) -> dict[str, int]:
    """Index one count-per-day result by ISO day string."""
    return {row["day"].isoformat(): int(row[column]) for row in rows}


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
        """Run one of the three templates, scoped to ``execution_ids`` if given.

        The one place this class binds an id, so the one place it has to be
        spelled the way agent_events holds it: AgentEvent's validator applies
        pg_safe on the way in, and a filter carrying a codepoint that stripped
        matches no row and reports that as an empty heatmap (#1241).
        """
        sql = self._render(template, execution_ids is not None)
        if execution_ids is not None:
            return await conn.fetch(sql, start, end, [pg_safe(eid) for eid in execution_ids])
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
            vendor_cost = parse_vendor_cost(row.get("vendor_cost_usd"))
            if vendor_cost is not None:
                day_cost.priced_cost += vendor_cost
                continue

            # Priced as what ran when reported, else as what was requested
            # (ADR-067) - the rate a legacy alias row was always priced at.
            model = recorded_model_from_row(row).pricing_model
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
        executions: int,
        commits: int,
        day_tokens: _DayTokens,
        day_cost: _DayCost,
    ) -> dict[str, float]:
        """Build one day's breakdown from its activity, tokens and priced cost."""
        return {
            "sessions": float(sessions),
            "executions": float(executions),
            "commits": float(commits),
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
            execution_rows = await self._fetch(conn, _EXECUTIONS_QUERY, start, end, execution_ids)
            commit_rows = await self._fetch(conn, _COMMITS_QUERY, start, end, execution_ids)
            session_rows = await self._fetch(conn, _SESSIONS_QUERY, start, end, execution_ids)
            usage_rows = await self._fetch(conn, _USAGE_QUERY, start, end, execution_ids)

        cost_by_day, tokens_by_day = self._price_by_day_and_model(usage_rows)
        executions_by_day = _count_by_day(execution_rows, "executions")
        commits_by_day = _count_by_day(commit_rows, "commits")
        sessions_by_day = _count_by_day(session_rows, "sessions")

        # Zero-fill all days in the range
        buckets: list[HeatmapDayBucket] = []
        current = start
        while current <= end:
            day_str = current.isoformat()
            has_data = (
                day_str in executions_by_day
                or day_str in commits_by_day
                or day_str in sessions_by_day
                or day_str in tokens_by_day
            )
            breakdown = (
                self._build_day_breakdown(
                    sessions_by_day.get(day_str, 0),
                    executions_by_day.get(day_str, 0),
                    commits_by_day.get(day_str, 0),
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
