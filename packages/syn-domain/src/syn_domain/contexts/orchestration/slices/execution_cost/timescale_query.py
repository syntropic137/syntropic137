"""TimescaleDB direct query for execution cost calculation.

Queries the agent_events table to aggregate token usage and costs
across all sessions belonging to an execution. This bypasses the
(always-empty) projection store and reads from the actual source of
truth for observability data (Lane 2).

Pattern follows TimescaleSessionCostQuery from the session_cost slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

from syn_domain.contexts.agent_sessions import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# Prefer session_summary rows (authoritative totals from Claude CLI).
# Aggregates across all sessions in the execution.
#
# Grouped by model, same as the token_usage fallback below: an execution
# spanning multiple sessions/phases can span multiple models, and a flat
# SUM(total_cost_usd) across mixed models silently drops any row whose
# cost is NULL (PostgreSQL excludes NULLs from SUM) instead of raising or
# falling back to that row's own token-based price - the same class of
# bug as issue #788, surviving on the completed-execution summary path.
_SESSION_SUMMARY_QUERY = """
SELECT
    data->>'model' as model,
    SUM((data->>'total_input_tokens')::int) as total_input,
    SUM((data->>'total_output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    SUM((data->>'total_cost_usd')::numeric) as sdk_cost,
    SUM(COALESCE((data->>'duration_ms')::bigint, 0)) as duration_ms_val,
    SUM(COALESCE((data->>'num_turns')::int, 0)) as total_turns,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as completed_at,
    COUNT(*) as observation_count
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
GROUP BY data->>'model'
"""

# Fallback: aggregate from individual token_usage events when no
# session_summary is available (e.g. mid-execution queries).
#
# Grouped by model: an execution can span multiple sessions/phases, each
# potentially on a different model (e.g. an Opus planning phase followed
# by a Haiku worker phase). Pricing must happen per model group rather
# than flattening all tokens into one SUM and pricing them as a single
# model - the same class of bug as issue #788.
_TOKEN_USAGE_FALLBACK_QUERY = """
SELECT
    data->>'model' as model,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation,
    COUNT(*) as observation_count
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
GROUP BY data->>'model'
"""

_TOOL_COUNT_QUERY = """
SELECT COUNT(*)
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

_TURN_COUNT_QUERY = """
SELECT COUNT(*)
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

# Per-phase cost breakdown from session_summary events
_COST_BY_PHASE_QUERY = """
SELECT
    phase_id,
    SUM((data->>'total_cost_usd')::numeric) as phase_cost
FROM agent_events
WHERE execution_id = $1
  AND event_type = $2
  AND phase_id IS NOT NULL
GROUP BY phase_id
"""


@dataclass
class _TokenData:
    """Intermediate token aggregation from a DB query row."""

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    session_count: int
    session_ids: list[str]
    started_at: datetime | None
    end_at: datetime | None
    sdk_cost: Decimal | None
    duration_ms_raw: int
    total_turns: int
    from_summary: bool


@dataclass
class _PricedTokenUsage:
    """Result of pricing one or more model-grouped token_usage rows."""

    data: _TokenData
    total_cost: Decimal
    cost_by_model: dict[str, Decimal]
    unpriced_observation_count: int


@dataclass
class GroupedTokenUsage:
    """Aggregated + priced token usage merged from model-grouped rows.

    Shared between ``TimescaleExecutionCostQuery`` (single execution) and
    ``ExecutionCostQueryService`` (list_all) - both need to merge rows that
    are grouped by (execution_id, model) into one priced total per execution.
    """

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    session_ids: list[str]
    started_at: datetime | None
    end_at: datetime | None
    total_cost: Decimal
    cost_by_model: dict[str, Decimal]
    unpriced_observation_count: int


@dataclass
class GroupedSessionSummary:
    """Aggregated + priced session_summary data merged from model-grouped rows.

    Shared between ``TimescaleExecutionCostQuery`` (single execution) and
    ``ExecutionCostQueryService`` (list_all) - both need to merge rows that
    are grouped by (execution_id, model) into one priced total per execution,
    mirroring ``GroupedTokenUsage`` for the token_usage fallback path.
    """

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    session_ids: list[str]
    started_at: datetime | None
    end_at: datetime | None
    total_cost: Decimal
    cost_by_model: dict[str, Decimal]
    unpriced_observation_count: int
    duration_ms_raw: int
    total_turns: int


@dataclass
class _GroupTokens:
    """Token counts extracted from one model-grouped row."""

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int


def _extract_group_tokens(row: asyncpg.Record) -> _GroupTokens:
    """Pull token counts out of one model-grouped row."""
    return _GroupTokens(
        input_tokens=row["total_input"] or 0,
        output_tokens=row["total_output"] or 0,
        cache_creation=row.get("cache_creation") or 0,
        cache_read=row.get("cache_read") or 0,
    )


def _extend_time_range(
    started_at: datetime | None,
    end_at: datetime | None,
    row: asyncpg.Record,
    end_key: str = "last_observation",
) -> tuple[datetime | None, datetime | None]:
    """Widen (started_at, end_at) with a row's own timestamps, if any.

    ``end_key`` names the row's end-of-range column: token_usage rows carry
    it as ``last_observation``, session_summary rows as ``completed_at``.
    """
    group_started_at = row.get("started_at")
    if group_started_at and (started_at is None or group_started_at < started_at):
        started_at = group_started_at
    group_end_at = row.get(end_key)
    if group_end_at and (end_at is None or group_end_at > end_at):
        end_at = group_end_at
    return started_at, end_at


def _resolve_row_model(row: asyncpg.Record) -> str | None:
    """Extract the model for a row, or None if missing/not a string."""
    raw_model = row.get("model")
    return raw_model if isinstance(raw_model, str) else None


def _row_observation_count(row: asyncpg.Record) -> int:
    """Number of underlying agent_events rows a grouped row represents.

    Grouped queries project ``COUNT(*) AS observation_count`` so an unpriced
    group's contribution to ``unpriced_observation_count`` reflects real
    observations, not one count per model group (issue #788 follow-up).
    Falls back to 1 when a row doesn't carry the column (e.g. hand-built
    test fixtures), so a single unpriced group still counts as unpriced.
    """
    return int(row.get("observation_count") or 1)


def price_grouped_token_usage(
    rows: list[asyncpg.Record], cost_calculator: CostCalculator
) -> GroupedTokenUsage:
    """Merge model-grouped token_usage rows into one priced aggregate.

    Each row is one model's token totals (e.g. for one execution). Every
    group is priced with its own model - never flattened into a single SUM
    and priced as one model (issue #788). A group whose model is
    unknown/missing contributes zero cost and counts toward
    ``unpriced_observation_count`` instead of guessing.
    """
    totals = _GroupTokens(0, 0, 0, 0)
    session_ids: set[str] = set()
    started_at: datetime | None = None
    end_at: datetime | None = None
    total_cost = Decimal("0")
    cost_by_model: dict[str, Decimal] = {}
    unpriced_observation_count = 0

    for row in rows:
        group = _extract_group_tokens(row)
        totals = _GroupTokens(
            input_tokens=totals.input_tokens + group.input_tokens,
            output_tokens=totals.output_tokens + group.output_tokens,
            cache_creation=totals.cache_creation + group.cache_creation,
            cache_read=totals.cache_read + group.cache_read,
        )
        session_ids.update(row.get("session_ids") or [])
        started_at, end_at = _extend_time_range(started_at, end_at, row)

        model = _resolve_row_model(row)
        pricing = cost_calculator.resolve_pricing(model)
        if pricing is None or model is None:
            unpriced_observation_count += _row_observation_count(row)
            continue
        group_cost = pricing.calculate_cost(
            group.input_tokens, group.output_tokens, group.cache_creation, group.cache_read
        )
        total_cost += group_cost
        cost_by_model[model] = cost_by_model.get(model, Decimal("0")) + group_cost

    return GroupedTokenUsage(
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_creation=totals.cache_creation,
        cache_read=totals.cache_read,
        session_ids=sorted(session_ids),
        started_at=started_at,
        end_at=end_at,
        total_cost=total_cost,
        cost_by_model=cost_by_model,
        unpriced_observation_count=unpriced_observation_count,
    )


@dataclass
class _RowPricing:
    """Result of pricing one session_summary row.

    ``cost`` is ``None`` when the row is genuinely unpriceable (unknown
    model and no ``sdk_cost``) - in that case ``unpriced_count`` carries how
    many observations that row represents.
    """

    cost: Decimal | None
    model: str | None
    unpriced_count: int


def _price_session_summary_row(
    row: asyncpg.Record, group: _GroupTokens, cost_calculator: CostCalculator
) -> _RowPricing:
    """Price one session_summary row: authoritative ``sdk_cost`` first, else per-model calc.

    ``sdk_cost`` (the CLI-reported ``total_cost_usd``) is used verbatim when
    present. A NULL ``sdk_cost`` is priced from this row's own tokens using
    this row's own model - never silently dropped from the total the way a
    flat ``SUM(total_cost_usd)`` would (PostgreSQL excludes NULL rows from
    SUM) and never priced as if the model were unknown when it is in fact
    known (issue #788).
    """
    model = _resolve_row_model(row)
    raw_sdk_cost = row.get("sdk_cost")
    if raw_sdk_cost is not None:
        return _RowPricing(cost=Decimal(str(raw_sdk_cost)), model=model, unpriced_count=0)

    pricing = cost_calculator.resolve_pricing(model)
    if pricing is None or model is None:
        return _RowPricing(cost=None, model=None, unpriced_count=_row_observation_count(row))

    group_cost = pricing.calculate_cost(
        group.input_tokens, group.output_tokens, group.cache_creation, group.cache_read
    )
    return _RowPricing(cost=group_cost, model=model, unpriced_count=0)


def price_grouped_session_summary(
    rows: list[asyncpg.Record], cost_calculator: CostCalculator
) -> GroupedSessionSummary:
    """Merge model-grouped session_summary rows into one priced aggregate.

    Each row is one model's session_summary totals (e.g. for one execution).
    A group whose model really is unknown/missing and has no ``sdk_cost``
    contributes zero cost and counts toward ``unpriced_observation_count``
    instead of guessing (issue #788). See ``_price_session_summary_row`` for
    the per-row pricing rule.
    """
    totals = _GroupTokens(0, 0, 0, 0)
    session_ids: set[str] = set()
    started_at: datetime | None = None
    end_at: datetime | None = None
    total_cost = Decimal("0")
    cost_by_model: dict[str, Decimal] = {}
    unpriced_observation_count = 0
    duration_ms_raw = 0
    total_turns = 0

    for row in rows:
        group = _extract_group_tokens(row)
        totals = _GroupTokens(
            input_tokens=totals.input_tokens + group.input_tokens,
            output_tokens=totals.output_tokens + group.output_tokens,
            cache_creation=totals.cache_creation + group.cache_creation,
            cache_read=totals.cache_read + group.cache_read,
        )
        session_ids.update(row.get("session_ids") or [])
        started_at, end_at = _extend_time_range(started_at, end_at, row, end_key="completed_at")
        duration_ms_raw += int(row.get("duration_ms_val") or 0)
        total_turns += int(row.get("total_turns") or 0)

        priced = _price_session_summary_row(row, group, cost_calculator)
        if priced.cost is None:
            unpriced_observation_count += priced.unpriced_count
            continue
        total_cost += priced.cost
        if priced.model is not None:
            cost_by_model[priced.model] = (
                cost_by_model.get(priced.model, Decimal("0")) + priced.cost
            )

    return GroupedSessionSummary(
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_creation=totals.cache_creation,
        cache_read=totals.cache_read,
        session_ids=sorted(session_ids),
        started_at=started_at,
        end_at=end_at,
        total_cost=total_cost,
        cost_by_model=cost_by_model,
        unpriced_observation_count=unpriced_observation_count,
        duration_ms_raw=duration_ms_raw,
        total_turns=total_turns,
    )


class TimescaleExecutionCostQuery:
    """Calculates execution cost directly from TimescaleDB observations.

    Aggregates across all sessions belonging to an execution,
    producing an ExecutionCost read model.
    """

    def __init__(self, pool: asyncpg.Pool, cost_calculator: CostCalculator | None = None) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def _query_session_summaries(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> list[asyncpg.Record]:
        """Query session_summary events, grouped by model, for authoritative totals."""
        return await conn.fetch(_SESSION_SUMMARY_QUERY, execution_id, SESSION_SUMMARY)

    async def _query_token_usage(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> list[asyncpg.Record]:
        """Query token_usage events, grouped by model, as fallback for in-progress executions."""
        return await conn.fetch(_TOKEN_USAGE_FALLBACK_QUERY, execution_id, TOKEN_USAGE)

    def _price_session_summary_groups(self, rows: list[asyncpg.Record]) -> _PricedTokenUsage:
        """Merge model-grouped session_summary rows into one priced aggregate.

        Delegates to ``price_grouped_session_summary`` (shared with
        ``ExecutionCostQueryService``) and repackages the result as
        ``_TokenData`` for this class's internal pipeline.
        """
        grouped = price_grouped_session_summary(rows, self._cost_calculator)
        data = _TokenData(
            input_tokens=grouped.input_tokens,
            output_tokens=grouped.output_tokens,
            cache_creation=grouped.cache_creation,
            cache_read=grouped.cache_read,
            session_count=len(grouped.session_ids),
            session_ids=grouped.session_ids,
            started_at=grouped.started_at,
            end_at=grouped.end_at,
            sdk_cost=None,
            duration_ms_raw=grouped.duration_ms_raw,
            total_turns=grouped.total_turns,
            from_summary=True,
        )
        return _PricedTokenUsage(
            data=data,
            total_cost=grouped.total_cost,
            cost_by_model=grouped.cost_by_model,
            unpriced_observation_count=grouped.unpriced_observation_count,
        )

    def _price_token_usage_groups(self, rows: list[asyncpg.Record]) -> _PricedTokenUsage:
        """Merge model-grouped token_usage rows into one priced aggregate.

        Delegates to ``price_grouped_token_usage`` (shared with
        ``ExecutionCostQueryService``) and repackages the result as
        ``_TokenData`` for this class's internal pipeline.
        """
        grouped = price_grouped_token_usage(rows, self._cost_calculator)
        data = _TokenData(
            input_tokens=grouped.input_tokens,
            output_tokens=grouped.output_tokens,
            cache_creation=grouped.cache_creation,
            cache_read=grouped.cache_read,
            session_count=len(grouped.session_ids),
            session_ids=grouped.session_ids,
            started_at=grouped.started_at,
            end_at=grouped.end_at,
            sdk_cost=None,
            duration_ms_raw=0,
            total_turns=0,
            from_summary=False,
        )
        return _PricedTokenUsage(
            data=data,
            total_cost=grouped.total_cost,
            cost_by_model=grouped.cost_by_model,
            unpriced_observation_count=grouped.unpriced_observation_count,
        )

    def _calculate_duration(self, data: _TokenData) -> float:
        """Calculate duration in ms from token data.

        Prefers the explicit duration_ms_raw from session_summary payloads, but
        falls back to computing from timestamps when that field is absent/zero —
        which is the common case because session_summary events rarely carry it.
        """
        if data.duration_ms_raw:
            return float(data.duration_ms_raw)
        if data.started_at and data.end_at:
            return (data.end_at - data.started_at).total_seconds() * 1000
        return 0

    async def _query_turn_count(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str, data: _TokenData
    ) -> int:
        """Get turn count from summary data or token_usage event count."""
        if data.from_summary:
            return data.total_turns
        return await conn.fetchval(_TURN_COUNT_QUERY, execution_id, TOKEN_USAGE) or 0

    async def _query_cost_by_phase(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> dict[str, Decimal]:
        """Query per-phase cost breakdown from session_summary events."""
        phase_rows = await conn.fetch(_COST_BY_PHASE_QUERY, execution_id, SESSION_SUMMARY)
        return {
            row["phase_id"]: Decimal(str(row["phase_cost"]))
            for row in phase_rows
            if row["phase_id"] and row["phase_cost"] is not None
        }

    async def _resolve_token_rows(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> tuple[list[asyncpg.Record], bool]:
        """Get the best available token data rows and whether they're from session_summary.

        Session_summary rows are grouped one row per model (see
        ``_SESSION_SUMMARY_QUERY``) so each group can be priced with its own
        model and a NULL ``sdk_cost`` in one group never silently drops out
        of the total. The token_usage fallback is grouped the same way (see
        ``_TOKEN_USAGE_FALLBACK_QUERY``).
        """
        summary_rows = await self._query_session_summaries(conn, execution_id)
        if summary_rows:
            return summary_rows, True
        return await self._query_token_usage(conn, execution_id), False

    def _build_execution_cost(
        self,
        execution_id: str,
        data: _TokenData,
        total_cost: Decimal,
        duration_ms: float,
        tool_count: int,
        turn_count: int,
        cost_by_phase: dict[str, Decimal],
        cost_by_model: dict[str, Decimal],
        unpriced_observation_count: int,
    ) -> ExecutionCost:
        """Construct the ExecutionCost read model from aggregated data."""
        return ExecutionCost(
            execution_id=execution_id,
            session_count=data.session_count,
            session_ids=data.session_ids,
            total_cost_usd=total_cost,
            token_cost_usd=total_cost,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            cache_creation_tokens=data.cache_creation,
            cache_read_tokens=data.cache_read,
            tool_calls=tool_count,
            turns=turn_count,
            duration_ms=duration_ms,
            cost_by_phase=cost_by_phase,
            cost_by_model=cost_by_model,
            unpriced_observation_count=unpriced_observation_count,
            started_at=data.started_at,
            completed_at=data.end_at,
        )

    async def calculate(self, execution_id: str) -> ExecutionCost | None:
        """Calculate execution cost from TimescaleDB.

        Prefers session_summary events (authoritative). Falls back to
        token_usage aggregation, grouped by model, for in-progress executions.
        """
        async with self._pool.acquire() as conn:
            token_rows, has_summary = await self._resolve_token_rows(conn, execution_id)
            if not token_rows:
                return None

            tool_count = (
                await conn.fetchval(_TOOL_COUNT_QUERY, execution_id, TOOL_EXECUTION_COMPLETED) or 0
            )

            if has_summary:
                priced = self._price_session_summary_groups(token_rows)
                cost_by_phase = await self._query_cost_by_phase(conn, execution_id)
            else:
                priced = self._price_token_usage_groups(token_rows)
                cost_by_phase = {}

            data = priced.data
            total_cost = priced.total_cost
            turn_count = await self._query_turn_count(conn, execution_id, data)
            cost_by_model = priced.cost_by_model
            unpriced_observation_count = priced.unpriced_observation_count

            return self._build_execution_cost(
                execution_id=execution_id,
                data=data,
                total_cost=total_cost,
                duration_ms=self._calculate_duration(data),
                tool_count=tool_count,
                turn_count=turn_count,
                cost_by_phase=cost_by_phase,
                cost_by_model=cost_by_model,
                unpriced_observation_count=unpriced_observation_count,
            )
