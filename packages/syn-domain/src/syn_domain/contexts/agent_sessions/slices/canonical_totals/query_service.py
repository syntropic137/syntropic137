"""All-time usage totals read from the one canonical source (issue #932).

The dashboard's metric card and its activity heatmap answered the same
question from different lanes - the card from Lane 1 ``SessionCompleted``
domain events, the heatmap from Lane 2 observations - and so quoted
9,151,116 tokens beside 10,002,629 for the same reality. This service gives
the card the SAME numbers the heatmap reads, so the two agree by
construction rather than by coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.agent_sessions.canonical_usage import PricingResolver

from syn_domain.contexts.agent_sessions.canonical_usage import (
    CANONICAL_MODEL_COLUMNS,
    price_canonical_row,
    rollup_usage_sources,
)
from syn_domain.storable_text import pg_safe
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
_TOTALS_QUERY = """
WITH {sources}
SELECT
    {model_columns},
    SUM(vendor_cost_usd) AS vendor_cost_usd,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(cache_creation_tokens) AS cache_creation_tokens,
    SUM(cache_read_tokens) AS cache_read_tokens
FROM canonical_usage
GROUP BY {model_columns}, (vendor_cost_usd IS NULL)
"""

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
    def _render(template: str, filtered: bool) -> str:
        where = _EXECUTION_FILTER if filtered else "TRUE"
        return template.format(
            sources=rollup_usage_sources(where),
            model_columns=CANONICAL_MODEL_COLUMNS,
            where=where,
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

        return CanonicalTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            # A Decimal sum keeps its operands' exponent; report the canonical form.
            cost_usd=canonical_cost_usd(cost),
            unpriced_tokens=unpriced,
            sessions=int(session_row["sessions"]) if session_row else 0,
        )
