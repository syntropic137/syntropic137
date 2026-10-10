"""/metrics usage totals EXACTLY as they read agent_events before E1 (#1558).

FROZEN. DO NOT EDIT, DO NOT REFACTOR, DO NOT TIDY.

A verbatim copy of

    packages/syn-domain/.../agent_sessions/slices/canonical_totals/query_service.py

as it stood on main at 5eb27ff77, the base #1558 branched from, with the three
canonical_usage constants it imported (CANONICAL_MODEL_COLUMNS,
CANONICAL_USAGE_EVENT_FILTER, CANONICAL_SESSION_USAGE_CTE) inlined below as
rendered at that revision. Importing the live ones would make this file the
NEW behaviour wearing the old name. price_canonical_row is still imported:
E1 did not change it, and it prices rows, it does not choose them.

It exists so test_canonical_totals_rollup_parity.py can run the old read and
the new one against one database and compare every field. The old read IS
the specification; E1 was a change of cost, and a change of cost that changes
an answer is a bug. If this file ever needs to change to keep that test
passing, the change under test altered a RESULT: explain it, do not edit this.

Only the class and the totals dataclass were renamed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.agent_sessions.canonical_usage import PricingResolver

from syn_domain.contexts.agent_sessions.canonical_usage import price_canonical_row
from syn_domain.storable_text import pg_safe
from syn_shared.pricing import canonical_cost_usd

# Frozen renderings of the canonical_usage constants at 5eb27ff77.
CANONICAL_MODEL_COLUMNS = "model, requested_model, has_requested_model"
CANONICAL_USAGE_EVENT_FILTER = "event_type IN ('session_summary', 'token_usage')"
CANONICAL_SESSION_USAGE_CTE = """
summary_rows AS (
    -- One row per summary observation, NOT aggregated. Aggregating first was
    -- the bug: "the summary supersedes the turn rows" means CHOOSE one, and
    -- SUM() over a session carrying two summaries added them, doubling its
    -- tokens and its cost. Grouping by model or cost-nullness made the
    -- duplicates into separate rows, which hid the doubling rather than
    -- preventing it.
    SELECT
        session_id,
        time,
        data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
        (data->>'total_cost_usd')::numeric AS vendor_cost_usd,
        COALESCE((data->>'total_input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((data->>'total_output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
    FROM scoped_events
    WHERE event_type = 'session_summary'
),
ranked_summary AS (
    -- Prefer a summary that carries usage, then the most recent. A summary of
    -- all zeroes is an ABSENCE of measurement, not a measurement of none: a
    -- run that produced no result event records the accumulator in the domain
    -- lane and zeroes here, and letting that win reports real work as free.
    SELECT
        session_id, model, requested_model, has_requested_model, vendor_cost_usd,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        ROW_NUMBER() OVER (
            PARTITION BY session_id
            -- Usable first, then MOST RECENT. Ordering by token magnitude
            -- instead makes a correction that REDUCES a session's totals
            -- unable to ever win: the stale larger row outranks it forever.
            -- Magnitude agrees with recency only when corrections grow.
            --
            -- Exact ties in (usable, time) are resolved arbitrarily, because
            -- agent_events carries no monotonic observation id to break them.
            -- Two summaries written in the same microsecond for one session
            -- is not a shape the writers produce; if that changes, this needs
            -- a durable insertion key rather than a cleverer ORDER BY.
            ORDER BY
                (input_tokens + output_tokens
                 + cache_creation_tokens + cache_read_tokens > 0) DESC,
                time DESC
        ) AS rn
    FROM summary_rows
),
priced_summary AS (
    SELECT
        session_id, model, requested_model, has_requested_model, vendor_cost_usd,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens
    FROM ranked_summary
    WHERE rn = 1
      AND input_tokens + output_tokens
          + cache_creation_tokens + cache_read_tokens > 0
),
turn_usage AS (
    -- No vendor cost exists mid-flight: a session reports its own cost only
    -- in the summary, so these rows are always priced from tokens.
    SELECT
        session_id,
        data->>'model' as model, data->>'requested_model' as requested_model, (data ? 'requested_model') as has_requested_model,
        NULL::numeric AS vendor_cost_usd,
        SUM(COALESCE((data->>'input_tokens')::bigint, 0)) AS input_tokens,
        SUM(COALESCE((data->>'output_tokens')::bigint, 0)) AS output_tokens,
        SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0)) AS cache_creation_tokens,
        SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0)) AS cache_read_tokens
    FROM scoped_events
    WHERE event_type = 'token_usage'
    GROUP BY session_id, data->>'model', data->>'requested_model', (data ? 'requested_model')
),
canonical_usage AS (
    -- The summary SUPERSEDES the per-turn rows for a session; it never adds
    -- to them. Unioning both would report the authoritative output plus the
    -- placeholders it replaces.
    SELECT * FROM priced_summary
    UNION ALL
    SELECT * FROM turn_usage
    WHERE session_id NOT IN (SELECT session_id FROM priced_summary)
)
"""

# Mirrors the heatmap's scoping so both read the same rows for the same
# filter. Callers that pass no filter get all-time totals, which is what the
# dashboard metric card wants.
#
# Narrowed to the two event types canonical usage reads (#1253). Three CTEs
# read `scoped_events`, so PostgreSQL cannot inline it and materialises it
# into a work table; unnarrowed, that work table was every agent_event ever
# recorded, JSONB `data` blob included, to total the two types that carry
# tokens. The session COUNT below is the only thing here that needs the other
# types, and it reads them directly.
_SCOPED_EVENTS = f"""
scoped_events AS (
    SELECT session_id, event_type, data, time
    FROM agent_events
    WHERE {CANONICAL_USAGE_EVENT_FILTER}
      {{execution_filter}}
)
"""

_EXECUTION_FILTER = "AND execution_id = ANY($1)"

# Grouped by model AND cost-nullness for the same reason every other canonical
# query is: a group mixing priced and unpriced rows prices some of its tokens
# and not others, and reports the shortfall as though it were cheap (#788).
_TOTALS_QUERY = f"""
WITH {_SCOPED_EVENTS},
{CANONICAL_SESSION_USAGE_CTE}
SELECT
    {CANONICAL_MODEL_COLUMNS},
    SUM(vendor_cost_usd) AS vendor_cost_usd,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(cache_creation_tokens) AS cache_creation_tokens,
    SUM(cache_read_tokens) AS cache_read_tokens
FROM canonical_usage
GROUP BY {CANONICAL_MODEL_COLUMNS}, (vendor_cost_usd IS NULL)
"""

# Counts every session the canonical source knows about, including ones that
# produced no tokens. `canonical_usage` only carries sessions with usage rows,
# so a session that failed before the agent ran would be missed by counting
# there - which is exactly how two different session counts arose.
_SESSION_COUNT_QUERY = """
SELECT COUNT(DISTINCT session_id) AS sessions
FROM agent_events
WHERE TRUE {execution_filter}
"""


@dataclass(frozen=True)
class LegacyCanonicalTotals:
    """Every token and dollar the canonical source knows about."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    unpriced_tokens: int = 0
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


class LegacyCanonicalUsageQueryService:
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
    def _render(template: str, filtered: bool) -> str:
        return template.format(execution_filter=_EXECUTION_FILTER if filtered else "")

    async def totals(self, execution_ids: set[str] | None = None) -> LegacyCanonicalTotals:
        """Canonical totals, optionally narrowed to a set of executions.

            # agent_events holds every id in its stored (sanitised) form, because
        # AgentEvent's validator applies pg_safe on the way in. A read binds text
        # against those columns, so it has to ask for the same spelling or it
        # matches nothing and reports that as "nothing was recorded" (#1241).
        """
        filtered = execution_ids is not None
        totals_sql = self._render(_TOTALS_QUERY, filtered)
        sessions_sql = self._render(_SESSION_COUNT_QUERY, filtered)
        args = [[pg_safe(eid) for eid in execution_ids]] if execution_ids is not None else []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(totals_sql, *args)
            session_row = await conn.fetchrow(sessions_sql, *args)

        input_tokens = output_tokens = cache_creation = cache_read = 0
        unpriced = 0
        cost = Decimal("0")
        for row in rows:
            input_tokens += int(row["input_tokens"])
            output_tokens += int(row["output_tokens"])
            cache_creation += int(row["cache_creation_tokens"])
            cache_read += int(row["cache_read_tokens"])
            row_cost = price_canonical_row(row, self._cost_calculator)
            cost += row_cost.cost
            unpriced += row_cost.unpriced_tokens

        return LegacyCanonicalTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            # A Decimal sum keeps its operands' exponent; report the canonical form.
            cost_usd=canonical_cost_usd(cost),
            unpriced_tokens=unpriced,
            sessions=int(session_row["sessions"]) if session_row else 0,
        )
