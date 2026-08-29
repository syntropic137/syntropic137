"""The one definition of a session's canonical token usage (issue #932).

WHY THIS EXISTS: ``token_usage`` and ``session_summary`` are two records of
the same reality and they do NOT agree. Claude Code's per-assistant-message
``usage.output_tokens`` is a PLACEHOLDER - a real message reporting
``output_tokens: 1`` produced 767, and only the stream's terminating
``result`` event carries authoritative totals. Those land in
``session_summary``; they are never written back into the per-turn rows.

So "which of the two do I trust, and how do I combine them" is a DOMAIN
decision. It was being made independently in four places, with different
answers - ``execution_cost`` and ``session_cost`` preferred the summary,
``contribution_heatmap`` read only ``token_usage`` and priced the
placeholder. That is why one dashboard showed 9.9M tokens / $5.71 beside
9,151,116 / $6.2711 for the same reality.

The rule, stated once:

    A session's usage is its ``session_summary`` when one exists,
    and its summed ``token_usage`` rows otherwise.

The fallback is not a nicety: a session still running has no summary yet,
and dropping it would make in-flight work invisible.

ATTRIBUTION: usage is attributed to the day the session STARTED, not the day
each observation landed. ``session_summary`` fires once, at session end, so
event-time bucketing would place a whole session's tokens on its end day
while the per-turn rows spread the same session across every day it touched.
Neither is what a contribution heatmap means. A session is one unit of work
and belongs on one square, the way a commit does.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import Mapping


CANONICAL_SESSION_USAGE_CTE = f"""
session_start AS (
    SELECT session_id, MIN(time) AS started_at
    FROM scoped_events
    GROUP BY session_id
),
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
        data->>'model' AS model,
        (data->>'total_cost_usd')::numeric AS vendor_cost_usd,
        COALESCE((data->>'total_input_tokens')::bigint, 0) AS input_tokens,
        COALESCE((data->>'total_output_tokens')::bigint, 0) AS output_tokens,
        COALESCE((data->>'cache_creation_tokens')::bigint, 0) AS cache_creation_tokens,
        COALESCE((data->>'cache_read_tokens')::bigint, 0) AS cache_read_tokens
    FROM scoped_events
    WHERE event_type = '{SESSION_SUMMARY}'
),
ranked_summary AS (
    -- Prefer a summary that carries usage, then the most recent. A summary of
    -- all zeroes is an ABSENCE of measurement, not a measurement of none: a
    -- run that produced no result event records the accumulator in the domain
    -- lane and zeroes here, and letting that win reports real work as free.
    SELECT
        session_id, model, vendor_cost_usd,
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
        session_id, model, vendor_cost_usd,
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
        data->>'model' AS model,
        NULL::numeric AS vendor_cost_usd,
        SUM(COALESCE((data->>'input_tokens')::bigint, 0)) AS input_tokens,
        SUM(COALESCE((data->>'output_tokens')::bigint, 0)) AS output_tokens,
        SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0)) AS cache_creation_tokens,
        SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0)) AS cache_read_tokens
    FROM scoped_events
    WHERE event_type = '{TOKEN_USAGE}'
    GROUP BY session_id, data->>'model'
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
"""Per-(session, model) canonical usage.

Expects an enclosing CTE named ``scoped_events`` holding the ``agent_events``
rows already narrowed to the caller's time range and filters. Yields columns:
``session_id, model, vendor_cost_usd, input_tokens, output_tokens,
cache_creation_tokens, cache_read_tokens``, plus a ``session_start`` CTE
mapping each session to its first observation. ``vendor_cost_usd`` is the
harness's OWN reported cost and is NULL whenever it did not report one -
codex never does, and a claude session that ended abnormally may not either.
"""


class Pricing(Protocol):
    """What a resolved model's rate card can do."""

    def calculate_cost(
        self, input_tokens: int, output_tokens: int, cache_creation: int, cache_read: int
    ) -> Decimal: ...


class PricingResolver(Protocol):
    """Resolves a model id to its rate card.

    A PROTOCOL, not the concrete CostCalculator, so a slice can price usage
    without importing another slice - VSA forbids that, and rightly: the
    calculator lives in session_cost and this is not session_cost.
    """

    def resolve_pricing(self, model: str | None) -> Pricing | None: ...


@dataclass(frozen=True)
class RowCost:
    """What one (model, cost-nullness) group of canonical usage costs.

    ``unpriced_tokens`` is non-zero only when the harness reported no cost AND
    the model could not be resolved. Those tokens are surfaced rather than
    priced at a guessed rate (issue #788).
    """

    cost: Decimal
    unpriced_tokens: int


def price_canonical_row(row: Mapping[str, object], calculator: PricingResolver) -> RowCost:
    """Cost one canonical usage row, vendor-reported first.

    THE ONE PLACE this precedence is decided. It was previously re-decided in
    every cost query, which is how the same sessions came to be quoted at
    different dollar amounts on one dashboard.

    The harness's own figure wins when it gave one, because that is the
    billing truth we were handed and our pricing table drifts from it (a real
    haiku session: vendor $0.09440, table $0.0921). Codex never reports a cost
    and a claude session that ended abnormally may not either, so tokens
    remain the fallback - never zero, which would price real work as free.
    """
    vendor_cost = row.get("vendor_cost_usd")
    if vendor_cost is not None:
        return RowCost(Decimal(str(vendor_cost)), 0)

    input_tokens = int(row["input_tokens"])  # type: ignore[arg-type]
    output_tokens = int(row["output_tokens"])  # type: ignore[arg-type]
    cache_creation = int(row["cache_creation_tokens"])  # type: ignore[arg-type]
    cache_read = int(row["cache_read_tokens"])  # type: ignore[arg-type]

    raw_model = row.get("model")
    model = raw_model if isinstance(raw_model, str) else None
    pricing = calculator.resolve_pricing(model)
    if pricing is None:
        return RowCost(Decimal("0"), input_tokens + output_tokens + cache_creation + cache_read)
    return RowCost(
        pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read), 0
    )
