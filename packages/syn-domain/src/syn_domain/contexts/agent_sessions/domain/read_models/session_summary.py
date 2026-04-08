"""Read model for session list views."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SubagentRecord:
    """Record of a subagent spawned during a session.

    Subagents are spawned via the Task tool and run as nested agents.
    The subagent_tool_use_id correlates events to this subagent.
    """

    subagent_tool_use_id: str
    """The Task tool_use_id - unique identifier for this subagent."""

    agent_name: str
    """Name/description of the subagent from Task input."""

    started_at: str | datetime | None = None
    """When the subagent was spawned."""

    stopped_at: str | datetime | None = None
    """When the subagent completed."""

    duration_ms: int | None = None
    """Execution duration in milliseconds."""

    tools_used: dict[str, int] = field(default_factory=dict)
    """Tools used by this subagent: {tool_name: count}."""

    success: bool = True
    """Whether the subagent completed successfully."""

    @classmethod
    def from_dict(cls, data: dict) -> "SubagentRecord":
        """Create from dictionary."""
        return cls(
            subagent_tool_use_id=data.get("subagent_tool_use_id", ""),
            agent_name=data.get("agent_name", ""),
            started_at=data.get("started_at"),
            stopped_at=data.get("stopped_at"),
            duration_ms=data.get("duration_ms"),
            tools_used=data.get("tools_used", {}),
            success=data.get("success", True),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        started = self.started_at
        if isinstance(started, datetime):
            started = started.isoformat()
        stopped = self.stopped_at
        if isinstance(stopped, datetime):
            stopped = stopped.isoformat()
        return {
            "subagent_tool_use_id": self.subagent_tool_use_id,
            "agent_name": self.agent_name,
            "started_at": started,
            "stopped_at": stopped,
            "duration_ms": self.duration_ms,
            "tools_used": self.tools_used,
            "success": self.success,
        }


@dataclass(frozen=True)
class OperationRecord:
    """Individual operation recorded during a session.

    Supports multiple operation types for full observability:
    - MESSAGE_REQUEST/RESPONSE: LLM API calls
    - TOOL_EXECUTION_STARTED/COMPLETED/BLOCKED: Tool lifecycle
    - THINKING: Extended thinking content
    - ERROR: Error information
    """

    operation_id: str
    operation_type: str
    timestamp: str | datetime | None
    duration_seconds: float | None = None
    success: bool = True

    # Token metrics (for MESSAGE_* types)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool details (for TOOL_* types)
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None

    # Message details (for MESSAGE_* types)
    message_role: str | None = None
    message_content: str | None = None

    # Thinking details (for THINKING type)
    thinking_content: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OperationRecord":
        """Create from dictionary. Handles both v1 and v2 event formats."""
        return cls(
            operation_id=data.get("operation_id", ""),
            operation_type=data.get("operation_type", ""),
            timestamp=data.get("timestamp"),
            duration_seconds=data.get("duration_seconds"),
            success=data.get("success", True),
            # Token metrics
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            total_tokens=data.get("total_tokens"),
            # Tool details
            tool_name=data.get("tool_name"),
            tool_use_id=data.get("tool_use_id"),
            tool_input=data.get("tool_input"),
            tool_output=data.get("tool_output"),
            # Message details
            message_role=data.get("message_role"),
            message_content=data.get("message_content"),
            # Thinking details
            thinking_content=data.get("thinking_content"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        ts = self.timestamp
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "timestamp": ts,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            # Token metrics
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            # Tool details
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            # Message details
            "message_role": self.message_role,
            "message_content": self.message_content,
            # Thinking details
            "thinking_content": self.thinking_content,
        }


@dataclass(frozen=True)
class SessionSummary:
    """Read model for session list view.

    This is a lightweight DTO optimized for listing sessions.
    """

    id: str
    """Unique identifier for the session."""

    workflow_id: str
    """ID of the workflow this session belongs to."""

    agent_type: str
    """Type of agent used in this session."""

    status: str
    """Current status (pending, in_progress, completed, failed)."""

    total_tokens: int
    """Total tokens used in this session."""

    total_cost_usd: Decimal
    """Total cost in USD for this session."""

    started_at: datetime | None
    """When the session started."""

    completed_at: datetime | None
    """When the session completed (if completed)."""

    # Enhanced fields for detailed metrics
    input_tokens: int = 0
    """Input tokens used in this session."""

    output_tokens: int = 0
    """Output tokens used in this session."""

    duration_seconds: float | None = None
    """Duration of the session in seconds."""

    phase_id: str | None = None
    """ID of the phase this session belongs to."""

    execution_id: str | None = None
    """ID of the workflow execution/run this session belongs to."""

    operations: tuple[OperationRecord, ...] = ()
    """Operations recorded during this session."""

    # Subagent metrics (from agentic_isolation v0.3.0)
    subagent_count: int = 0
    """Number of subagents spawned during this session."""

    subagents: tuple[SubagentRecord, ...] = ()
    """Records of subagents spawned during this session."""

    tools_by_subagent: dict[str, dict[str, int]] = field(default_factory=dict)
    """Aggregated tool usage per subagent: {subagent_name: {tool_name: count}}."""

    # Enhanced metrics from result event
    num_turns: int = 0
    """Number of conversation turns."""

    duration_api_ms: int | None = None
    """API latency in milliseconds (from result event)."""

    error_message: str | None = None
    """Error message if the session failed."""

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSummary":
        """Create from dictionary data."""
        # Parse operations list
        ops_data = data.get("operations", [])
        operations = tuple(OperationRecord.from_dict(op) for op in ops_data)

        # Parse subagents list
        subagents_data = data.get("subagents", [])
        subagents = tuple(SubagentRecord.from_dict(s) for s in subagents_data)

        return cls(
            id=data["id"],
            workflow_id=data["workflow_id"],
            agent_type=data.get("agent_type", ""),
            status=data.get("status", "pending"),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=Decimal(str(data.get("total_cost_usd", 0))),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            duration_seconds=data.get("duration_seconds"),
            phase_id=data.get("phase_id"),
            execution_id=data.get("execution_id"),
            operations=operations,
            # Subagent metrics
            subagent_count=data.get("subagent_count", 0),
            subagents=subagents,
            tools_by_subagent=data.get("tools_by_subagent", {}),
            # Enhanced metrics
            num_turns=data.get("num_turns", 0),
            duration_api_ms=data.get("duration_api_ms"),
            error_message=data.get("error_message"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        # Handle both datetime objects and ISO string format
        # (events from event store come back as strings after serialization)
        started_at_str = None
        if self.started_at:
            started_at_str = (
                self.started_at.isoformat()
                if isinstance(self.started_at, datetime)
                else str(self.started_at)
            )

        completed_at_str = None
        if self.completed_at:
            completed_at_str = (
                self.completed_at.isoformat()
                if isinstance(self.completed_at, datetime)
                else str(self.completed_at)
            )

        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "total_tokens": self.total_tokens,
            "total_cost_usd": str(self.total_cost_usd),
            "started_at": started_at_str,
            "completed_at": completed_at_str,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_seconds": self.duration_seconds,
            "phase_id": self.phase_id,
            "execution_id": self.execution_id,
            "operations": [op.to_dict() for op in self.operations],
            # Subagent metrics
            "subagent_count": self.subagent_count,
            "subagents": [s.to_dict() for s in self.subagents],
            "tools_by_subagent": self.tools_by_subagent,
            # Enhanced metrics
            "num_turns": self.num_turns,
            "duration_api_ms": self.duration_api_ms,
            "error_message": self.error_message,
        }
