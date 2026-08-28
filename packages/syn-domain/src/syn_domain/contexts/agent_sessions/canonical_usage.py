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

from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

CANONICAL_SESSION_USAGE_CTE = f"""
session_start AS (
    SELECT session_id, MIN(time) AS started_at
    FROM scoped_events
    GROUP BY session_id
),
summary_usage AS (
    -- Grouped on cost-nullness as well as model: two summaries on the SAME
    -- model, one with a vendor cost and one without, would otherwise land in
    -- one group whose SUM() is non-NULL, so the token fallback never fires
    -- while the group's tokens include the unpriced row (issue #788).
    SELECT
        session_id,
        data->>'model' AS model,
        SUM((data->>'total_cost_usd')::numeric) AS vendor_cost_usd,
        SUM(COALESCE((data->>'total_input_tokens')::bigint, 0)) AS input_tokens,
        SUM(COALESCE((data->>'total_output_tokens')::bigint, 0)) AS output_tokens,
        SUM(COALESCE((data->>'cache_creation_tokens')::bigint, 0)) AS cache_creation_tokens,
        SUM(COALESCE((data->>'cache_read_tokens')::bigint, 0)) AS cache_read_tokens
    FROM scoped_events
    WHERE event_type = '{SESSION_SUMMARY}'
    GROUP BY session_id, data->>'model', ((data->>'total_cost_usd') IS NULL)
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
priced_summary AS (
    -- A summary of all zeroes is an ABSENCE of usage, not a measurement of
    -- none, so it must not supersede anything. Seen on live data: a run that
    -- produced no result event records the accumulator in Lane 1 and zeroes
    -- here, because AgentExecutionHandler resolves the aggregate's totals
    -- with a `result_x or accumulated_x` fallback but writes this row from
    -- the RAW result fields. Letting those zeroes win reports real work as
    -- free - the silently-cheap failure this module exists to prevent.
    SELECT * FROM summary_usage
    WHERE input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens > 0
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
