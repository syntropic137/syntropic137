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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# Prefer session_summary rows (authoritative totals from Claude CLI).
# Aggregates across all sessions in the execution.
_SESSION_SUMMARY_QUERY = """
SELECT
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
    MAX(time) as completed_at
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
"""

# Fallback: aggregate from individual token_usage events when no
# session_summary is available (e.g. mid-execution queries).
_TOKEN_USAGE_FALLBACK_QUERY = """
SELECT
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation
FROM agent_events
WHERE execution_id = $1 AND event_type = $2
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

# Per-model cost breakdown from session_summary events
_COST_BY_MODEL_QUERY = """
SELECT
    data->>'model' as model,
    SUM((data->>'total_cost_usd')::numeric) as model_cost
FROM agent_events
WHERE execution_id = $1
  AND event_type = $2
  AND data->>'model' IS NOT NULL
GROUP BY data->>'model'
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
    ) -> asyncpg.Record | None:
        """Query session_summary events for authoritative totals."""
        return await conn.fetchrow(_SESSION_SUMMARY_QUERY, execution_id, SESSION_SUMMARY)

    async def _query_token_usage(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> asyncpg.Record | None:
        """Query token_usage events as fallback for in-progress executions."""
        return await conn.fetchrow(_TOKEN_USAGE_FALLBACK_QUERY, execution_id, TOKEN_USAGE)

    def _extract_common_fields(self, row: asyncpg.Record) -> dict[str, Any]:
        """Extract common token fields shared by both query types."""
        return {
            "input_tokens": row["total_input"] or 0,
            "output_tokens": row["total_output"] or 0,
            "cache_creation": row.get("cache_creation") or 0,
            "cache_read": row.get("cache_read") or 0,
            "session_count": row.get("session_count") or 0,
            "session_ids": list(row.get("session_ids") or []),
            "started_at": row.get("started_at"),
        }

    def _extract_token_data(self, row: asyncpg.Record, from_summary: bool) -> _TokenData:
        """Extract token counts and metadata from a query row."""
        common = self._extract_common_fields(row)
        sdk_cost = Decimal(str(row["sdk_cost"])) if row.get("sdk_cost") is not None else None
        return _TokenData(
            **common,
            end_at=row.get("completed_at" if from_summary else "last_observation"),
            sdk_cost=sdk_cost if from_summary else None,
            duration_ms_raw=int(row.get("duration_ms_val") or 0) if from_summary else 0,
            total_turns=int(row.get("total_turns") or 0) if from_summary else 0,
            from_summary=from_summary,
        )

    def _calculate_cost(self, data: _TokenData) -> Decimal:
        """Calculate total cost from token data, preferring SDK cost."""
        if data.sdk_cost is not None:
            return data.sdk_cost
        return self._cost_calculator.calculate_token_cost(
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            cache_creation=data.cache_creation,
            cache_read=data.cache_read,
        )

    def _calculate_duration(self, data: _TokenData) -> float:
        """Calculate duration in ms from token data."""
        if data.from_summary:
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

    async def _query_cost_by_model(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> dict[str, Decimal]:
        """Query per-model cost breakdown from session_summary events."""
        model_rows = await conn.fetch(_COST_BY_MODEL_QUERY, execution_id, SESSION_SUMMARY)
        return {
            row["model"]: Decimal(str(row["model_cost"]))
            for row in model_rows
            if row["model"] and row["model_cost"] is not None
        }

    async def _resolve_token_row(
        self, conn: asyncpg.pool.PoolConnectionProxy, execution_id: str
    ) -> tuple[asyncpg.Record | None, bool]:
        """Get the best available token data row and whether it's from session_summary."""
        summary_row = await self._query_session_summaries(conn, execution_id)
        if summary_row is not None and summary_row["total_input"] is not None:
            return summary_row, True
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
            started_at=data.started_at,
            completed_at=data.end_at,
        )

    async def calculate(self, execution_id: str) -> ExecutionCost | None:
        """Calculate execution cost from TimescaleDB.

        Prefers session_summary events (authoritative). Falls back to
        token_usage aggregation for in-progress executions.
        """
        async with self._pool.acquire() as conn:
            token_row, has_summary = await self._resolve_token_row(conn, execution_id)
            if token_row is None or token_row["total_input"] is None:
                return None

            data = self._extract_token_data(token_row, from_summary=has_summary)
            tool_count = (
                await conn.fetchval(_TOOL_COUNT_QUERY, execution_id, TOOL_EXECUTION_COMPLETED) or 0
            )
            turn_count = await self._query_turn_count(conn, execution_id, data)
            cost_by_phase = (
                await self._query_cost_by_phase(conn, execution_id) if has_summary else {}
            )
            cost_by_model = (
                await self._query_cost_by_model(conn, execution_id) if has_summary else {}
            )

            return self._build_execution_cost(
                execution_id=execution_id,
                data=data,
                total_cost=self._calculate_cost(data),
                duration_ms=self._calculate_duration(data),
                tool_count=tool_count,
                turn_count=turn_count,
                cost_by_phase=cost_by_phase,
                cost_by_model=cost_by_model,
            )
