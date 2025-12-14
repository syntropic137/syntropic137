"""Projection for session cost tracking.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to:
- CostRecorded: Individual cost events
- SessionCostFinalized: Session completion with final totals
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from aef_domain.contexts.costs.domain.read_models.session_cost import SessionCost


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

    async def on_cost_recorded(self, event_data: dict[str, Any]) -> None:
        """Handle CostRecorded event.

        Incrementally updates the session cost totals.
        """
        session_id = event_data.get("session_id")
        if not session_id:
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

        # Parse cost amount
        amount_str = event_data.get("amount_usd", "0")
        amount = Decimal(str(amount_str))

        cost_type = event_data.get("cost_type", "")

        # Update totals based on cost type
        if cost_type == "llm_tokens":
            session_cost.token_cost_usd += amount

            # Update token counts
            input_tokens = event_data.get("input_tokens") or 0
            output_tokens = event_data.get("output_tokens") or 0
            cache_creation = event_data.get("cache_creation_tokens") or 0
            cache_read = event_data.get("cache_read_tokens") or 0

            session_cost.input_tokens += input_tokens
            session_cost.output_tokens += output_tokens
            session_cost.cache_creation_tokens += cache_creation
            session_cost.cache_read_tokens += cache_read

            # Update cost by model
            model = event_data.get("model")
            if model:
                current = session_cost.cost_by_model.get(model, Decimal("0"))
                session_cost.cost_by_model[model] = current + amount

            # Aggregate tool token breakdown (if present)
            tool_breakdown = event_data.get("tool_token_breakdown", {})
            event_total_tokens = input_tokens + output_tokens + cache_creation + cache_read

            for tool_name, tool_tokens in tool_breakdown.items():
                tool_use = tool_tokens.get("tool_use", 0)
                tool_result = tool_tokens.get("tool_result", 0)
                total_tool_tokens = tool_use + tool_result

                # Aggregate tokens by tool
                current_tokens = session_cost.tokens_by_tool.get(tool_name, 0)
                session_cost.tokens_by_tool[tool_name] = current_tokens + total_tool_tokens

                # Calculate proportional cost for this tool
                # (tool_tokens / total_event_tokens) * event_cost
                if event_total_tokens > 0 and amount > 0:
                    tool_cost = (Decimal(total_tool_tokens) / Decimal(event_total_tokens)) * amount
                    current_cost = session_cost.cost_by_tool_tokens.get(tool_name, Decimal("0"))
                    session_cost.cost_by_tool_tokens[tool_name] = current_cost + tool_cost

            # Increment turns (each token usage = one turn)
            session_cost.turns += 1

        elif cost_type == "tool_execution":
            session_cost.compute_cost_usd += amount

            # Update tool metrics
            session_cost.tool_calls += 1

            duration = event_data.get("tool_duration_ms") or 0
            session_cost.duration_ms += duration

            # Update cost by tool
            tool_name = event_data.get("tool_name")
            if tool_name:
                current = session_cost.cost_by_tool.get(tool_name, Decimal("0"))
                session_cost.cost_by_tool[tool_name] = current + amount

        elif cost_type == "compute":
            session_cost.compute_cost_usd += amount

        # Update total
        session_cost.total_cost_usd += amount

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
