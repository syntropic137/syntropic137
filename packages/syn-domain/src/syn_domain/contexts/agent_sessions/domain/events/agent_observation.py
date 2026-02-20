"""AgentObservation event - unified telemetry for all agent activities.

This module provides a single event type for all agent observations,
simplifying the observability pipeline and enabling consistent
projection-based cost and metrics calculation.

Architecture Decision:
- All agent telemetry (tokens, tools, operations) flows through this single event type
- CostProjection subscribes directly to these events for cost calculation
- No intermediate transformation required (no CostCalculator indirection)

See: ADR-018 (Commands vs Observations), PROJECT-PLAN_20251215_CONTAINER-OBSERVABILITY.md
"""

from __future__ import annotations

from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Any

from event_sourcing import DomainEvent, event


class ObservationType(str, Enum):
    """Type of agent observation.

    Categorizes raw telemetry from agent execution.
    Unlike OperationType (which tracks granular operations),
    ObservationType captures direct observations from the agent runner.
    """

    # Token usage - per-turn LLM API usage
    TOKEN_USAGE = "token_usage"

    # Tool lifecycle - from SDK hooks
    # Values match syn_shared.events constants (enforced by test_event_type_consistency.py)
    TOOL_EXECUTION_STARTED = "tool_execution_started"  # PreToolUse hook
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"  # PostToolUse hook
    TOOL_BLOCKED = "tool_blocked"  # Safety validation blocked

    # Execution lifecycle - from SDK hooks
    # Values match syn_shared.events constants (enforced by test_event_type_consistency.py)
    USER_PROMPT_SUBMITTED = "user_prompt_submitted"  # UserPromptSubmit hook
    EXECUTION_STOPPED = "execution_stopped"  # Stop hook
    SUBAGENT_STARTED = "subagent_started"  # Task tool spawns subagent (ADR-037)
    SUBAGENT_STOPPED = "subagent_stopped"  # SubagentStop hook / Task completion
    CONTEXT_COMPACTING = "context_compacted"  # PreCompact hook

    # Progress tracking
    PROGRESS = "progress"  # Periodic progress update

    # Session lifecycle
    STARTED = "started"  # Agent execution started
    COMPLETED = "completed"  # Agent execution completed
    ERROR = "error"  # Error occurred
    CANCELLED = "cancelled"  # Execution cancelled


@event("AgentObservation", "v1")
class AgentObservationEvent(DomainEvent):
    """Unified event for all agent observations.

    This event captures all telemetry from agent execution:
    - Token usage (input/output/cache tokens)
    - Tool lifecycle (started/completed/blocked)
    - Execution events (prompts, stops, compaction)
    - Progress updates

    Projections subscribe to this event type to build:
    - Cost projections (from TOKEN_USAGE observations)
    - Tool metrics (from TOOL_* observations)
    - Session timelines (from all observations)

    Design Principles:
    - Single event type for all observations (unified model)
    - Type-specific data in the `data` field (flexible schema)
    - Projections handle type-specific logic (no domain service indirection)

    Version History:
    - v1: Initial unified observation model
    """

    # Identity - which session this observation belongs to
    session_id: str

    # Classification
    observation_type: ObservationType

    # Timing
    timestamp: datetime

    # Type-specific payload
    # For TOKEN_USAGE: {input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, model}
    # For TOOL_EXECUTION_STARTED: {tool_name, tool_use_id, input_preview}
    # For TOOL_EXECUTION_COMPLETED: {tool_name, tool_use_id, success, output_preview, duration_ms}
    # For TOOL_BLOCKED: {tool_name, tool_use_id, reason}
    # For USER_PROMPT_SUBMITTED: {prompt}
    # For EXECUTION_STOPPED: {reason}
    # For SUBAGENT_STOPPED: {subagent}
    # For CONTEXT_COMPACTING: {message_count}
    # For PROGRESS: {turn, total_input_tokens, total_output_tokens}
    # For STARTED/COMPLETED/CANCELLED: {message}
    # For ERROR: {error_type, message, traceback}
    data: dict[str, Any] = field(default_factory=dict)

    # Optional linkage to execution hierarchy
    execution_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None

    # Generic metadata (e.g., agent_model, tags)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": "AgentObservation",
            "session_id": self.session_id,
            "observation_type": self.observation_type.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "data": self.data,
            "execution_id": self.execution_id,
            "phase_id": self.phase_id,
            "workspace_id": self.workspace_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentObservationEvent:
        """Create from dictionary."""
        from datetime import UTC

        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(UTC)

        return cls(
            session_id=data["session_id"],
            observation_type=ObservationType(data["observation_type"]),
            timestamp=timestamp,
            data=data.get("data", {}),
            execution_id=data.get("execution_id"),
            phase_id=data.get("phase_id"),
            workspace_id=data.get("workspace_id"),
            metadata=data.get("metadata", {}),
        )

    # =========================================================================
    # FACTORY METHODS - Create observations for specific types
    # =========================================================================

    @classmethod
    def token_usage(
        cls,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        model: str | None = None,
        *,
        timestamp: datetime | None = None,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AgentObservationEvent:
        """Create a TOKEN_USAGE observation."""
        from datetime import UTC

        return cls(
            session_id=session_id,
            observation_type=ObservationType.TOKEN_USAGE,
            timestamp=timestamp or datetime.now(UTC),
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
                "model": model,
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

    @classmethod
    def tool_started(
        cls,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        input_preview: str | None = None,
        *,
        timestamp: datetime | None = None,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AgentObservationEvent:
        """Create a TOOL_EXECUTION_STARTED observation."""
        from datetime import UTC

        return cls(
            session_id=session_id,
            observation_type=ObservationType.TOOL_EXECUTION_STARTED,
            timestamp=timestamp or datetime.now(UTC),
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "input_preview": input_preview,
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

    @classmethod
    def tool_completed(
        cls,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        success: bool = True,
        output_preview: str | None = None,
        duration_ms: int | None = None,
        *,
        timestamp: datetime | None = None,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AgentObservationEvent:
        """Create a TOOL_EXECUTION_COMPLETED observation."""
        from datetime import UTC

        return cls(
            session_id=session_id,
            observation_type=ObservationType.TOOL_EXECUTION_COMPLETED,
            timestamp=timestamp or datetime.now(UTC),
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "success": success,
                "output_preview": output_preview,
                "duration_ms": duration_ms,
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

    @classmethod
    def tool_blocked(
        cls,
        session_id: str,
        tool_name: str,
        tool_use_id: str,
        reason: str,
        *,
        timestamp: datetime | None = None,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AgentObservationEvent:
        """Create a TOOL_BLOCKED observation."""
        from datetime import UTC

        return cls(
            session_id=session_id,
            observation_type=ObservationType.TOOL_BLOCKED,
            timestamp=timestamp or datetime.now(UTC),
            data={
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "reason": reason,
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

    @classmethod
    def progress(
        cls,
        session_id: str,
        turn: int,
        total_input_tokens: int,
        total_output_tokens: int,
        *,
        timestamp: datetime | None = None,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AgentObservationEvent:
        """Create a PROGRESS observation."""
        from datetime import UTC

        return cls(
            session_id=session_id,
            observation_type=ObservationType.PROGRESS,
            timestamp=timestamp or datetime.now(UTC),
            data={
                "turn": turn,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
            },
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )
