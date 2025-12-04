"""Projection for session list view."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from aef_domain.contexts.sessions.domain.read_models.session_summary import (
    SessionSummary,
)


def _calculate_duration(
    started_at: str | datetime | None, completed_at: str | datetime | None
) -> float | None:
    """Calculate duration in seconds between two timestamps.

    Handles both datetime objects and ISO strings.
    """
    if not started_at or not completed_at:
        return None

    try:
        # Parse if string
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))

        return (completed_at - started_at).total_seconds()
    except (ValueError, TypeError):
        return None


class SessionListProjection:
    """Builds session list read model from events.

    This projection maintains a summary view of all sessions for
    efficient listing and filtering.
    """

    PROJECTION_NAME = "session_summaries"

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_session_started(self, event_data: dict) -> None:
        """Handle SessionStarted event."""
        session_id = event_data.get("session_id", "")
        summary = SessionSummary(
            id=session_id,
            workflow_id=event_data.get("workflow_id", ""),
            agent_type=event_data.get("agent_provider", "unknown"),
            status="running",
            total_tokens=0,
            total_cost_usd=Decimal("0"),
            started_at=event_data.get("started_at"),
            completed_at=None,
            input_tokens=0,
            output_tokens=0,
            duration_seconds=None,
            phase_id=event_data.get("phase_id"),  # Store phase_id from event
        )
        await self._store.save(self.PROJECTION_NAME, session_id, summary.to_dict())

    async def on_operation_recorded(self, event_data: dict) -> None:
        """Handle OperationRecorded - update token counts and store operation."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            # Accumulate tokens from operation
            op_tokens = event_data.get("total_tokens", 0) or event_data.get("tokens_used", 0)
            existing["total_tokens"] = existing.get("total_tokens", 0) + op_tokens
            existing["total_cost_usd"] = float(
                Decimal(str(existing.get("total_cost_usd", 0)))
                + Decimal(str(event_data.get("cost_usd", 0)))
            )

            # Store the operation in the operations list
            operations = existing.get("operations", [])
            operations.append(
                {
                    "operation_id": event_data.get("operation_id", ""),
                    "operation_type": event_data.get("operation_type", ""),
                    "timestamp": event_data.get("timestamp"),
                    "duration_seconds": event_data.get("duration_seconds"),
                    "input_tokens": event_data.get("input_tokens"),
                    "output_tokens": event_data.get("output_tokens"),
                    "total_tokens": event_data.get("total_tokens"),
                    "tool_name": event_data.get("tool_name"),
                    "success": event_data.get("success", True),
                }
            )
            existing["operations"] = operations

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def on_session_completed(self, event_data: dict) -> None:
        """Handle SessionCompleted event."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            existing["status"] = event_data.get("status", "completed")
            existing["completed_at"] = event_data.get("completed_at")

            # Token breakdown - extract input/output separately
            existing["input_tokens"] = event_data.get("total_input_tokens", 0)
            existing["output_tokens"] = event_data.get("total_output_tokens", 0)
            existing["total_tokens"] = event_data.get(
                "total_tokens", existing.get("total_tokens", 0)
            )
            existing["total_cost_usd"] = float(
                Decimal(str(event_data.get("total_cost_usd", existing.get("total_cost_usd", 0))))
            )

            # Duration calculation
            started_at = existing.get("started_at")
            completed_at = event_data.get("completed_at")
            if started_at and completed_at:
                existing["duration_seconds"] = _calculate_duration(started_at, completed_at)

            await self._store.save(self.PROJECTION_NAME, session_id, existing)

    async def get_all(self) -> list[SessionSummary]:
        """Get all sessions."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [SessionSummary.from_dict(d) for d in data]

    async def get_by_workflow(self, workflow_id: str) -> list[SessionSummary]:
        """Get sessions for a specific workflow."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"workflow_id": workflow_id},
        )
        return [SessionSummary.from_dict(d) for d in data]

    async def query(
        self,
        workflow_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-started_at",
    ) -> list[SessionSummary]:
        """Query sessions with optional filtering."""
        filters = {}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if status_filter:
            filters["status"] = status_filter

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [SessionSummary.from_dict(d) for d in data]
