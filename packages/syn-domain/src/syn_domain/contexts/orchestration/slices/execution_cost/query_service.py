"""Read-only query service for execution cost data.

All reads go through TimescaleDB — the single source of truth for cost/token
data (Lane 2: Observability). This service does NOT read from the projection
store, which is used only by the write-side projection for event handling.

See #532 for why reads and writes were separated.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import asyncpg

from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_EXECUTION_COMPLETED,
)

# List all executions with cost data from session_summary (authoritative).
_LIST_ALL_FROM_SUMMARY_QUERY = """
SELECT
    execution_id,
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
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
ORDER BY MAX(time) DESC
"""

# Fallback: list executions from token_usage (in-progress, no summary yet)
_LIST_ALL_FROM_TOKEN_USAGE_QUERY = """
SELECT
    execution_id,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output,
    SUM(COALESCE((data->>'cache_creation_tokens')::int, 0)) as cache_creation,
    SUM(COALESCE((data->>'cache_read_tokens')::int, 0)) as cache_read,
    COUNT(DISTINCT session_id) as session_count,
    ARRAY_AGG(DISTINCT session_id) as session_ids,
    MIN(time) as started_at,
    MAX(time) as last_observation
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
"""

_TOOL_COUNT_BY_EXECUTION_QUERY = """
SELECT execution_id, COUNT(*) as cnt
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
GROUP BY execution_id
"""

# Per-execution, per-phase cost breakdown
_COST_BY_PHASE_QUERY = """
SELECT
    execution_id,
    phase_id,
    SUM((data->>'total_cost_usd')::numeric) as phase_cost
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
  AND phase_id IS NOT NULL
GROUP BY execution_id, phase_id
"""

# Per-execution, per-model cost breakdown
_COST_BY_MODEL_QUERY = """
SELECT
    execution_id,
    data->>'model' as model,
    SUM((data->>'total_cost_usd')::numeric) as model_cost
FROM agent_events
WHERE event_type = $1
  AND execution_id IS NOT NULL
  AND data->>'model' IS NOT NULL
GROUP BY execution_id, data->>'model'
"""


class ExecutionCostQueryService:
    """Read-only query service for execution cost data.

    Reads exclusively from TimescaleDB (Lane 2: Observability).
    The projection store is NOT used for reads — it serves only
    the write-side event handlers in ExecutionCostProjection.

    See #532 for the architectural rationale.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        cost_calculator: CostCalculator | None = None,
    ) -> None:
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    async def get(self, execution_id: str) -> ExecutionCost | None:
        """Get cost data for a single execution.

        Delegates to TimescaleExecutionCostQuery which handles the
        session_summary -> token_usage fallback logic.
        """
        query = TimescaleExecutionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate(execution_id)

    async def list_all(self) -> list[ExecutionCost]:
        """List cost data for all executions.

        Queries TimescaleDB directly, combining authoritative session_summary
        data with in-progress token_usage aggregation for executions that
        haven't completed yet.
        """
        async with self._pool.acquire() as conn:
            # 1. Authoritative data from session_summary events
            summary_rows = await conn.fetch(
                _LIST_ALL_FROM_SUMMARY_QUERY, SESSION_SUMMARY
            )
            summarized_exec_ids = {row["execution_id"] for row in summary_rows}

            # 2. In-progress executions from token_usage
            token_rows = await conn.fetch(
                _LIST_ALL_FROM_TOKEN_USAGE_QUERY, TOKEN_USAGE
            )

            # 3. Tool counts per execution
            tool_rows = await conn.fetch(
                _TOOL_COUNT_BY_EXECUTION_QUERY, TOOL_EXECUTION_COMPLETED
            )
            tool_counts: dict[str, int] = {
                row["execution_id"]: row["cnt"] for row in tool_rows
            }

            # 4. Phase breakdowns (from session_summary)
            phase_rows = await conn.fetch(_COST_BY_PHASE_QUERY, SESSION_SUMMARY)
            phase_map: dict[str, dict[str, Decimal]] = {}
            for row in phase_rows:
                eid = row["execution_id"]
                if eid not in phase_map:
                    phase_map[eid] = {}
                if row["phase_cost"] is not None:
                    phase_map[eid][row["phase_id"]] = Decimal(str(row["phase_cost"]))

            # 5. Model breakdowns (from session_summary)
            model_rows = await conn.fetch(_COST_BY_MODEL_QUERY, SESSION_SUMMARY)
            model_map: dict[str, dict[str, Decimal]] = {}
            for row in model_rows:
                eid = row["execution_id"]
                if eid not in model_map:
                    model_map[eid] = {}
                if row["model_cost"] is not None:
                    model_map[eid][row["model"]] = Decimal(str(row["model_cost"]))

            results: list[ExecutionCost] = []

            # Build from session_summary rows (authoritative)
            for row in summary_rows:
                eid = row["execution_id"]
                sdk_cost = (
                    Decimal(str(row["sdk_cost"]))
                    if row["sdk_cost"] is not None
                    else self._cost_calculator.calculate_token_cost(
                        input_tokens=row["total_input"] or 0,
                        output_tokens=row["total_output"] or 0,
                        cache_creation=row["cache_creation"] or 0,
                        cache_read=row["cache_read"] or 0,
                    )
                )
                ec = ExecutionCost(
                    execution_id=eid,
                    session_count=row["session_count"] or 0,
                    session_ids=list(row["session_ids"] or []),
                    total_cost_usd=sdk_cost,
                    token_cost_usd=sdk_cost,
                    input_tokens=row["total_input"] or 0,
                    output_tokens=row["total_output"] or 0,
                    cache_creation_tokens=row["cache_creation"] or 0,
                    cache_read_tokens=row["cache_read"] or 0,
                    tool_calls=tool_counts.get(eid, 0),
                    turns=row["total_turns"] or 0,
                    duration_ms=float(row["duration_ms_val"] or 0),
                    cost_by_phase=phase_map.get(eid, {}),
                    cost_by_model=model_map.get(eid, {}),
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
                results.append(ec)

            # Build from token_usage rows (in-progress, no summary yet)
            for row in token_rows:
                eid = row["execution_id"]
                if eid in summarized_exec_ids:
                    continue

                total_input = row["total_input"] or 0
                total_output = row["total_output"] or 0
                cache_creation = row["cache_creation"] or 0
                cache_read = row["cache_read"] or 0

                cost = self._cost_calculator.calculate_token_cost(
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cache_creation=cache_creation,
                    cache_read=cache_read,
                )
                ec = ExecutionCost(
                    execution_id=eid,
                    session_count=row["session_count"] or 0,
                    session_ids=list(row["session_ids"] or []),
                    total_cost_usd=cost,
                    token_cost_usd=cost,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                    tool_calls=tool_counts.get(eid, 0),
                    started_at=row["started_at"],
                    completed_at=row.get("last_observation"),
                )
                results.append(ec)

            return results
