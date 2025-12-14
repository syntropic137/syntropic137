"""Projection for execution cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to:
- CostRecorded: Individual cost events (for real-time updates)
- SessionCostFinalized: Session completion (for accurate aggregation)
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from aef_domain.contexts.costs.domain.read_models.execution_cost import ExecutionCost


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

    async def on_cost_recorded(self, event_data: dict[str, Any]) -> None:
        """Handle CostRecorded event.

        Updates execution cost with incremental cost from a session.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            # Cost without execution - skip execution aggregation
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

        # Update started_at on first event
        if not execution_cost.started_at:
            ts = event_data.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    execution_cost.started_at = datetime.fromisoformat(ts)
                elif isinstance(ts, datetime):
                    execution_cost.started_at = ts

        # Parse cost amount
        amount_str = event_data.get("amount_usd", "0")
        amount = Decimal(str(amount_str))

        cost_type = event_data.get("cost_type", "")

        # Update totals based on cost type
        if cost_type == "llm_tokens":
            execution_cost.token_cost_usd += amount

            # Update token counts
            input_tokens = event_data.get("input_tokens") or 0
            output_tokens = event_data.get("output_tokens") or 0
            cache_creation = event_data.get("cache_creation_tokens") or 0
            cache_read = event_data.get("cache_read_tokens") or 0

            execution_cost.input_tokens += input_tokens
            execution_cost.output_tokens += output_tokens
            execution_cost.cache_creation_tokens += cache_creation
            execution_cost.cache_read_tokens += cache_read

            # Update cost by model
            model = event_data.get("model")
            if model:
                current = execution_cost.cost_by_model.get(model, Decimal("0"))
                execution_cost.cost_by_model[model] = current + amount

            # Increment turns
            execution_cost.turns += 1

        elif cost_type == "tool_execution":
            execution_cost.compute_cost_usd += amount

            # Update tool metrics
            execution_cost.tool_calls += 1

            duration = event_data.get("tool_duration_ms") or 0
            execution_cost.duration_ms += duration

            # Update cost by tool
            tool_name = event_data.get("tool_name")
            if tool_name:
                current = execution_cost.cost_by_tool.get(tool_name, Decimal("0"))
                execution_cost.cost_by_tool[tool_name] = current + amount

        elif cost_type == "compute":
            execution_cost.compute_cost_usd += amount

        # Update total
        execution_cost.total_cost_usd += amount

        # Update cost by phase
        phase_id = event_data.get("phase_id")
        if phase_id:
            current = execution_cost.cost_by_phase.get(phase_id, Decimal("0"))
            execution_cost.cost_by_phase[phase_id] = current + amount

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
