"""Projection for session cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to:
- AgentObservation: Unified telemetry events (all agent observations)
  - TOKEN_USAGE: Updates token counts and costs
  - TOOL_COMPLETED: Increments tool_calls count
- SessionCostFinalized: Session completion with final totals
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from aef_domain.contexts.costs.domain.read_models.session_cost import SessionCost
from aef_domain.contexts.observability.domain.events.agent_observation import ObservationType


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

    def __init__(self, store: Any):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_agent_observation(self, event_data: dict[str, Any]) -> None:
        """Handle AgentObservation event.

        Processes unified telemetry:
        - TOKEN_USAGE: Calculate cost from tokens, update counts
        - TOOL_COMPLETED: Increment tool_calls count
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        observation_type = event_data.get("observation_type")
        if not observation_type:
            return

        # Get existing session cost or create new
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        session_cost = (
            SessionCost.from_dict(existing) if existing else SessionCost(session_id=session_id)
        )

        # Update linkage if not set
        if not session_cost.execution_id and event_data.get("execution_id"):
            session_cost.execution_id = event_data["execution_id"]
        if not session_cost.phase_id and event_data.get("phase_id"):
            session_cost.phase_id = event_data["phase_id"]
        if not session_cost.workspace_id and event_data.get("workspace_id"):
            session_cost.workspace_id = event_data["workspace_id"]

        # Update started_at on first event
        if not session_cost.started_at:
            ts = event_data.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    session_cost.started_at = datetime.fromisoformat(ts)
                elif isinstance(ts, datetime):
                    session_cost.started_at = ts

        # Type-specific payload
        data = event_data.get("data", {})

        # Handle TOKEN_USAGE observations
        if observation_type == ObservationType.TOKEN_USAGE.value:
            input_tokens = data.get("input_tokens") or 0
            output_tokens = data.get("output_tokens") or 0
            cache_creation = data.get("cache_creation_tokens") or 0
            cache_read = data.get("cache_read_tokens") or 0

            # Update token counts
            session_cost.input_tokens += input_tokens
            session_cost.output_tokens += output_tokens
            session_cost.cache_creation_tokens += cache_creation
            session_cost.cache_read_tokens += cache_read

            # Calculate cost (using default pricing - can be enhanced with ModelPricing)
            # Prices per 1M tokens (Claude 3.5 Sonnet pricing)
            input_price_per_million = Decimal("3.00")  # $3/MTok input
            output_price_per_million = Decimal("15.00")  # $15/MTok output
            cache_write_per_million = Decimal("3.75")  # $3.75/MTok cache write
            cache_read_per_million = Decimal("0.30")  # $0.30/MTok cache read

            input_cost = (Decimal(input_tokens) / 1_000_000) * input_price_per_million
            output_cost = (Decimal(output_tokens) / 1_000_000) * output_price_per_million
            cache_write_cost = (Decimal(cache_creation) / 1_000_000) * cache_write_per_million
            cache_read_cost = (Decimal(cache_read) / 1_000_000) * cache_read_per_million

            token_cost = input_cost + output_cost + cache_write_cost + cache_read_cost
            session_cost.token_cost_usd += token_cost
            session_cost.total_cost_usd += token_cost

            # Update cost by model
            model = data.get("model")
            if model:
                current = session_cost.cost_by_model.get(model, Decimal("0"))
                session_cost.cost_by_model[model] = current + token_cost

            # Increment turns (each token_usage = one turn)
            session_cost.turns += 1

        # Handle TOOL_COMPLETED observations
        elif observation_type == ObservationType.TOOL_COMPLETED.value:
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

        # Save updated session cost
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def on_session_cost_finalized(self, event_data: dict[str, Any]) -> None:
        """Handle SessionCostFinalized event.

        Marks the session as complete with final totals.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return

        # Get existing or create from finalized data
        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            session_cost = SessionCost.from_dict(existing)
        else:
            session_cost = SessionCost(session_id=session_id)

        # Update from finalized event
        session_cost.execution_id = event_data.get("execution_id") or session_cost.execution_id
        session_cost.phase_id = event_data.get("phase_id") or session_cost.phase_id
        session_cost.workspace_id = event_data.get("workspace_id") or session_cost.workspace_id

        # Use finalized totals
        total_cost = event_data.get("total_cost_usd")
        if total_cost:
            session_cost.total_cost_usd = Decimal(str(total_cost))

        token_cost = event_data.get("token_cost_usd")
        if token_cost:
            session_cost.token_cost_usd = Decimal(str(token_cost))

        compute_cost = event_data.get("compute_cost_usd")
        if compute_cost:
            session_cost.compute_cost_usd = Decimal(str(compute_cost))

        # Token counts
        session_cost.input_tokens = event_data.get("input_tokens", session_cost.input_tokens)
        session_cost.output_tokens = event_data.get("output_tokens", session_cost.output_tokens)
        session_cost.cache_creation_tokens = event_data.get(
            "cache_creation_tokens", session_cost.cache_creation_tokens
        )
        session_cost.cache_read_tokens = event_data.get(
            "cache_read_tokens", session_cost.cache_read_tokens
        )

        # Metrics
        session_cost.tool_calls = event_data.get("tool_calls", session_cost.tool_calls)
        session_cost.turns = event_data.get("turns", session_cost.turns)
        session_cost.duration_ms = event_data.get("duration_ms", session_cost.duration_ms)

        # Breakdowns
        cost_by_model = event_data.get("cost_by_model", {})
        if cost_by_model:
            session_cost.cost_by_model = {k: Decimal(str(v)) for k, v in cost_by_model.items()}

        cost_by_tool = event_data.get("cost_by_tool", {})
        if cost_by_tool:
            session_cost.cost_by_tool = {k: Decimal(str(v)) for k, v in cost_by_tool.items()}

        # Timing
        started_at = event_data.get("started_at")
        if started_at:
            if isinstance(started_at, str):
                session_cost.started_at = datetime.fromisoformat(started_at)
            else:
                session_cost.started_at = started_at

        completed_at = event_data.get("completed_at")
        if completed_at:
            if isinstance(completed_at, str):
                session_cost.completed_at = datetime.fromisoformat(completed_at)
            else:
                session_cost.completed_at = completed_at

        # Mark as finalized
        session_cost.is_finalized = True

        # Save
        await self._store.save(self.PROJECTION_NAME, session_id, session_cost.to_dict())

    async def get_session_cost(self, session_id: str) -> SessionCost | None:
        """Get session cost by session ID.

        Args:
            session_id: The session to get cost for.

        Returns:
            SessionCost if found, None otherwise.
        """
        data = await self._store.get(self.PROJECTION_NAME, session_id)
        if not data:
            return None
        return SessionCost.from_dict(data)

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
        """Get all session costs."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [SessionCost.from_dict(d) for d in data]
