"""TimescaleDB fallback query for session cost calculation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import asyncpg
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_shared.events import (
    SESSION_STARTED,
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

logger = logging.getLogger(__name__)

# There is one query per input shape and no single-session variant of any of
# them: ``calculate`` is ``calculate_many`` for a list of one. Keeping a
# separate set of per-session queries is how the two answers drift, and the
# drift is silent - the list view and the detail view quietly disagree about
# the same session's cost. Every query is scoped with
# ``session_id = ANY($1::text[])`` so one page of a list endpoint costs a FIXED
# number of round trips instead of up to four per session (issue #1077; #1087
# fixed the same defect on the execution side).

# The newest ``session_summary`` per session. ``DISTINCT ON (session_id)`` with
# ``ORDER BY session_id, time DESC`` is what makes it "newest, one per session"
# - a session that reported twice must still resolve to exactly one cost.
_SESSION_SUMMARIES_QUERY = """
SELECT DISTINCT ON (session_id)
    session_id,
    (data->>'total_input_tokens')::int as total_input,
    (data->>'total_output_tokens')::int as total_output,
    (data->>'cache_creation_tokens')::int as cache_creation,
    (data->>'cache_read_tokens')::int as cache_read,
    (data->>'total_cost_usd')::numeric as sdk_cost,
    (data->>'duration_ms')::bigint as duration_ms_val,
    data->>'model' as agent_model,
    time as completed_at,
    execution_id,
    phase_id
FROM agent_events
WHERE session_id = ANY($1::text[]) AND event_type = $2
ORDER BY session_id, time DESC
"""

# Fallback for sessions with no usable summary: aggregate their raw token_usage
# events.
#
# GROUPED BY MODEL. A session is one agent, but not one model: a Claude session
# delegating to a Haiku subagent emits token_usage rows for both, and an agent
# that reports no model on some observations emits rows with a NULL model beside
# priced ones (issue #788 haiku attribution). Summing every observation into one
# row and taking MAX(data->>'model') priced the whole session at that single
# model, and both outcomes were wrong: pick the priced model and unknown tokens
# get billed at a real rate while unpriced_observation_count reports 0; pick the
# NULL and the entire session goes unpriced including work we could price.
#
# Grouping by model lets each group be priced with its own rate and lets
# COUNT(*) be summed for unpriced groups ONLY - mirroring
# execution_cost/timescale_query.py, which already had to solve this.
#
# ``execution_id`` and ``phase_id`` stay in the GROUP BY beside ``session_id``:
# they were there before this query was scoped by id list, and collapsing to
# (session, model) would merge groups the pricing code counts separately.
_TOKEN_USAGE_FALLBACK_BY_SESSIONS_QUERY = """
SELECT
    session_id,
    data->>'model' as agent_model,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    MAX(data->>'workspace_id') as workspace_id,
    COUNT(*) as observation_count,
    execution_id,
    phase_id
FROM agent_events
WHERE session_id = ANY($1::text[]) AND event_type = $2
GROUP BY session_id, execution_id, phase_id, data->>'model'
"""

_COUNTS_BY_SESSION_QUERY = """
SELECT session_id, COUNT(*) as cnt
FROM agent_events
WHERE session_id = ANY($1::text[]) AND event_type = $2
GROUP BY session_id
"""

_MIN_TIMES_BY_SESSION_QUERY = """
SELECT session_id, MIN(time) as started_at
FROM agent_events
WHERE session_id = ANY($1::text[]) AND event_type = $2
GROUP BY session_id
"""


def _extract_tokens(token_result: asyncpg.Record) -> tuple[int, int, int, int]:
    """Extract token counts from a DB result row."""
    return (
        token_result["total_input"] or 0,
        token_result["total_output"] or 0,
        token_result.get("cache_creation") or 0,
        token_result.get("cache_read") or 0,
    )


@dataclass
class _GroupTokens:
    """Token counts for one model group."""

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation + self.cache_read


@dataclass
class PricedSessionTotals:
    """One session's token totals, priced per model group.

    ``total_cost`` covers the PRICED groups only. ``unpriced_observation_count``
    says how many observations are missing from it. Reporting both is the whole
    point: a session that mixes a priced model with an unpriced one has a real
    cost that is also a lower bound, and neither number alone conveys that.
    """

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    total_cost: Decimal
    cost_by_model: dict[str, Decimal]
    unpriced_observation_count: int
    primary_model: str | None
    started_at: datetime | None
    last_observation: datetime | None
    workspace_id: str | None
    execution_id: str | None
    phase_id: str | None


def _row_sdk_cost(row: asyncpg.Record) -> Decimal | None:
    """The harness-reported cost for a row, when it has one."""
    raw = row.get("sdk_cost")
    return None if raw is None else Decimal(str(raw))


def _pick_primary_model(token_totals_by_model: dict[str, int]) -> str | None:
    """The model that did most of the work in this session.

    ``SessionCost.agent_model`` is a single field but a session can span models,
    so one has to be chosen. Most tokens wins, ties broken by name so the answer
    is stable across queries. The previous ``MAX(data->>'model')`` picked
    whichever id sorted last, which is arbitrary and, worse, was ALSO used to
    price the whole session.
    """
    if not token_totals_by_model:
        return None
    return max(token_totals_by_model.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _min_time(current: datetime | None, candidate: datetime | None) -> datetime | None:
    """Earliest of two optional timestamps."""
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _max_time(current: datetime | None, candidate: datetime | None) -> datetime | None:
    """Latest of two optional timestamps."""
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


@dataclass
class _SessionAccumulator:
    """Running totals while merging one session's model-grouped rows."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    total_cost: Decimal = Decimal("0")
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    tokens_by_model: dict[str, int] = field(default_factory=dict)
    unpriced_observation_count: int = 0
    started_at: datetime | None = None
    last_observation: datetime | None = None
    workspace_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    rows_seen: int = 0

    def add_tokens(self, row: asyncpg.Record, model: str | None) -> _GroupTokens:
        """Fold one group's tokens and metadata in; returns that group's tokens."""
        group = _GroupTokens(*_extract_tokens(row))
        self.input_tokens += group.input_tokens
        self.output_tokens += group.output_tokens
        self.cache_creation += group.cache_creation
        self.cache_read += group.cache_read
        self.started_at = _min_time(self.started_at, row.get("started_at"))
        self.last_observation = _max_time(self.last_observation, row.get("last_observation"))
        self.workspace_id = self.workspace_id or row.get("workspace_id")
        self.execution_id = self.execution_id or row.get("execution_id")
        self.phase_id = self.phase_id or row.get("phase_id")
        if model:
            self.tokens_by_model[model] = self.tokens_by_model.get(model, 0) + group.total
        self.rows_seen += 1
        return group

    def add_cost(self, model: str | None, cost: Decimal) -> None:
        """Record a priced group's contribution to the total and the breakdown."""
        self.total_cost += cost
        if model:
            self.cost_by_model[model] = self.cost_by_model.get(model, Decimal("0")) + cost

    def to_totals(self) -> PricedSessionTotals:
        return PricedSessionTotals(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_creation=self.cache_creation,
            cache_read=self.cache_read,
            total_cost=self.total_cost,
            cost_by_model=self.cost_by_model,
            unpriced_observation_count=self.unpriced_observation_count,
            primary_model=_pick_primary_model(self.tokens_by_model),
            started_at=self.started_at,
            last_observation=self.last_observation,
            workspace_id=self.workspace_id,
            execution_id=self.execution_id,
            phase_id=self.phase_id,
        )


def _price_one_group(
    row: asyncpg.Record,
    group: _GroupTokens,
    model: str | None,
    cost_calculator: CostCalculator,
    session_id: str,
) -> Decimal | None:
    """Price one model group, or ``None`` when no rate could be found.

    A harness-reported ``sdk_cost`` is authoritative and used verbatim,
    matching ``_price_session_summary_row`` on the execution side.
    """
    sdk_cost = _row_sdk_cost(row)
    if sdk_cost is not None:
        return sdk_cost
    priced = cost_calculator.calculate_token_cost(
        input_tokens=group.input_tokens,
        output_tokens=group.output_tokens,
        cache_creation=group.cache_creation,
        cache_read=group.cache_read,
        model=model,
        context=f"session_id={session_id}",
    )
    return priced.cost


def price_session_rows(
    rows: Sequence[asyncpg.Record],
    cost_calculator: CostCalculator,
    session_id: str,
) -> PricedSessionTotals | None:
    """Merge model-grouped rows for one session into one priced total.

    Every group is priced with ITS OWN model - never flattened into a single
    SUM and priced as one model (issue #788), and never reported as a bare zero
    when no rate exists (issue #890). A group whose model is unknown or unrated
    contributes its tokens to the totals and its ``COUNT(*)`` to
    ``unpriced_observation_count``, but nothing to ``total_cost``.

    Returns ``None`` when there is nothing to report, so callers keep their
    existing "no cost data" behaviour.
    """
    acc = _SessionAccumulator()
    for row in rows:
        if row["total_input"] is None and row.get("total_output") is None:
            continue
        model = row.get("agent_model")
        group = acc.add_tokens(row, model)
        cost = _price_one_group(row, group, model, cost_calculator, session_id)
        if cost is None:
            acc.unpriced_observation_count += _row_observation_count(row)
            continue
        acc.add_cost(model, cost)

    if acc.rows_seen == 0:
        return None
    return acc.to_totals()


def _row_observation_count(row: asyncpg.Record) -> int:
    """How many raw ``agent_events`` rows this aggregated group stands for.

    The token_usage queries project ``COUNT(*) AS observation_count`` so an
    unpriced group reports how much real work went unpriced rather than a flat
    1. The session_summary path has no such column (it is a single finalized
    row), so it falls back to 1 - still non-zero, and non-zero is what makes a
    client render "unpriced" instead of "$0.00".
    """
    return int(row.get("observation_count") or 1)


def _resolve_duration(
    exec_result: asyncpg.Record | None,
    totals: PricedSessionTotals,
    started_at: datetime | None,
) -> tuple[datetime | None, int | None]:
    """Resolve completed_at and duration_ms from available data."""
    completed_at = exec_result["completed_at"] if exec_result else totals.last_observation
    duration_ms_val = exec_result.get("duration_ms_val") if exec_result else None

    if duration_ms_val is not None:
        return completed_at, int(duration_ms_val)
    if started_at and completed_at:
        return completed_at, int((completed_at - started_at).total_seconds() * 1000)
    return completed_at, None


class TimescaleSessionCostQuery:
    """Calculates session cost directly from TimescaleDB observations."""

    def __init__(self, pool: asyncpg.Pool, cost_calculator: CostCalculator | None = None) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    @staticmethod
    def _build_session_cost(
        session_id: str,
        totals: PricedSessionTotals,
        tool_count: int,
        started_at: datetime | None,
        completed_at: datetime | None,
        duration_ms: int | None,
    ) -> SessionCost:
        """Assemble a SessionCost from priced, model-grouped totals.

        An unpriced group still reports zero dollars - the read model's
        ``total_cost_usd`` is a ``Decimal`` and every consumer sums it - but
        ``unpriced_observation_count`` ships alongside, so the zero is labelled
        rather than asserted (issue #890). ``cost_by_model`` carries only the
        groups that were actually priced; an entry there claims that model cost
        that much.
        """
        sc = SessionCost(session_id=session_id)
        sc.input_tokens = totals.input_tokens
        sc.output_tokens = totals.output_tokens
        sc.cache_creation_tokens = totals.cache_creation
        sc.cache_read_tokens = totals.cache_read
        sc.tool_calls = tool_count
        sc.token_cost_usd = totals.total_cost
        sc.total_cost_usd = totals.total_cost
        sc.unpriced_observation_count = totals.unpriced_observation_count
        sc.cost_by_model = dict(totals.cost_by_model)
        if totals.primary_model:
            sc.agent_model = totals.primary_model
        sc.started_at = started_at
        sc.execution_id = totals.execution_id
        sc.phase_id = totals.phase_id
        sc.workspace_id = totals.workspace_id
        if completed_at:
            sc.completed_at = completed_at
        if duration_ms is not None:
            sc.duration_ms = duration_ms
        return sc

    def _assemble(
        self,
        session_id: str,
        summary: asyncpg.Record | None,
        token_rows: Sequence[asyncpg.Record],
        tool_count: int,
        session_started_at: datetime | None,
    ) -> SessionCost | None:
        """Price and assemble one session, or ``None`` when it has no cost data.

        Both input shapes run through ``price_session_rows``. The summary is a
        single authoritative row for one model, so it is passed as a one-row
        list rather than given its own pricing branch - one pricing rule, two
        callers, which is what keeps the two answers reconcilable.

        Failures are contained to the one session deliberately. Before this was
        batched every session had its own query and so its own error boundary;
        one session with, say, an unparseable ``total_cost_usd`` cost only its
        own enrichment. A batch answers for a whole page, so without this the
        same bad row would blank all twenty. Transport failures are NOT caught
        here - if the pool is gone there is no partial answer to salvage, and
        the per-session loop could not have salvaged one either.
        """
        try:
            totals = price_session_rows(
                [summary] if summary is not None else token_rows,
                self._cost_calculator,
                session_id,
            )
            if totals is None:
                return None

            started_at = session_started_at
            if started_at is None:
                started_at = totals.started_at

            completed_at, duration_ms = _resolve_duration(summary, totals, started_at)

            return self._build_session_cost(
                session_id=session_id,
                totals=totals,
                tool_count=tool_count,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.warning(
                "Skipping cost for session %s: its observations could not be priced",
                session_id,
                exc_info=True,
            )
            return None

    async def _fetch_summaries(
        self, conn: asyncpg.pool.PoolConnectionProxy, session_ids: list[str]
    ) -> dict[str, asyncpg.Record]:
        """Newest usable ``session_summary`` row per session.

        A row with no ``total_input`` is dropped rather than returned, which is
        what sends that session down the token_usage path - the same test the
        single-session query applies before it decides which shape to price.
        """
        rows = await conn.fetch(_SESSION_SUMMARIES_QUERY, session_ids, SESSION_SUMMARY)
        return {row["session_id"]: row for row in rows if row["total_input"] is not None}

    async def _fetch_token_usage(
        self, conn: asyncpg.pool.PoolConnectionProxy, session_ids: list[str]
    ) -> dict[str, list[asyncpg.Record]]:
        """Model-grouped ``token_usage`` rows, keyed by session.

        Skipped entirely when every requested session had a usable summary, so
        a fully-summarised page still costs three round trips rather than four
        - the same query count the single-session path spends in that case.
        """
        if not session_ids:
            return {}
        rows = await conn.fetch(_TOKEN_USAGE_FALLBACK_BY_SESSIONS_QUERY, session_ids, TOKEN_USAGE)
        grouped: dict[str, list[asyncpg.Record]] = {}
        for row in rows:
            grouped.setdefault(row["session_id"], []).append(row)
        return grouped

    async def calculate(self, session_id: str) -> SessionCost | None:
        """Calculate session cost from TimescaleDB."""
        return (await self.calculate_many([session_id])).get(session_id)

    async def calculate_many(self, session_ids: Sequence[str]) -> dict[str, SessionCost]:
        """Calculate cost for many sessions, keyed by session id.

        At most four round trips for the whole batch - summary, token_usage
        fallback, tool counts, start times - against up to four *per session*
        when ``calculate`` is called in a loop. That loop is what made
        ``/api/v1/sessions`` cost ~80 sequential queries per page (issue #1077,
        the same defect #1087 fixed on ``/api/v1/executions``).

        ``calculate`` is defined in terms of this method rather than beside it.
        Two implementations of "what a session's cost is" would be free to
        drift, and the drift would be invisible: the list and the detail view
        would simply disagree about the same session. There is one
        implementation, so they cannot.

        Sessions with no cost data are absent from the result, matching
        ``calculate`` returning ``None`` for them.
        """
        ids = list(dict.fromkeys(session_ids))
        if not ids:
            return {}

        async with self._pool.acquire() as conn:
            summaries = await self._fetch_summaries(conn, ids)
            token_rows = await self._fetch_token_usage(
                conn, [sid for sid in ids if sid not in summaries]
            )
            tool_counts = {
                row["session_id"]: row["cnt"]
                for row in await conn.fetch(_COUNTS_BY_SESSION_QUERY, ids, TOOL_EXECUTION_COMPLETED)
            }
            started_at_by_session = {
                row["session_id"]: row["started_at"]
                for row in await conn.fetch(_MIN_TIMES_BY_SESSION_QUERY, ids, SESSION_STARTED)
            }

        costs: dict[str, SessionCost] = {}
        for sid in ids:
            cost = self._assemble(
                sid,
                summary=summaries.get(sid),
                token_rows=token_rows.get(sid, ()),
                tool_count=tool_counts.get(sid, 0),
                session_started_at=started_at_by_session.get(sid),
            )
            if cost is not None:
                costs[sid] = cost
        return costs
