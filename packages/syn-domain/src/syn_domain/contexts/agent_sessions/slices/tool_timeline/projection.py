"""Projection for tool execution timeline.

Pattern: Event Log + CQRS (ADR-018 Pattern 2)

Subscribes to observation events from syn-collector:
- tool_execution_started
- tool_execution_completed
- tool_blocked
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from syn_domain.contexts.agent_sessions.domain.read_models.tool_execution import (
    ToolExecution,
    ToolTimeline,
)


def _as_datetime(stamp: object) -> datetime | None:
    """A recorded stamp as a datetime, whether it was stored as one or as ISO text."""
    if isinstance(stamp, datetime):
        return stamp
    if isinstance(stamp, str):
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return None
    return None


def _elapsed_ms(started: object, completed: object) -> int | None:
    """How long the call took, from the two stamps the record already holds (#1064).

    The completion observation carries no duration - its producer never
    measured one - so the only place the number exists is the gap between
    the start this record was created from and the completion updating it.
    Anything that makes that gap meaningless (an unparseable stamp, one side
    naive and the other aware, a negative result) yields None: a wrong
    duration is worse than a missing one, because nothing downstream can tell
    it apart.
    """
    start = _as_datetime(started)
    end = _as_datetime(completed)
    if start is None or end is None:
        return None
    if (start.tzinfo is None) != (end.tzinfo is None):
        return None
    elapsed = (end - start).total_seconds() * 1000
    return round(elapsed) if elapsed >= 0 else None


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

        completed_at = event_data.get("timestamp")

        if existing:
            # Update existing record
            existing["status"] = "completed"
            existing["completed_at"] = completed_at
            existing["duration_ms"] = event_data.get("duration_ms") or _elapsed_ms(
                existing.get("started_at"), completed_at
            )
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
                # Best effort: with no start row there is nothing to measure
                # from, so this record reports no duration rather than zero.
                "started_at": completed_at,
                "completed_at": completed_at,
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
