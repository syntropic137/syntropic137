"""Projection for session cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Data Sources:
- TimescaleDB: agent_events table (token_usage, tool_execution_completed)
- Event Store: SessionCostFinalized events (optional finalized totals)

See ADR-029: Simplified Event System
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp from string or datetime, returning None on failure."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _update_linkage(session_cost: SessionCost, event_data: dict[str, Any]) -> None:
    """Update execution/phase/workspace linkage from event data if not already set."""
    if not session_cost.execution_id and event_data.get("execution_id"):
        session_cost.execution_id = event_data["execution_id"]
    if not session_cost.phase_id and event_data.get("phase_id"):
        session_cost.phase_id = event_data["phase_id"]
    if not session_cost.workspace_id and event_data.get("workspace_id"):
        session_cost.workspace_id = event_data["workspace_id"]


def _set_linkage(session_cost: SessionCost, event_data: dict[str, Any]) -> None:
    """Unconditionally update linkage fields from event data."""
    if event_data.get("execution_id"):
        session_cost.execution_id = event_data["execution_id"]
    if event_data.get("phase_id"):
        session_cost.phase_id = event_data["phase_id"]
    if event_data.get("workspace_id"):
        session_cost.workspace_id = event_data["workspace_id"]


def _get_or_create_session_cost(existing: dict[str, Any] | None, session_id: str) -> SessionCost:
    """Load session cost from existing dict or create a new one."""
    return SessionCost.from_dict(existing) if existing else SessionCost(session_id=session_id)


def _apply_finalized_costs(session_cost: SessionCost, event_data: dict[str, Any]) -> None:
    """Apply finalized cost values from a SessionCostFinalized event."""
    for field, attr in [
        ("total_cost_usd", "total_cost_usd"),
        ("token_cost_usd", "token_cost_usd"),
        ("compute_cost_usd", "compute_cost_usd"),
    ]:
        value = event_data.get(field)
        if value is not None:
            setattr(session_cost, attr, Decimal(str(value)))


def _apply_finalized_tokens(session_cost: SessionCost, event_data: dict[str, Any]) -> None:
    """Apply finalized token counts and metrics."""
    session_cost.input_tokens = event_data.get("input_tokens", session_cost.input_tokens)
    session_cost.output_tokens = event_data.get("output_tokens", session_cost.output_tokens)
    session_cost.cache_creation_tokens = event_data.get(
        "cache_creation_tokens", session_cost.cache_creation_tokens
    )
    session_cost.cache_read_tokens = event_data.get(
        "cache_read_tokens", session_cost.cache_read_tokens
    )
    session_cost.tool_calls = event_data.get("tool_calls", session_cost.tool_calls)
    session_cost.turns = event_data.get("turns", session_cost.turns)
    session_cost.duration_ms = event_data.get("duration_ms", session_cost.duration_ms)


def _apply_finalized_breakdowns(session_cost: SessionCost, event_data: dict[str, Any]) -> None:
    """Apply model and tool cost breakdowns."""
    cost_by_model = event_data.get("cost_by_model", {})
    if cost_by_model:
        session_cost.cost_by_model = {k: Decimal(str(v)) for k, v in cost_by_model.items()}
    cost_by_tool = event_data.get("cost_by_tool", {})
    if cost_by_tool:
        session_cost.cost_by_tool = {k: Decimal(str(v)) for k, v in cost_by_tool.items()}


class SessionCostProjection:
    """Builds session cost from cost events.

    This projection maintains running totals for each session,
    enabling queries like "how much has session X cost so far".

    The session is the atomic unit for cost tracking:
    - Single agent
    - Single phase
    - Single workspace/sandbox
    """

    PROJECTION_NAME = "session_cost"

    def __init__(
        self, store: Any, pool: Any | None = None, cost_calculator: CostCalculator | None = None
    ):
        """Initialize with a projection store and optional DB pool.

        Args:
            store: A ProjectionStoreProtocol implementation
            pool: asyncpg Pool for querying TimescaleDB (ADR-029)
            cost_calculator: Optional CostCalculator for token cost computation
        """
        self._store = store
        self._pool = pool
        self._cost_calculator = cost_calculator or CostCalculator()

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_agent_observation(self, event_data: dict[str, Any]) -> None:
        """Handle AgentObservation event.

        Processes unified telemetry:
        - TOKEN_USAGE: Calculate cost from tokens, update counts
        - TOOL_EXECUTION_COMPLETED: Increment tool_calls count
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        event_type = event_data.get("event_type") or event_data.get("observation_type")
        if not event_type:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = _get_or_create_session_cost(existing, session_id)
        _update_linkage(session_cost, event_data)

        if not session_cost.started_at:
            session_cost.started_at = _parse_timestamp(event_data.get("timestamp"))

        data = event_data.get("data", {})
        if event_type == ObservationType.TOKEN_USAGE.value:
            self._handle_token_usage(session_cost, data)
        elif event_type == ObservationType.TOOL_EXECUTION_COMPLETED.value:
            self._handle_tool_execution(session_cost, data)

        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    def _handle_token_usage(self, session_cost: SessionCost, data: dict[str, Any]) -> None:
        """Handle TOKEN_USAGE observation data.

        Updates token counts, calculates cost, and tracks per-model breakdown.
        """
        input_tokens = data.get("input_tokens") or 0
        output_tokens = data.get("output_tokens") or 0
        cache_creation = data.get("cache_creation_tokens") or 0
        cache_read = data.get("cache_read_tokens") or 0

        # Update token counts
        session_cost.input_tokens += input_tokens
        session_cost.output_tokens += output_tokens
        session_cost.cache_creation_tokens += cache_creation
        session_cost.cache_read_tokens += cache_read

        # Calculate cost using CostCalculator
        token_cost = self._cost_calculator.calculate_token_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation=cache_creation,
            cache_read=cache_read,
        )
        session_cost.token_cost_usd += token_cost
        session_cost.total_cost_usd += token_cost

        # Update cost by model
        model = data.get("model")
        if model:
            current = session_cost.cost_by_model.get(model, Decimal("0"))
            session_cost.cost_by_model[model] = current + token_cost

        # Increment turns (each token_usage = one turn)
        session_cost.turns += 1

    def _handle_tool_execution(self, session_cost: SessionCost, data: dict[str, Any]) -> None:
        """Handle TOOL_EXECUTION_COMPLETED observation data.

        Increments tool call count and tracks duration.
        """
        session_cost.tool_calls += 1

        # Track duration if available
        duration_ms = data.get("duration_ms")
        if duration_ms:
            session_cost.duration_ms += duration_ms

        # Track tool name for breakdown
        tool_name = data.get("tool_name")
        if tool_name:
            # Track call count by tool (using cost_by_tool as counter for now)
            # Note: actual tool execution cost would need compute pricing
            pass  # Tool execution itself is free - cost is in tokens

    async def on_session_summary(self, event_data: dict[str, Any]) -> None:
        """Handle session_summary event with accurate cumulative totals.

        This event is produced at the end of agent execution and contains
        the authoritative totals from Claude CLI's result event.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = _get_or_create_session_cost(existing, session_id)
        _set_linkage(session_cost, event_data)

        data = event_data.get("data", {})

        session_cost.input_tokens = data.get("total_input_tokens", session_cost.input_tokens)
        session_cost.output_tokens = data.get("total_output_tokens", session_cost.output_tokens)
        session_cost.cache_creation_tokens = data.get(
            "cache_creation_tokens", session_cost.cache_creation_tokens
        )
        session_cost.cache_read_tokens = data.get(
            "cache_read_tokens", session_cost.cache_read_tokens
        )
        session_cost.tool_calls = data.get("tool_count", session_cost.tool_calls)
        session_cost.turns = data.get("num_turns", session_cost.turns)
        session_cost.duration_ms = data.get("duration_ms", session_cost.duration_ms)

        if data.get("model"):
            session_cost.agent_model = data["model"]

        if data.get("total_cost_usd") is not None:
            session_cost.total_cost_usd = Decimal(str(data["total_cost_usd"]))
            session_cost.token_cost_usd = session_cost.total_cost_usd

        session_cost.completed_at = _parse_timestamp(event_data.get("timestamp"))
        session_cost.is_finalized = True
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def on_session_cost_finalized(self, event_data: dict[str, Any]) -> None:
        """Handle SessionCostFinalized event.

        Marks the session as complete with final totals.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = _get_or_create_session_cost(existing, session_id)
        _set_linkage(session_cost, event_data)
        _apply_finalized_costs(session_cost, event_data)
        _apply_finalized_tokens(session_cost, event_data)
        _apply_finalized_breakdowns(session_cost, event_data)

        session_cost.started_at = (
            _parse_timestamp(event_data.get("started_at")) or session_cost.started_at
        )
        session_cost.completed_at = (
            _parse_timestamp(event_data.get("completed_at")) or session_cost.completed_at
        )
        session_cost.is_finalized = True
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        """Get session cost by session ID.

        .. deprecated::
            API routes should use ``SessionCostQueryService`` instead.
            This method remains for handler/test use. See #532.

        Queries TimescaleDB directly for real-time cost calculation.

        Args:
            session_id: The session to get cost for.

        Returns:
            SessionCost if found, None otherwise.
        """
        # Query TimescaleDB directly if observability_writer is available
        if self._pool is not None:
            return await self._calculate_from_timescale(session_id)

        # Fallback to projection store (legacy path)
        data = await self._store.get(self.PROJECTION_NAME, session_id)
        if not data:
            return None
        return SessionCost.from_dict(data)

    async def _calculate_from_timescale(self, session_id: str) -> SessionCost | None:
        """Calculate session cost directly from TimescaleDB observations.

        Delegates to TimescaleSessionCostQuery for the actual computation.

        Args:
            session_id: The session to calculate cost for

        Returns:
            SessionCost with aggregated metrics, or None if no observations found
        """
        if self._pool is None:
            return None
        query = TimescaleSessionCostQuery(self._pool, self._cost_calculator)
        return await query.calculate(session_id)

    async def get_sessions_for_execution(self, execution_id: str) -> list[SessionCost]:
        """Get all session costs for an execution.

        Args:
            execution_id: The execution to get sessions for.

        Returns:
            List of SessionCost for all sessions in the execution.
        """
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"execution_id": execution_id},
            order_by="started_at",
        )
        return [SessionCost.from_dict(d) for d in data]

    async def get_all(self) -> list[SessionCost]:
        """Get all session costs.

        .. deprecated::
            API routes should use ``SessionCostQueryService.list_all()`` instead.
            This method reads from the projection store which is always empty
            for cost data. See #532.
        """
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [SessionCost.from_dict(d) for d in data]
