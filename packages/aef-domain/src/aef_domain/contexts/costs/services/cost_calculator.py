"""Cost calculator service.

Calculates costs from token_usage and tool_execution events,
emitting CostRecordedEvents to the event store.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from aef_domain.contexts.costs._shared.value_objects import (
    TokenCount,
    get_model_pricing,
)
from aef_domain.contexts.costs.record_cost.CostRecordedEvent import CostRecordedEvent
from aef_domain.contexts.costs.record_cost.SessionCostFinalizedEvent import (
    SessionCostFinalizedEvent,
)
from aef_domain.contexts.costs.services.tool_token_estimator import ToolTokenEstimator


class EventEmitter(Protocol):
    """Protocol for emitting domain events."""

    async def emit(self, event: Any) -> None:
        """Emit a domain event."""
        ...


class CostCalculator:
    """Calculates costs from observability events.

    This service bridges between collector events (token_usage, tool_execution)
    and domain events (CostRecorded, SessionCostFinalized).

    Usage:
        calculator = CostCalculator(event_emitter)
        await calculator.on_token_usage(event_data)
        await calculator.on_tool_execution(event_data)
        await calculator.on_session_ended(session_data)
    """

    # Default compute cost per tool execution (configurable)
    DEFAULT_COMPUTE_COST_PER_TOOL_MS = Decimal("0.000001")  # $0.001 per second

    def __init__(
        self,
        emitter: EventEmitter | None = None,
        compute_cost_per_ms: Decimal | None = None,
        tool_token_estimator: ToolTokenEstimator | None = None,
    ):
        """Initialize the cost calculator.

        Args:
            emitter: Event emitter for domain events (optional for testing).
            compute_cost_per_ms: Cost per millisecond of tool execution.
            tool_token_estimator: Estimator for tool-level token attribution.
        """
        self._emitter = emitter
        self._compute_cost_per_ms = compute_cost_per_ms or self.DEFAULT_COMPUTE_COST_PER_TOOL_MS
        self._tool_estimator = tool_token_estimator or ToolTokenEstimator()

    async def on_token_usage(self, event_data: dict[str, Any]) -> CostRecordedEvent | None:
        """Handle token_usage event and emit CostRecordedEvent.

        Args:
            event_data: Token usage event data with fields:
                - session_id: str
                - execution_id: str | None
                - phase_id: str | None
                - workspace_id: str | None
                - model: str
                - input_tokens: int
                - output_tokens: int
                - cache_creation_input_tokens: int
                - cache_read_input_tokens: int
                - timestamp: str

        Returns:
            CostRecordedEvent if emitted, None otherwise.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return None

        # Extract token counts
        input_tokens = event_data.get("input_tokens", 0)
        output_tokens = event_data.get("output_tokens", 0)
        cache_creation = event_data.get("cache_creation_input_tokens", 0)
        cache_read = event_data.get("cache_read_input_tokens", 0)

        # Get model and pricing
        model = event_data.get("model", "claude-sonnet-4-20250514")
        pricing = get_model_pricing(model)

        # Calculate cost
        tokens = TokenCount(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
        )
        cost = pricing.calculate_cost(tokens)

        # Parse timestamp
        timestamp = None
        ts_str = event_data.get("timestamp")
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()

        # Estimate tool token breakdown if tool_details present
        tool_token_breakdown: dict[str, dict[str, int]] = {}
        tool_details = event_data.get("tool_details", [])
        if tool_details:
            breakdown = self._tool_estimator.estimate_from_tool_details(tool_details)
            for tool_name, tt in breakdown.by_tool.items():
                tool_token_breakdown[tool_name] = {
                    "tool_use": tt.tool_use_tokens,
                    "tool_result": tt.tool_result_tokens,
                }

        # Create event
        cost_event = CostRecordedEvent(
            session_id=session_id,
            execution_id=event_data.get("execution_id"),
            phase_id=event_data.get("phase_id"),
            workspace_id=event_data.get("workspace_id"),
            cost_type="llm_tokens",
            amount_usd=cost.value,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
            tool_token_breakdown=tool_token_breakdown,
            timestamp=timestamp,
        )

        # Emit if emitter is configured
        if self._emitter:
            await self._emitter.emit(cost_event)

        return cost_event

    async def on_tool_execution(self, event_data: dict[str, Any]) -> CostRecordedEvent | None:
        """Handle tool_execution_completed event and emit CostRecordedEvent.

        Args:
            event_data: Tool execution event data with fields:
                - session_id: str
                - execution_id: str | None
                - phase_id: str | None
                - workspace_id: str | None
                - tool_name: str
                - duration_ms: float
                - timestamp: str

        Returns:
            CostRecordedEvent if emitted, None otherwise.
        """
        session_id = event_data.get("session_id")
        if not session_id:
            return None

        # Extract tool info
        tool_name = event_data.get("tool_name", "unknown")
        duration_ms = event_data.get("duration_ms", 0)

        # Calculate compute cost based on duration
        cost_amount = Decimal(str(duration_ms)) * self._compute_cost_per_ms

        # Parse timestamp (always use UTC for consistency)
        timestamp = None
        ts_str = event_data.get("timestamp")
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now(UTC)

        # Create event
        cost_event = CostRecordedEvent(
            session_id=session_id,
            execution_id=event_data.get("execution_id"),
            phase_id=event_data.get("phase_id"),
            workspace_id=event_data.get("workspace_id"),
            cost_type="tool_execution",
            amount_usd=cost_amount,
            tool_name=tool_name,
            tool_duration_ms=duration_ms,
            timestamp=timestamp,
        )

        # Emit if emitter is configured
        if self._emitter:
            await self._emitter.emit(cost_event)

        return cost_event

    async def on_session_ended(
        self,
        session_data: dict[str, Any],
    ) -> SessionCostFinalizedEvent | None:
        """Handle session_ended event and emit SessionCostFinalizedEvent.

        This should be called when a session completes, with aggregated
        session cost data from the SessionCostProjection.

        Args:
            session_data: Session summary with cost totals.

        Returns:
            SessionCostFinalizedEvent if emitted, None otherwise.
        """
        session_id = session_data.get("session_id")
        if not session_id:
            return None

        # Parse timestamps
        started_at = None
        sa_str = session_data.get("started_at")
        if sa_str:
            with contextlib.suppress(ValueError):
                started_at = datetime.fromisoformat(sa_str.replace("Z", "+00:00"))

        # Parse completed_at (always use UTC for consistency)
        completed_at = None
        ca_str = session_data.get("completed_at")
        if ca_str:
            with contextlib.suppress(ValueError):
                completed_at = datetime.fromisoformat(ca_str.replace("Z", "+00:00"))
        # Default to UTC now if not provided or parse failed
        if completed_at is None:
            completed_at = datetime.now(UTC)

        # Parse cost fields
        total_cost = Decimal(str(session_data.get("total_cost_usd", "0")))
        token_cost = Decimal(str(session_data.get("token_cost_usd", "0")))
        compute_cost = Decimal(str(session_data.get("compute_cost_usd", "0")))

        # Parse breakdowns
        cost_by_model = {k: str(v) for k, v in session_data.get("cost_by_model", {}).items()}
        cost_by_tool = {k: str(v) for k, v in session_data.get("cost_by_tool", {}).items()}

        # Create event
        finalized_event = SessionCostFinalizedEvent(
            session_id=session_id,
            execution_id=session_data.get("execution_id"),
            phase_id=session_data.get("phase_id"),
            workspace_id=session_data.get("workspace_id"),
            total_cost_usd=total_cost,
            token_cost_usd=token_cost,
            compute_cost_usd=compute_cost,
            input_tokens=session_data.get("input_tokens", 0),
            output_tokens=session_data.get("output_tokens", 0),
            cache_creation_tokens=session_data.get("cache_creation_tokens", 0),
            cache_read_tokens=session_data.get("cache_read_tokens", 0),
            tool_calls=session_data.get("tool_calls", 0),
            turns=session_data.get("turns", 0),
            duration_ms=session_data.get("duration_ms", 0),
            cost_by_model=cost_by_model,
            cost_by_tool=cost_by_tool,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Emit if emitter is configured
        if self._emitter:
            await self._emitter.emit(finalized_event)

        return finalized_event

    def calculate_token_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> Decimal:
        """Calculate cost for given token counts.

        Utility method for direct cost calculation without event emission.

        Args:
            model: Model identifier.
            input_tokens: Input token count.
            output_tokens: Output token count.
            cache_creation_tokens: Cache creation token count.
            cache_read_tokens: Cache read token count.

        Returns:
            Cost in USD as Decimal.
        """
        pricing = get_model_pricing(model)
        tokens = TokenCount(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        return pricing.calculate_cost(tokens).value
