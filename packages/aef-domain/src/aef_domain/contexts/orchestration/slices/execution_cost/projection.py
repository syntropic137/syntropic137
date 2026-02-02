"""Projection for execution cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to:
- AgentObservation: Unified telemetry events (all agent observations)
  - TOKEN_USAGE: Updates token counts and costs
  - TOOL_COMPLETED: Increments tool_calls count
- SessionCostFinalized: Session completion (for accurate aggregation)
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from aef_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from aef_domain.contexts.sessions.domain.events.agent_observation import ObservationType


class ExecutionCostProjection:
    """Builds execution cost by aggregating session costs.

    This projection maintains running totals for each execution,
    enabling queries like "how much has execution X cost so far".
    """

    PROJECTION_NAME = "execution_cost"

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

        Aggregates session-level observations to execution level:
        - TOKEN_USAGE: Calculate cost from tokens, update counts
        - TOOL_COMPLETED: Increment tool_calls count
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            # Observation without execution - skip execution aggregation
            return

        session_id = event_data.get("session_id")
        observation_type = event_data.get("observation_type")
        if not observation_type:
            return

        # Get existing execution cost or create new
        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        execution_cost = (
            ExecutionCost.from_dict(existing)
            if existing
            else ExecutionCost(execution_id=execution_id)
        )

        # Track session
        if session_id and session_id not in execution_cost.session_ids:
            execution_cost.session_ids.append(session_id)
            execution_cost.session_count = len(execution_cost.session_ids)

        # Update started_at on first event
        if not execution_cost.started_at:
            ts = event_data.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    execution_cost.started_at = datetime.fromisoformat(ts)
                elif isinstance(ts, datetime):
                    execution_cost.started_at = ts

        # Type-specific payload
        data = event_data.get("data", {})

        # Handle TOKEN_USAGE observations
        if observation_type == ObservationType.TOKEN_USAGE.value:
            input_tokens = data.get("input_tokens") or 0
            output_tokens = data.get("output_tokens") or 0
            cache_creation = data.get("cache_creation_tokens") or 0
            cache_read = data.get("cache_read_tokens") or 0

            # Update token counts
            execution_cost.input_tokens += input_tokens
            execution_cost.output_tokens += output_tokens
            execution_cost.cache_creation_tokens += cache_creation
            execution_cost.cache_read_tokens += cache_read

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
            execution_cost.token_cost_usd += token_cost
            execution_cost.total_cost_usd += token_cost

            # Update cost by model
            model = data.get("model")
            if model:
                current = execution_cost.cost_by_model.get(model, Decimal("0"))
                execution_cost.cost_by_model[model] = current + token_cost

            # Update cost by phase
            phase_id = event_data.get("phase_id")
            if phase_id:
                current = execution_cost.cost_by_phase.get(phase_id, Decimal("0"))
                execution_cost.cost_by_phase[phase_id] = current + token_cost

            # Increment turns
            execution_cost.turns += 1

        # Handle TOOL_COMPLETED observations
        elif observation_type == ObservationType.TOOL_COMPLETED.value:
            execution_cost.tool_calls += 1

            # Track duration if available
            duration_ms = data.get("duration_ms")
            if duration_ms:
                execution_cost.duration_ms += duration_ms

        # Save updated execution cost
        await self._store.save(self.PROJECTION_NAME, execution_id, execution_cost.to_dict())

    async def on_session_cost_finalized(self, event_data: dict[str, Any]) -> None:
        """Handle SessionCostFinalized event.

        Tracks session completion within an execution.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        session_id = event_data.get("session_id")
        if not session_id:
            return

        # Get existing execution cost or create new
        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        execution_cost = (
            ExecutionCost.from_dict(existing)
            if existing
            else ExecutionCost(execution_id=execution_id)
        )

        # Track session
        if session_id not in execution_cost.session_ids:
            execution_cost.session_ids.append(session_id)
            execution_cost.session_count = len(execution_cost.session_ids)

        # Update completed_at with latest session completion
        completed_at = event_data.get("completed_at")
        if completed_at:
            if isinstance(completed_at, str):
                completed_at = datetime.fromisoformat(completed_at)

            if not execution_cost.completed_at or completed_at > execution_cost.completed_at:
                execution_cost.completed_at = completed_at

        # Save
        await self._store.save(self.PROJECTION_NAME, execution_id, execution_cost.to_dict())

    async def get_execution_cost(self, execution_id: str) -> ExecutionCost | None:
        """Get execution cost by execution ID.

        Args:
            execution_id: The execution to get cost for.

        Returns:
            ExecutionCost if found, None otherwise.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not data:
            return None
        return ExecutionCost.from_dict(data)

    async def get_all(self) -> list[ExecutionCost]:
        """Get all execution costs."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [ExecutionCost.from_dict(d) for d in data]
