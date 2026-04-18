"""Projection for tool execution timeline.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to observation events from syn-collector:
- tool_execution_started
- tool_execution_completed
- tool_blocked
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from syn_domain.contexts.agent_sessions.domain.read_models.tool_execution import (
    ToolExecution,
    ToolTimeline,
)


class ToolTimelineProjection:
    """Builds tool execution timeline from observation events.

    This projection maintains a timeline view of tool executions for
    each session, enabling queries like "what tools were used in session X".

    Note: This uses Pattern 2 (Event Log + CQRS) - observations flow
    directly to this projection without aggregate validation.
    See ADR-018 for architectural rationale.
    """

    PROJECTION_NAME = "tool_timelines"

    def __init__(self, store: ProjectionStore):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_tool_execution_started(self, event_data: dict[str, Any]) -> None:
        """Handle tool_execution_started observation.

        Creates a new tool execution record with 'started' status.
        """
        session_id = event_data.get("session_id")
        tool_use_id = event_data.get("tool_use_id")

        if not session_id or not tool_use_id:
            return

        execution = {
            "event_id": event_data.get("event_id", ""),
            "session_id": session_id,
            "tool_name": event_data.get("tool_name", "unknown"),
            "tool_use_id": tool_use_id,
            "status": "started",
            "started_at": event_data.get("timestamp"),
            "tool_input": event_data.get("tool_input"),
        }

        # Store by session_id#tool_use_id for correlation
        key = f"{session_id}#{tool_use_id}"
        await self._store.save(self.PROJECTION_NAME, key, execution)

    async def on_tool_execution_completed(self, event_data: dict[str, Any]) -> None:
        """Handle tool_execution_completed observation.

        Updates existing tool execution record to 'completed' status.
        """
        session_id = event_data.get("session_id")
        tool_use_id = event_data.get("tool_use_id")

        if not session_id or not tool_use_id:
            return

        key = f"{session_id}#{tool_use_id}"
        existing = await self._store.get(self.PROJECTION_NAME, key)

        if existing:
            # Update existing record
            existing["status"] = "completed"
            existing["completed_at"] = event_data.get("timestamp")
            existing["duration_ms"] = event_data.get("duration_ms")
            existing["success"] = event_data.get("success", True)
            existing["tool_output"] = event_data.get("tool_output")
            await self._store.save(self.PROJECTION_NAME, key, existing)
        else:
            # Create new record if started event was missed
            execution = {
                "event_id": event_data.get("event_id", ""),
                "session_id": session_id,
                "tool_name": event_data.get("tool_name", "unknown"),
                "tool_use_id": tool_use_id,
                "status": "completed",
                "started_at": event_data.get("timestamp"),  # Best effort
                "completed_at": event_data.get("timestamp"),
                "duration_ms": event_data.get("duration_ms"),
                "success": event_data.get("success", True),
                "tool_output": event_data.get("tool_output"),
            }
            await self._store.save(self.PROJECTION_NAME, key, execution)

    async def on_tool_blocked(self, event_data: dict[str, Any]) -> None:
        """Handle tool_blocked observation.

        Creates a tool execution record with 'blocked' status.
        """
        session_id = event_data.get("session_id")
        tool_use_id = event_data.get("tool_use_id")

        if not session_id or not tool_use_id:
            return

        execution = {
            "event_id": event_data.get("event_id", ""),
            "session_id": session_id,
            "tool_name": event_data.get("tool_name", "unknown"),
            "tool_use_id": tool_use_id,
            "status": "blocked",
            "started_at": event_data.get("timestamp"),
            "block_reason": event_data.get("reason"),
            "tool_input": event_data.get("tool_input"),
        }

        key = f"{session_id}#{tool_use_id}"
        await self._store.save(self.PROJECTION_NAME, key, execution)

    async def get_timeline(self, session_id: str) -> ToolTimeline:
        """Get tool execution timeline for a session.

        Args:
            session_id: The session to get timeline for.

        Returns:
            ToolTimeline with all executions for the session.
        """
        # Query all executions for this session
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"session_id": session_id},
            order_by="started_at",
        )

        executions = [ToolExecution.from_dict(d) for d in data]
        return ToolTimeline.from_executions(session_id, executions)

    async def get_all(self) -> list[ToolExecution]:
        """Get all tool executions across all sessions."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [ToolExecution.from_dict(d) for d in data]
