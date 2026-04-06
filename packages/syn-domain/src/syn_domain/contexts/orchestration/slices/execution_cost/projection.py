"""Projection for execution cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to:
- AgentObservation: Unified telemetry events (all agent observations)
  - TOKEN_USAGE: Updates token counts and costs
  - TOOL_EXECUTION_COMPLETED: Increments tool_calls count
- SessionCostFinalized: Session completion (for accurate aggregation)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_shared.pricing import get_model_pricing


def _get_or_create(existing: dict[str, Any] | None, execution_id: str) -> ExecutionCost:
    """Load execution cost from existing dict or create a new one."""
    return (
        ExecutionCost.from_dict(existing) if existing else ExecutionCost(execution_id=execution_id)
    )


def _track_session(execution_cost: ExecutionCost, session_id: str | None) -> None:
    """Add session_id to session list if not already tracked."""
    if session_id and session_id not in execution_cost.session_ids:
        execution_cost.session_ids.append(session_id)
        execution_cost.session_count = len(execution_cost.session_ids)


def _update_started_at(execution_cost: ExecutionCost, ts: str | datetime | None) -> None:
    """Set started_at from timestamp if not already set."""
    if execution_cost.started_at or not ts:
        return
    if isinstance(ts, str):
        execution_cost.started_at = datetime.fromisoformat(ts)
    elif isinstance(ts, datetime):
        execution_cost.started_at = ts


def _calculate_token_cost(
    input_tokens: int,
    output_tokens: int,
    cache_creation: int,
    cache_read: int,
    model: str | None = None,
) -> Decimal:
    """Calculate token cost from counts using model-specific pricing."""
    pricing = get_model_pricing(model or "")
    return pricing.calculate_cost(input_tokens, output_tokens, cache_creation, cache_read)


def _apply_token_usage(
    execution_cost: ExecutionCost,
    data: dict[str, Any],
    event_data: dict[str, Any],
) -> None:
    """Apply TOKEN_USAGE observation to execution cost."""
    input_tokens = data.get("input_tokens") or 0
    output_tokens = data.get("output_tokens") or 0
    cache_creation = data.get("cache_creation_tokens") or 0
    cache_read = data.get("cache_read_tokens") or 0

    execution_cost.input_tokens += input_tokens
    execution_cost.output_tokens += output_tokens
    execution_cost.cache_creation_tokens += cache_creation
    execution_cost.cache_read_tokens += cache_read

    model = data.get("model")
    token_cost = _calculate_token_cost(
        input_tokens, output_tokens, cache_creation, cache_read, model=model
    )
    execution_cost.token_cost_usd += token_cost
    execution_cost.total_cost_usd += token_cost
    if model:
        current = execution_cost.cost_by_model.get(model, Decimal("0"))
        execution_cost.cost_by_model[model] = current + token_cost

    phase_id = event_data.get("phase_id")
    if phase_id:
        current = execution_cost.cost_by_phase.get(phase_id, Decimal("0"))
        execution_cost.cost_by_phase[phase_id] = current + token_cost

    execution_cost.turns += 1


def _apply_tool_execution(execution_cost: ExecutionCost, data: dict[str, Any]) -> None:
    """Apply TOOL_EXECUTION_COMPLETED observation to execution cost."""
    execution_cost.tool_calls += 1
    duration_ms = data.get("duration_ms")
    if duration_ms:
        execution_cost.duration_ms += duration_ms


def _update_completed_at(execution_cost: ExecutionCost, ts: str | datetime | None) -> None:
    """Update completed_at if the new timestamp is later."""
    if not ts:
        return
    completed_at = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    if not execution_cost.completed_at or completed_at > execution_cost.completed_at:
        execution_cost.completed_at = completed_at


class ExecutionCostProjection:
    """Builds execution cost by aggregating session costs.

    This projection maintains running totals for each execution,
    enabling queries like "how much has execution X cost so far".

    Data Sources:
    - TimescaleDB: agent_events table (token_usage, session_summary) — preferred
    - Projection Store: fallback for environments without TimescaleDB
    """

    PROJECTION_NAME = "execution_cost"

    def __init__(self, store: Any, pool: Any | None = None):  # noqa: ANN401
        """Initialize with a projection store and optional TimescaleDB pool.

        Args:
            store: A ProjectionStoreProtocol implementation
            pool: asyncpg Pool for querying TimescaleDB directly (ADR-029).
                  When available, query methods bypass the (empty) projection
                  store and read from the actual observability data source.
        """
        self._store = store
        self._pool = pool

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_agent_observation(self, event_data: dict[str, Any]) -> None:
        """Handle AgentObservation event.

        Aggregates session-level observations to execution level:
        - TOKEN_USAGE: Calculate cost from tokens, update counts
        - TOOL_EXECUTION_COMPLETED: Increment tool_calls count
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        event_type = event_data.get("event_type") or event_data.get("observation_type")
        if not event_type:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        execution_cost = _get_or_create(existing, execution_id)
        _track_session(execution_cost, event_data.get("session_id"))
        _update_started_at(execution_cost, event_data.get("timestamp"))

        data = event_data.get("data", {})
        if event_type == ObservationType.TOKEN_USAGE.value:
            _apply_token_usage(execution_cost, data, event_data)
        elif event_type == ObservationType.TOOL_EXECUTION_COMPLETED.value:
            _apply_tool_execution(execution_cost, data)

        await self._store.save(self.PROJECTION_NAME, execution_id, execution_cost.to_dict())

    async def on_session_summary(self, event_data: dict[str, Any]) -> None:
        """Handle session_summary event with accurate cumulative totals.

        This event is produced at the end of agent execution and contains
        the authoritative totals from Claude CLI's result event.
        """
        execution_id = event_data.get("execution_id")
        session_id = event_data.get("session_id")
        if not execution_id or not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        execution_cost = _get_or_create(existing, execution_id)
        _track_session(execution_cost, session_id)

        data = event_data.get("data", {})
        execution_cost.input_tokens += data.get("total_input_tokens", 0)
        execution_cost.output_tokens += data.get("total_output_tokens", 0)
        execution_cost.tool_calls += data.get("tool_count", 0)
        execution_cost.turns += data.get("num_turns", 0)
        execution_cost.duration_ms += data.get("duration_ms", 0) or 0

        if data.get("total_cost_usd") is not None:
            session_cost = Decimal(str(data["total_cost_usd"]))
            execution_cost.token_cost_usd += session_cost
            execution_cost.total_cost_usd += session_cost

            phase_id = event_data.get("phase_id")
            if phase_id:
                current = execution_cost.cost_by_phase.get(phase_id, Decimal("0"))
                execution_cost.cost_by_phase[phase_id] = current + session_cost

        _update_completed_at(execution_cost, event_data.get("timestamp"))
        await self._store.save(self.PROJECTION_NAME, execution_id, execution_cost.to_dict())

    async def on_session_cost_finalized(self, event_data: dict[str, Any]) -> None:
        """Handle SessionCostFinalized event."""
        execution_id = event_data.get("execution_id")
        session_id = event_data.get("session_id")
        if not execution_id or not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        execution_cost = _get_or_create(existing, execution_id)
        _track_session(execution_cost, session_id)
        _update_completed_at(execution_cost, event_data.get("completed_at"))
        await self._store.save(self.PROJECTION_NAME, execution_id, execution_cost.to_dict())

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        """Get execution cost by execution ID.

        .. deprecated::
            API routes should use ``ExecutionCostQueryService`` instead.
            This method remains for handler/test use. See #532.

        Queries TimescaleDB directly when a pool is available (preferred).
        Falls back to projection store for environments without TimescaleDB.

        Args:
            execution_id: The execution to get cost for.

        Returns:
            ExecutionCost if found, None otherwise.
        """
        # Query TimescaleDB directly if pool is available
        if self._pool is not None:
            return await self._query_timescale(execution_id)

        # Fallback to projection store (legacy path)
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not data:
            return None
        return ExecutionCost.from_dict(data)

    async def _query_timescale(self, execution_id: str) -> ExecutionCost | None:
        """Calculate execution cost directly from TimescaleDB observations.

        Delegates to TimescaleExecutionCostQuery for the actual computation.

        Args:
            execution_id: The execution to calculate cost for

        Returns:
            ExecutionCost with aggregated metrics, or None if no observations found
        """
        if self._pool is None:
            return None
        from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
            TimescaleExecutionCostQuery,
        )

        query = TimescaleExecutionCostQuery(self._pool)
        return await query.calculate(execution_id)

    async def get_all(self) -> list[ExecutionCost]:
        """Get all execution costs.

        .. deprecated::
            API routes should use ``ExecutionCostQueryService.list_all()`` instead.
            This method reads from the projection store which is always empty
            for cost data. See #532.
        """
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [ExecutionCost.from_dict(d) for d in data]
