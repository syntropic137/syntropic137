"""Read models for tool execution timeline."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ToolExecution:
    """Single tool execution record.

    Represents an observed tool execution from the syn-collector.
    This is Pattern 2 (Event Log + CQRS) - observations, not commands.
    """

    event_id: str
    """Deterministic event ID for deduplication."""

    session_id: str
    """Session this tool execution belongs to."""

    tool_name: str
    """Name of the tool executed."""

    tool_use_id: str
    """Claude's tool_use_id for correlation."""

    status: str
    """Execution status: 'started', 'completed', or 'blocked'."""

    started_at: datetime | str
    """When the tool execution started."""

    completed_at: datetime | str | None = None
    """When the tool execution completed (if completed)."""

    duration_ms: int | None = None
    """Duration in milliseconds (if completed)."""

    success: bool | None = None
    """Whether execution succeeded (if completed)."""

    block_reason: str | None = None
    """Reason for blocking (if blocked)."""

    tool_input: dict[str, Any] | None = None
    """Input parameters passed to the tool."""

    tool_output: str | None = None
    """Output from the tool (if completed)."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolExecution":
        """Create from dictionary."""
        # started_at is required, default to empty string if missing
        started_at = data.get("started_at") or ""
        return cls(
            event_id=data.get("event_id", ""),
            session_id=data.get("session_id", ""),
            tool_name=data.get("tool_name", ""),
            tool_use_id=data.get("tool_use_id", ""),
            status=data.get("status", "unknown"),
            started_at=started_at,
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms"),
            success=data.get("success"),
            block_reason=data.get("block_reason"),
            tool_input=data.get("tool_input"),
            tool_output=data.get("tool_output"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        started = self.started_at
        if isinstance(started, datetime):
            started = started.isoformat()

        completed = self.completed_at
        if isinstance(completed, datetime):
            completed = completed.isoformat()

        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "status": self.status,
            "started_at": started,
            "completed_at": completed,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "block_reason": self.block_reason,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
        }


@dataclass(frozen=True)
class ToolTimeline:
    """Timeline of tool executions for a session.

    Aggregated view of all tool executions in a session.
    """

    session_id: str
    """Session ID this timeline belongs to."""

    executions: tuple[ToolExecution, ...]
    """All tool executions in chronological order."""

    total_executions: int
    """Total number of tool executions."""

    completed_count: int
    """Number of completed executions."""

    blocked_count: int
    """Number of blocked executions."""

    avg_duration_ms: float | None
    """Average duration of completed executions."""

    @classmethod
    def from_executions(
        cls,
        session_id: str,
        executions: list[ToolExecution],
    ) -> "ToolTimeline":
        """Create timeline from list of executions."""
        completed = [e for e in executions if e.status == "completed"]
        blocked = [e for e in executions if e.status == "blocked"]

        durations = [e.duration_ms for e in completed if e.duration_ms is not None]
        avg_duration = sum(durations) / len(durations) if durations else None

        return cls(
            session_id=session_id,
            executions=tuple(executions),
            total_executions=len(executions),
            completed_count=len(completed),
            blocked_count=len(blocked),
            avg_duration_ms=avg_duration,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "executions": [e.to_dict() for e in self.executions],
            "total_executions": self.total_executions,
            "completed_count": self.completed_count,
            "blocked_count": self.blocked_count,
            "avg_duration_ms": self.avg_duration_ms,
        }
