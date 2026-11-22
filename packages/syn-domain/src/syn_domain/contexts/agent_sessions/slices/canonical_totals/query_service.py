"""All-time usage totals read from the one canonical source (issue #932).

The dashboard's metric card and its activity heatmap answered the same
question from different lanes - the card from Lane 1 ``SessionCompleted``
domain events, the heatmap from Lane 2 observations - and so quoted
9,151,116 tokens beside 10,002,629 for the same reality. This service gives
the card the SAME numbers the heatmap reads, so the two agree by
construction rather than by coincidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.agent_sessions.canonical_usage import PricingResolver

from syn_domain import agent_event_span
from syn_domain.contexts.agent_sessions.canonical_usage import (
    CANONICAL_MODEL_COLUMNS,
    price_canonical_row,
    rollup_usage_sources,
)
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
    ModelRow,
    recorded_model_group_by,
    recorded_model_select,
    zero_usage_group_by,
)
from syn_domain.storable_text import pg_safe
from syn_shared.events import TOKEN_USAGE
from syn_shared.pricing import canonical_cost_usd

# All-time totals are read from the usage rollup, never from agent_events.
#
# Read from agent_events they were a scan of every usage row ever recorded:
# the hypertable is compressed and segmented by session_id, and nothing here
# names a session, so every compressed chunk was decompressed and every JSONB
# blob parsed, on every dashboard load (1.9s live, 3.0s with a workflow
# filter). The rollup holds one row per summary and one per (session, model)
# of turns, so this grows with sessions, not with telemetry. The decision
# between summary and turns is still CANONICAL_USAGE_DECISION_CTE's - the one
# the heatmap applies - so the card and the heatmap agree by construction.
_EXECUTION_FILTER = "execution_id = ANY($1)"

# Grouped by model AND cost-nullness for the same reason every other canonical
# query is: a group mixing priced and unpriced rows prices some of its tokens
# and not others, and reports the shortfall as though it were cheap (#788).
#
# The last two columns are what an UNPRICED group's observation count is made
# of (#897), read from the same rows as its money. A summary that won its
# session is one observation. A session with no summary contributes its turns,
# and the rollup's ``observations`` counts zero-token turns too - a priced zero
# at any rate (#890) - so those sessions are counted here, and named by
# ``_UNPRICED_TURN_DAYS_QUERY`` only when the group turns out to be
# unpriced. Naming them here shipped every summary-less session of every
# rate-priced group on every poll, to be thrown away (#2341).
_TOTALS_QUERY = """
WITH {sources}
SELECT
    {model_columns},
    SUM(vendor_cost_usd) AS vendor_cost_usd,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(cache_creation_tokens) AS cache_creation_tokens,
    SUM(cache_read_tokens) AS cache_read_tokens,
    COUNT(*) FILTER (
        WHERE session_id IN (SELECT session_id FROM priced_summary)
    ) AS summary_observations,
    COUNT(*) FILTER (
        WHERE session_id NOT IN (SELECT session_id FROM priced_summary)
    ) AS turn_session_count
FROM canonical_usage
GROUP BY {model_columns}, (vendor_cost_usd IS NULL)
"""

# The summary-less sessions of the groups pricing found unpriced, and of no
# other group, by the UTC days they have telemetry on. Whether a model has a
# rate is decided in Python, so the groups are bound by their three model
# columns, after the execution filter's $1 when there is one. NOT DISTINCT,
# because a missing model is the commonest unpriced group and NULL = NULL
# matches nothing. A session the day rollup has never seen comes back under a
# NULL day, which reads it unbounded, as agent_event_span does.
_UNPRICED_TURN_DAYS_QUERY = f"""
WITH {{sources}},
unpriced_sessions AS (
    SELECT DISTINCT canonical_usage.session_id
    FROM canonical_usage
    JOIN unnest({{keys}}) AS unpriced({CANONICAL_MODEL_COLUMNS})
      ON canonical_usage.model IS NOT DISTINCT FROM unpriced.model
     AND canonical_usage.{REQUESTED_MODEL_COLUMN} IS NOT DISTINCT FROM unpriced.{REQUESTED_MODEL_COLUMN}
     AND canonical_usage.{HAS_REQUESTED_MODEL_COLUMN} = unpriced.{HAS_REQUESTED_MODEL_COLUMN}
    WHERE canonical_usage.vendor_cost_usd IS NULL
      AND canonical_usage.session_id NOT IN (SELECT session_id FROM priced_summary)
)
SELECT day_rollup.day, ARRAY_AGG(DISTINCT unpriced_sessions.session_id) AS sessions
FROM unpriced_sessions
LEFT JOIN agent_event_day_rollup AS day_rollup USING (session_id)
GROUP BY day_rollup.day
"""

# The turns of the sessions above that reported tokens, per model. Read from
# agent_events because the rollup cannot tell a zero-token turn from any other.
#
# One branch per UTC day, each naming that day's sessions - session_id is the
# hypertable's segment key - and that day's bounds as constants, so each
# branch plans and opens one chunk. Measured at #2341's scale (2,000 unpriced
# sessions over 91 daily chunks): ONE statement naming every session over the
# whole span spent ~700ms PLANNING, estimating the 2,000-id array against each
# chunk's statistics, then seq-scanned every chunk; the per-day branches do
# work proportional to the sessions, not sessions x chunks. It runs only when
# some turn-priced work has no rate, which priced history never has.
_UNPRICED_TURNS_DAY = f"""
    SELECT data
    FROM agent_events
    WHERE event_type = '{TOKEN_USAGE}'
      AND session_id = ANY($1)
      AND time >= $2 AND time < $3
      AND NOT {zero_usage_group_by()}
      AND {{where}}"""

_UNPRICED_TURNS_QUERY = f"""
SELECT
    {recorded_model_select()},
    COUNT(*) AS observations
FROM ({{days}}
) AS turns
GROUP BY {recorded_model_group_by()}
"""

# Each branch's own $1-$3, renumbered to its place in the statement.
_PARAMETER = re.compile(r"\$(\d+)")

# The execution filter, bound after every day's three parameters.
_UNPRICED_TURNS_EXECUTION_FILTER = "execution_id = ANY(${position})"

type _ModelKey = tuple[object, object, bool]
"""A row's three model columns, as the canonical query groups on them."""


def _model_key(row: ModelRow) -> _ModelKey:
    return (
        row.get("model"),
        row.get(REQUESTED_MODEL_COLUMN),
        bool(row.get(HAS_REQUESTED_MODEL_COLUMN)),
    )


# Counts every session the canonical source knows about, including ones that
# produced no tokens. `canonical_usage` only carries sessions with usage rows,
# so a session that failed before the agent ran would be missed by counting
# there - which is exactly how two different session counts arose.
#
# Asked of agent_event_day_rollup, which has a row for every (day, session,
# execution) that emitted ANY event - the same population a COUNT(DISTINCT)
# over agent_events saw, at one row per session-day instead of one per event.
_SESSION_COUNT_QUERY = """
SELECT COUNT(DISTINCT session_id) AS sessions
FROM agent_event_day_rollup
WHERE {where}
"""


@dataclass(frozen=True)
class CanonicalTotals:
    """Every token and dollar the canonical source knows about."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    unpriced_tokens: int = 0
    unpriced_observation_count: int = 0
    """Observations behind ``unpriced_tokens``: the work ``cost_usd`` could not
    price, counted from the same rows. Non-zero means the cost is a lower bound,
    not that the work was free (#890, #897)."""
    sessions: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of the four buckets. Safe because they are disjoint."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


class CanonicalUsageQueryService:
    """Reads system-wide totals from the canonical usage definition."""

    def __init__(self, pool: asyncpg.Pool, cost_calculator: PricingResolver) -> None:
        """Takes the resolver rather than importing one.

        CostCalculator lives in the session_cost slice; importing it here
        would be a cross-slice dependency, which VSA forbids. The composition
        root supplies it.
        """
        self._pool = pool
        self._cost_calculator = cost_calculator

    @staticmethod
    def _render(template: str, filtered: bool, **fields: str) -> str:
        where = _EXECUTION_FILTER if filtered else "TRUE"
        return template.format(
            sources=rollup_usage_sources(where),
            model_columns=CANONICAL_MODEL_COLUMNS,
            where=where,
            **fields,
        )

    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        """Canonical totals, optionally narrowed to a set of executions.

        agent_events holds every id in its stored (sanitised) form, because
        AgentEvent's validator applies pg_safe on the way in. A read binds text
        against those columns, so it has to ask for the same spelling or it
        matches nothing and reports that as "nothing was recorded" (#1241).
        The usage rollup copies its ids from those rows, so the same holds.
        """
        filtered = execution_ids is not None
        totals_sql = self._render(_TOTALS_QUERY, filtered)
        sessions_sql = self._render(_SESSION_COUNT_QUERY, filtered)
        args = [[pg_safe(eid) for eid in execution_ids]] if execution_ids is not None else []

        # One snapshot for both reads (#983), so the tokens and the session
        # count describe the same moment: two autocommit statements could
        # report a new session's tokens without the session, or the reverse.
        async with self._pool.acquire() as conn, agent_event_span.custom_plans(conn):  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
            rows = await conn.fetch(totals_sql, *args)
            session_row = await conn.fetchrow(sessions_sql, *args)

            input_tokens = output_tokens = cache_creation = cache_read = 0
            unpriced = unpriced_observations = 0
            cost = Decimal("0")
            unpriced_turn_models: set[_ModelKey] = set()
            for row in rows:
                input_tokens += int(row["input_tokens"])
                output_tokens += int(row["output_tokens"])
                cache_creation += int(row["cache_creation_tokens"])
                cache_read += int(row["cache_read_tokens"])
                row_cost = price_canonical_row(row, self._cost_calculator)
                cost += row_cost.cost
                unpriced += row_cost.unpriced_tokens
                if row_cost.unpriced_tokens:
                    unpriced_observations += int(row["summary_observations"] or 0)
                    if row["turn_session_count"]:
                        unpriced_turn_models.add(_model_key(row))
            unpriced_observations += await self._unpriced_turns(
                conn,  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
                unpriced_turn_models,
                filtered,
                args,
            )

        return CanonicalTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            # A Decimal sum keeps its operands' exponent; report the canonical form.
            cost_usd=canonical_cost_usd(cost),
            unpriced_tokens=unpriced,
            unpriced_observation_count=unpriced_observations,
            sessions=int(session_row["sessions"]) if session_row else 0,
        )

    @classmethod
    async def _unpriced_turns(
        cls,
        conn: agent_event_span.SpanConnection,
        models: set[_ModelKey],
        filtered: bool,
        args: list[list[str]],
    ) -> int:
        """Turns that reported tokens, on these unpriced models, in their sessions.

        The sessions are every summary-less session of an unpriced group, so a
        session can also carry turns on a model that WAS priced; those are
        dropped by model here rather than counted as unpriced.
        """
        if not models:
            return 0
        keys = sorted(models, key=repr)
        first = len(args) + 1
        days_sql = cls._render(
            _UNPRICED_TURN_DAYS_QUERY,
            filtered,
            keys=f"${first}::text[], ${first + 1}::text[], ${first + 2}::boolean[]",
        )
        day_rows = await conn.fetch(
            days_sql,
            *args,
            [key[0] for key in keys],
            [key[1] for key in keys],
            [key[2] for key in keys],
        )
        if not day_rows:
            return 0
        days = sorted(day_rows, key=lambda row: str(row["day"]))
        where = (
            _UNPRICED_TURNS_EXECUTION_FILTER.format(position=3 * len(days) + 1)
            if filtered
            else "TRUE"
        )
        branches: list[str] = []
        params: list[object] = []
        for n, row in enumerate(days):
            day = row["day"]
            span = (
                agent_event_span.EventSpan.of_days(day, day)
                if isinstance(day, date)
                else agent_event_span.EventSpan.unbounded()
            )
            branches.append(
                _PARAMETER.sub(
                    lambda m, n=n: f"${int(m.group(1)) + 3 * n}", _UNPRICED_TURNS_DAY
                ).format(where=where)
            )
            params += [sorted(str(s) for s in row["sessions"]), span.lower, span.upper]  # type: ignore[union-attr]  # an ARRAY_AGG column
        rows = await conn.fetch(
            _UNPRICED_TURNS_QUERY.format(days="\n    UNION ALL".join(branches)),
            *params,
            *args,
        )
        return sum(
            int(row["observations"])  # type: ignore[arg-type]  # a COUNT(*) column
            for row in rows
            if _model_key(row) in models  # type: ignore[arg-type]  # asyncpg Record reads by name
        )
