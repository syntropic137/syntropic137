"""Projection for session cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Data Sources:
- TimescaleDB: agent_events table (token_usage, tool_execution_completed)
- Event Store: SessionCostFinalized events (optional finalized totals)

See ADR-029: Simplified Event System
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg
    from event_sourcing import ProjectionStore

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import ObservationType
from syn_domain.contexts.agent_sessions.domain.read_models.session_cost import SessionCost
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.agent_sessions.slices.session_cost.timescale_query import (
    TimescaleSessionCostQuery,
)


def _parse_timestamp(value: object) -> datetime | None:
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


def _reported[N: (int, float)](data: dict[str, Any], key: str, current: N) -> N:
    """The summary's value for ``key``, or ``current`` when it did not report one.

    ``dict.get(key, default)`` is not enough: a harness that was killed still
    emits the key, carrying ``None``. Absent and null mean the same thing here -
    nobody counted this - and neither is a reason to discard what the
    observations already counted.
    """
    value = data.get(key)
    return current if value is None else value


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
        self,
        store: ProjectionStore,
        pool: asyncpg.Pool | None = None,
        cost_calculator: CostCalculator | None = None,
    ):
        """Initialize with a projection store and optional DB pool.

        Args:
            store: A ProjectionStore implementation
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

        # Resolve pricing STRICTLY: an unknown/missing model contributes
        # zero cost, never a guessed default model's price (issue #788).
        model = data.get("model")
        pricing = self._cost_calculator.resolve_pricing(model)
        if pricing is None:
            token_cost = Decimal("0")
            session_cost.unpriced_observation_count += 1
        else:
            token_cost = pricing.calculate_cost(
                input_tokens, output_tokens, cache_creation, cache_read
            )
        session_cost.token_cost_usd += token_cost
        session_cost.total_cost_usd += token_cost

        # Update cost by model (only for observations we could actually price)
        if model and pricing is not None:
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
        """Apply a run's end-of-run totals, without letting silence overwrite counts.

        A summary reports what the harness knew when the run ended, and a run
        that was killed or timed out never got to say. Two rules keep that from
        being read as "spent nothing" (#1164):

        - A field the summary does not actually report - absent, or present as
          ``None`` because the harness never filled it in - leaves the counted
          value alone. ``num_turns: None`` from a timed-out phase used to be
          assigned straight over the turns counted from its observations,
          replacing a real 3 with ``None`` in an ``int`` field.
        - ``is_finalized`` follows ``totals_are_authoritative``: the session is
          settled only when the harness reported its own totals. A phase killed
          mid-run is still the best estimate available, not a final bill, and
          the dashboard badge says so. Summaries written before that flag
          existed carry no key and keep the original settled semantics.

        Reported values still REPLACE rather than add: per-turn deltas
        double-count the context re-sent each turn, so the harness's cumulative
        figure is lower than the accumulated sum and is the one to trust.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = _get_or_create_session_cost(existing, session_id)
        _set_linkage(session_cost, event_data)

        data = event_data.get("data", {})

        session_cost.input_tokens = _reported(data, "total_input_tokens", session_cost.input_tokens)
        session_cost.output_tokens = _reported(
            data, "total_output_tokens", session_cost.output_tokens
        )
        session_cost.cache_creation_tokens = _reported(
            data, "cache_creation_tokens", session_cost.cache_creation_tokens
        )
        session_cost.cache_read_tokens = _reported(
            data, "cache_read_tokens", session_cost.cache_read_tokens
        )
        session_cost.tool_calls = _reported(data, "tool_count", session_cost.tool_calls)
        session_cost.turns = _reported(data, "num_turns", session_cost.turns)
        session_cost.duration_ms = _reported(data, "duration_ms", session_cost.duration_ms)

        if data.get("model"):
            session_cost.agent_model = data["model"]

        # An absent cost leaves the running one alone, and nothing recomputes it
        # here: it was priced per observation with that observation's own model
        # (#788), so re-pricing the totals under the summary's single model
        # would be wrong for any session that spanned two. Leaving it is also
        # what keeps a killed phase agreeing with the last figure the live path
        # reported, instead of dropping to $0.00.
        if data.get("total_cost_usd") is not None:
            session_cost.total_cost_usd = Decimal(str(data["total_cost_usd"]))
            session_cost.token_cost_usd = session_cost.total_cost_usd

        session_cost.completed_at = _parse_timestamp(event_data.get("timestamp"))
        session_cost.is_finalized = bool(data.get("totals_are_authoritative", True))
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
