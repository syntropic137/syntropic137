"""Read-only query service for session cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    import asyncpg

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
    price_session_rows,
)
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)
from syn_shared.pricing import PricedAmount, PricingStatus

# List all sessions with cost data from session_summary (authoritative).
_LIST_ALL_FROM_SUMMARY_QUERY = """
SELECT
    session_id,
    (data->>'total_input_tokens')::int as total_input,
    (data->>'total_output_tokens')::int as total_output,
    COALESCE((data->>'cache_creation_tokens')::int, 0) as cache_creation,
    COALESCE((data->>'cache_read_tokens')::int, 0) as cache_read,
    (data->>'total_cost_usd')::numeric as sdk_cost,
    (data->>'duration_ms')::bigint as duration_ms_val,
    data->>'model' as agent_model,
    (data->>'num_turns')::int as num_turns,
    (data->>'tool_count')::int as tool_count,
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
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = """
SELECT
    session_id,
    data->>'model' as agent_model,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    COUNT(*) as observation_count,
    MAX(execution_id) as execution_id,
    MAX(phase_id) as phase_id
FROM agent_events
WHERE event_type = $1
GROUP BY session_id, data->>'model'
"""

_TOOL_COUNT_BY_SESSION_QUERY = """
SELECT session_id, COUNT(*) as cnt
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""

_STARTED_AT_BY_SESSION_QUERY = """
SELECT session_id, MIN(time) as started_at
FROM agent_events
WHERE event_type = $1
GROUP BY session_id
"""


def _observation_count(row: object) -> int:
    """How many raw ``agent_events`` rows an aggregated row stands for.

    The token_usage list query projects ``COUNT(*) AS observation_count``. The
    session_summary query returns one finalized row per session and has no such
    column, so it counts as 1 - non-zero, which is all a client needs to render
    "unpriced" rather than "$0.00".
    """
    try:
        raw = row["observation_count"]  # type: ignore[index]
    except (KeyError, IndexError):
        return 1
    return int(raw or 1)


def _unpriced_count(priced: PricedAmount, row: object) -> int:
    """Observations this row contributes to ``unpriced_observation_count``."""
    if priced.is_priced:
        return 0
    return _observation_count(row)


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
        four queries for the whole set instead of four per session (#1114).
        Sessions with no cost data are absent from the mapping.
        """
        query = TimescaleSessionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate_many(session_ids)

    async def list_all(self, limit: int = 500) -> list[SessionCost]:
        """List cost data for all sessions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for sessions that
        haven't completed yet.

        Args:
            limit: Maximum number of results (pushed down to SQL).
        """
        async with self._pool.acquire() as conn:
            summary_rows = await conn.fetch(_LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY, limit)
            summarized_session_ids = {row["session_id"] for row in summary_rows}  # type: ignore[index]
            token_rows = await conn.fetch(_LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE)
            tool_counts = await self._fetch_tool_counts(conn)
            started_map = await self._fetch_started_map(conn)

            results: list[SessionCost] = []
            for row in summary_rows:
                results.append(self._build_from_summary(row, tool_counts, started_map))

            # token_usage rows are one per (session, model) now, so they must be
            # regrouped per session before pricing - otherwise a two-model
            # session would surface as two SessionCost records.
            rows_by_session: dict[str, list[object]] = {}
            for row in token_rows:
                sid = row["session_id"]  # type: ignore[index]
                if sid in summarized_session_ids:
                    continue
                rows_by_session.setdefault(sid, []).append(row)
            for sid, session_rows in rows_by_session.items():
                built = self._build_from_token_usage(sid, session_rows, tool_counts, started_map)
                if built is not None:
                    results.append(built)
            return results

    async def _fetch_tool_counts(self, conn: object) -> dict[str, int]:
        """Fetch tool call counts per session."""
        rows = await conn.fetch(_TOOL_COUNT_BY_SESSION_QUERY, TOOL_EXECUTION_COMPLETED)  # type: ignore[union-attr]
        return {row["session_id"]: row["cnt"] for row in rows}  # type: ignore[index]

    async def _fetch_started_map(self, conn: object) -> dict[str, object]:
        """Fetch the earliest started_at timestamp per session."""
        rows = await conn.fetch(_STARTED_AT_BY_SESSION_QUERY, SESSION_STARTED)  # type: ignore[union-attr]
        return {row["session_id"]: row["started_at"] for row in rows}  # type: ignore[index]

    def _resolve_cost(self, row: object, model: str | None) -> PricedAmount:
        """Resolve cost from sdk_cost field or calculate from token counts.

        ``model`` comes from the same row (``agent_model``, a single session's
        model - a session is one agent/phase/sandbox, see #788) and is used
        whenever the SDK-reported cost is absent and we must price from raw
        token counts.

        Returns a ``PricedAmount`` rather than a ``Decimal`` so a session whose
        model has no rate reaches the API as "unpriced" instead of as a zero
        that reads identically to free work (issue #890).
        """
        sdk_cost = row["sdk_cost"]  # type: ignore[index]
        if sdk_cost is not None:
            return PricedAmount(
                cost=Decimal(str(sdk_cost)), status=PricingStatus.PRICED, model=model
            )
        return self._cost_calculator.calculate_token_cost(
            input_tokens=row["total_input"] or 0,  # type: ignore[index]
            output_tokens=row["total_output"] or 0,  # type: ignore[index]
            cache_creation=row["cache_creation"] or 0,  # type: ignore[index]
            cache_read=row["cache_read"] or 0,  # type: ignore[index]
            model=model,
            context=f"session_id={row['session_id']}",  # type: ignore[index]
        )

    def _build_from_summary(
        self,
        row: object,
        tool_counts: dict[str, int],
        started_map: dict[str, object],
    ) -> SessionCost:
        """Build a SessionCost from a session_summary row."""
        sid = row["session_id"]  # type: ignore[index]
        agent_model = row["agent_model"]  # type: ignore[index]
        priced = self._resolve_cost(row, agent_model)
        cost = priced.cost if priced.cost is not None else Decimal("0")
        sc = SessionCost(session_id=sid)
        sc.input_tokens = row["total_input"] or 0  # type: ignore[index]
        sc.output_tokens = row["total_output"] or 0  # type: ignore[index]
        sc.cache_creation_tokens = row["cache_creation"] or 0  # type: ignore[index]
        sc.cache_read_tokens = row["cache_read"] or 0  # type: ignore[index]
        sc.total_cost_usd = cost
        sc.token_cost_usd = cost
        sc.tool_calls = tool_counts.get(sid, 0)
        sc.turns = row["num_turns"] or 0  # type: ignore[index]
        sc.duration_ms = float(row["duration_ms_val"] or 0)  # type: ignore[index]
        sc.execution_id = row["execution_id"]  # type: ignore[index]
        sc.phase_id = row["phase_id"]  # type: ignore[index]
        sc.started_at = started_map.get(sid)  # type: ignore[arg-type]
        sc.completed_at = row["completed_at"]  # type: ignore[index]
        sc.is_finalized = True
        sc.unpriced_observation_count = _unpriced_count(priced, row)
        if agent_model:
            sc.agent_model = agent_model
            if priced.is_priced:
                sc.cost_by_model = {agent_model: cost}
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
        sc.started_at = started_map.get(session_id) or totals.started_at  # type: ignore[assignment]
        sc.unpriced_observation_count = totals.unpriced_observation_count
        sc.cost_by_model = dict(totals.cost_by_model)
        if totals.primary_model:
            sc.agent_model = totals.primary_model
        return sc
