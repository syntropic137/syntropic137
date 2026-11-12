"""Read-only query service for session cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    import asyncpg

    from syn_shared.observed_model import RecordedModel

from syn_domain import agent_event_span, tool_call_counts
from syn_domain.contexts.agent_sessions.canonical_usage import SUMMARY_USAGE_TABLE
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import (
    CostField,
    SessionCost,
)
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    recorded_model_from_row,
    recorded_model_group_by,
    recorded_model_select,
    zero_usage_group_by,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
    price_session_rows,
    turn_cost,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.unreported_cost import (
    TurnCost,
    cost_under_unreported_summary,
)
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
)
from syn_shared.pricing import parse_vendor_cost

# List all sessions with cost data from session_summary (authoritative).
_LIST_ALL_FROM_SUMMARY_QUERY = f"""
SELECT
    session_id,
    (data->>'total_input_tokens')::int as total_input,
    (data->>'total_output_tokens')::int as total_output,
    COALESCE((data->>'cache_creation_tokens')::int, 0) as cache_creation,
    COALESCE((data->>'cache_read_tokens')::int, 0) as cache_read,
    (data->>'total_cost_usd')::numeric as sdk_cost,
    (data->>'duration_ms')::bigint as duration_ms_val,
    {recorded_model_select(model_column="agent_model")},
    (data->>'num_turns')::int as num_turns,
    (data->>'tool_count')::int as tool_count,
    data->>'workspace_id' as workspace_id,
    time as completed_at,
    execution_id,
    phase_id
FROM agent_events
WHERE event_type = $1
ORDER BY time DESC
LIMIT $2
"""

# Fallback: list sessions from token_usage events (for in-progress sessions
# that don't yet have a session_summary).
# GROUPED BY MODEL, not just by session. A session is one agent but not
# necessarily one model: a Claude session delegating to a Haiku subagent emits
# token_usage rows for both, and some observations carry no model at all. The
# previous shape summed the session into one row and took
# ``MAX(data->>'model')``, then priced everything at that one model - so a
# session mixing priced and unpriced work either billed unknown tokens at a
# real rate and reported zero unpriced, or went entirely unpriced. Both make
# ``unpriced_observation_count`` a lie (#788 haiku attribution, #890).
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = f"""
SELECT
    session_id,
    {recorded_model_select(model_column="agent_model")},
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    COUNT(*) as observation_count,
    MAX(data->>'workspace_id') as workspace_id,
    MAX(execution_id) as execution_id,
    MAX(phase_id) as phase_id
FROM agent_events
WHERE event_type = $1
GROUP BY session_id, {recorded_model_group_by()}, {zero_usage_group_by()}
"""

# Rank sessions by the cost their newest summary reports (#2228). Read from the
# usage rollup, never from agent_events: the rollup holds one row per
# session_summary, so this grows with sessions rather than telemetry and no
# compressed chunk is decompressed to rank them. DISTINCT ON keeps the newest
# summary per session, as in timescale_query.py, so a re-reported session ranks
# by its final cost and appears once. Only ids leave the database: pricing stays
# on the one ``get_many`` path, and the LIMIT bounds what is priced however long
# the history is. A summary without a reported cost is not ranked - its cost is
# priced from token rows, which SQL cannot order by.
_TOP_BY_COST_QUERY = f"""
SELECT session_id
FROM (
    SELECT DISTINCT ON (session_id) session_id, vendor_cost_usd
    FROM {SUMMARY_USAGE_TABLE}
    ORDER BY session_id, time DESC
) newest_summary
WHERE vendor_cost_usd IS NOT NULL
ORDER BY vendor_cost_usd DESC, session_id
LIMIT $1
"""

_STARTED_AT_BY_SESSION_QUERY = """
SELECT session_id, MIN(time) as started_at
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""


def _attribute_summary_model(sc: SessionCost, recorded: RecordedModel) -> None:
    """Attribute a summary-built session's tokens the way ``price_session_rows`` would.

    ``agent_model`` is only ever a REPORTED model, so the list path and the
    single-session path agree (ADR-067). A reported cost is filed under
    ``cost_key`` - the reported id or the unknown bucket - by the caller.
    """
    sc.agent_model = recorded.observed
    sc.requested_model = recorded.requested
    tokens = sc.total_tokens
    if recorded.observed:
        sc.tokens_by_model = {recorded.observed: tokens}
    if recorded.requested:
        sc.tokens_by_requested_model = {recorded.requested: tokens}


class SessionCostQueryService:
    """Read-only query service for session cost data.

    Reads exclusively from TimescaleDB (Lane 2: Observability).
    The projection store is NOT used for reads — it serves only
    the write-side event handlers in SessionCostProjection.

    See #532 for the architectural rationale.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        cost_calculator: CostCalculator | None = None,
    ) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def get(self, session_id: str) -> SessionCost | None:
        """Get cost data for a single session.

        Delegates to TimescaleSessionCostQuery which handles the
        session_summary → token_usage fallback logic.
        """
        query = TimescaleSessionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate(session_id)

    async def get_many(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        """Get cost data for many sessions in a fixed number of round-trips.

        Same answers as calling ``get`` per id - it is the same code path - but
        three or four queries per BATCH instead of four per session (#1114).
        Three when every id was answered from session summaries, four when the
        token-usage fallback is needed; and one batch per
        ``MAX_SESSIONS_PER_QUERY`` ids rather than one for the whole set, which
        is what bounds a single acquisition (#1338).
        Sessions with no cost data are absent from the mapping.
        """
        query = TimescaleSessionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate_many(session_ids)

    async def top_by_cost(self, limit: int) -> list[SessionCost]:
        """The ``limit`` most expensive completed sessions, most expensive first.

        Ranked by the cost each session's newest summary reports, across the
        whole history - not just the newest ``list_all`` page - and priced
        through ``get_many``. Sessions still in progress, and summaries that
        report no cost, are not ranked (#2228).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_TOP_BY_COST_QUERY, limit)
        ranked_ids = [row["session_id"] for row in rows]  # type: ignore[index]
        costs = await self.get_many(ranked_ids)
        return [costs[sid] for sid in ranked_ids if sid in costs]

    async def list_all(self, limit: int = 500) -> list[SessionCost]:
        """List cost data for all sessions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for sessions that
        haven't completed yet.

        Args:
            limit: Maximum number of results (pushed down to SQL).
        """
        # One snapshot for all four reads (#983): a session that finished
        # between the summary read and the turn read was reported from its
        # placeholder turn rows instead of its summary.
        async with self._pool.acquire() as conn, agent_event_span.custom_plans(conn):  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
            summary_rows = await conn.fetch(_LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY, limit)
            summarized_session_ids = {row["session_id"] for row in summary_rows}  # type: ignore[index]
            token_rows = await conn.fetch(_LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE)
            # From the tally, not from a COUNT(*) over agent_events (#1322).
            tool_counts = await tool_call_counts.by_session(conn)  # type: ignore[arg-type]  # asyncpg generates PoolConnectionProxy's methods at runtime
            started_map = await self._fetch_started_map(conn)

            # token_usage rows are one per (session, model) now, so they must be
            # regrouped per session before pricing - otherwise a two-model
            # session would surface as two SessionCost records.
            rows_by_session: dict[str, list[object]] = {}
            for row in token_rows:
                rows_by_session.setdefault(row["session_id"], []).append(row)  # type: ignore[index]

            results: list[SessionCost] = []
            for row in summary_rows:
                turn_rows = rows_by_session.get(row["session_id"], [])  # type: ignore[index]
                results.append(self._build_from_summary(row, tool_counts, started_map, turn_rows))

            for sid, session_rows in rows_by_session.items():
                if sid in summarized_session_ids:
                    continue
                built = self._build_from_token_usage(sid, session_rows, tool_counts, started_map)
                if built is not None:
                    results.append(built)
            return results

    async def _fetch_started_map(self, conn: object) -> dict[str, object]:
        """Fetch the earliest started_at timestamp per session."""
        rows = await conn.fetch(_STARTED_AT_BY_SESSION_QUERY, SESSION_STARTED)  # type: ignore[union-attr]
        return {row["session_id"]: row["started_at"] for row in rows}  # type: ignore[index]

    def _build_from_summary(
        self,
        row: object,
        tool_counts: dict[str, int],
        started_map: dict[str, object],
        turn_rows: Sequence[object] = (),
    ) -> SessionCost:
        """Build a SessionCost from a session_summary row.

        ``turn_rows`` are the session's model-grouped token_usage rows. They
        price the session only when the summary reports no cost (#1420).
        """
        sid = row["session_id"]  # type: ignore[index]
        # Classified, not read raw: a legacy summary's `model` is the REQUEST
        # (often an alias), and reporting it as the model that ran is exactly
        # what ADR-067 forbids. Priced as before, keyed by what ran.
        recorded = recorded_model_from_row(cast("asyncpg.Record", row), model_column="agent_model")
        sc = SessionCost(session_id=sid)
        sc.input_tokens = row["total_input"] or 0  # type: ignore[index]
        sc.output_tokens = row["total_output"] or 0  # type: ignore[index]
        sc.cache_creation_tokens = row["cache_creation"] or 0  # type: ignore[index]
        sc.cache_read_tokens = row["cache_read"] or 0  # type: ignore[index]
        sc.tool_calls = tool_counts.get(sid, 0)
        sc.turns = row["num_turns"] or 0  # type: ignore[index]
        sc.record_measured(CostField.TURNS)
        sc.duration_ms = float(row["duration_ms_val"] or 0)  # type: ignore[index]
        sc.execution_id = row["execution_id"]  # type: ignore[index]
        sc.phase_id = row["phase_id"]  # type: ignore[index]
        sc.workspace_id = row["workspace_id"]  # type: ignore[index]
        sc.started_at = started_map.get(sid)  # type: ignore[arg-type]
        sc.completed_at = row["completed_at"]  # type: ignore[index]
        sc.is_finalized = True
        _attribute_summary_model(sc, recorded)
        sdk_cost = parse_vendor_cost(row["sdk_cost"])  # type: ignore[index]
        if sdk_cost is not None:
            cost = TurnCost(total=sdk_cost, cost_by_model={recorded.cost_key: sdk_cost})
        else:
            # The rule the projection and the single-session path apply too.
            turns = price_session_rows(
                cast("Sequence[asyncpg.Record]", turn_rows), self._cost_calculator, sid
            )
            cost = cost_under_unreported_summary(turn_cost(turns), sc.total_tokens)
        sc.total_cost_usd = cost.total
        sc.token_cost_usd = cost.total
        sc.cost_by_model = dict(cost.cost_by_model)
        sc.unpriced_observation_count = cost.unpriced_observation_count
        return sc

    def _build_from_token_usage(
        self,
        session_id: str,
        rows: Sequence[object],
        tool_counts: dict[str, int],
        started_map: dict[str, object],
    ) -> SessionCost | None:
        """Build a SessionCost from this session's model-grouped token_usage rows.

        Delegates to ``price_session_rows`` - the same merge the single-session
        path uses - so a session that mixes a priced model with an unpriced one
        reports the priced cost AND the count of what it could not price,
        instead of pricing everything at one arbitrarily chosen model (#788).
        """
        totals = price_session_rows(
            cast("Sequence[asyncpg.Record]", rows), self._cost_calculator, session_id
        )
        if totals is None:
            return None
        sc = SessionCost(session_id=session_id)
        sc.input_tokens = totals.input_tokens
        sc.output_tokens = totals.output_tokens
        sc.cache_creation_tokens = totals.cache_creation
        sc.cache_read_tokens = totals.cache_read
        sc.total_cost_usd = totals.total_cost
        sc.token_cost_usd = totals.total_cost
        sc.tool_calls = tool_counts.get(session_id, 0)
        sc.execution_id = totals.execution_id
        sc.phase_id = totals.phase_id
        sc.workspace_id = totals.workspace_id
        sc.started_at = started_map.get(session_id) or totals.started_at  # type: ignore[assignment]
        sc.unpriced_observation_count = totals.unpriced_observation_count
        sc.cost_by_model = dict(totals.cost_by_model)
        sc.agent_model = totals.primary_model
        sc.requested_model = totals.requested_model
        sc.tokens_by_model = dict(totals.tokens_by_model)
        sc.tokens_by_requested_model = dict(totals.tokens_by_requested_model)
        return sc
