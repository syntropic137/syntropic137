"""Projection for session list view."""

from decimal import Decimal
from typing import Any

from aef_domain.contexts.sessions.domain.read_models.session_summary import (
    SessionSummary,
)


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
        )
        await self._store.save(self.PROJECTION_NAME, session_id, summary.to_dict())

    async def on_operation_recorded(self, event_data: dict) -> None:
        """Handle OperationRecorded - update token counts."""
        session_id = event_data.get("session_id")
        if not session_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, session_id)
        if existing:
            # Accumulate tokens
            existing["total_tokens"] = existing.get("total_tokens", 0) + event_data.get(
                "tokens_used", 0
            )
            existing["total_cost_usd"] = float(
                Decimal(str(existing.get("total_cost_usd", 0)))
                + Decimal(str(event_data.get("cost_usd", 0)))
            )
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
            existing["total_tokens"] = event_data.get(
                "total_tokens", existing.get("total_tokens", 0)
            )
            existing["total_cost_usd"] = float(
                Decimal(str(event_data.get("total_cost_usd", existing.get("total_cost_usd", 0))))
            )
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
