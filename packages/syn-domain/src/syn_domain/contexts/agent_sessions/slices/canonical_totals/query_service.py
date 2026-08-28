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

from syn_domain.contexts.agent_sessions.canonical_usage import (
    CANONICAL_SESSION_USAGE_CTE,
    price_canonical_row,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)

# Mirrors the heatmap's scoping so both read the same rows for the same
# filter. Callers that pass no filter get all-time totals, which is what the
# dashboard metric card wants.
_SCOPED_EVENTS = """
scoped_events AS (
    SELECT session_id, execution_id, event_type, data, time
    FROM agent_events
    {execution_filter}
)
"""

_EXECUTION_FILTER = "WHERE execution_id = ANY($1)"

# Grouped by model AND cost-nullness for the same reason every other canonical
# query is: a group mixing priced and unpriced rows prices some of its tokens
# and not others, and reports the shortfall as though it were cheap (#788).
_TOTALS_QUERY = f"""
WITH {_SCOPED_EVENTS},
{CANONICAL_SESSION_USAGE_CTE}
SELECT
    model,
    SUM(vendor_cost_usd) AS vendor_cost_usd,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(cache_creation_tokens) AS cache_creation_tokens,
    SUM(cache_read_tokens) AS cache_read_tokens
FROM canonical_usage
GROUP BY model, (vendor_cost_usd IS NULL)
"""

# Counts every session the canonical source knows about, including ones that
# produced no tokens. `canonical_usage` only carries sessions with usage rows,
# so a session that failed before the agent ran would be missed by counting
# there - which is exactly how two different session counts arose.
_SESSION_COUNT_QUERY = """
SELECT COUNT(DISTINCT session_id) AS sessions
FROM agent_events
{execution_filter}
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

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._cost_calculator = CostCalculator()

    @staticmethod
    def _render(template: str, filtered: bool) -> str:
        return template.format(execution_filter=_EXECUTION_FILTER if filtered else "")

    async def totals(self, execution_ids: set[str] | None = None) -> CanonicalTotals:
        """Canonical totals, optionally narrowed to a set of executions."""
        filtered = execution_ids is not None
        totals_sql = self._render(_TOTALS_QUERY, filtered)
        sessions_sql = self._render(_SESSION_COUNT_QUERY, filtered)
        args = [list(execution_ids)] if execution_ids is not None else []

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
            cost_usd=cost,
            unpriced_tokens=unpriced,
            sessions=int(session_row["sessions"]) if session_row else 0,
        )
