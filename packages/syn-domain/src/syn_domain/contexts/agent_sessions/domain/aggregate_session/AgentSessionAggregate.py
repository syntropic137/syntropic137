"""AgentSession aggregate root - tracks agent execution sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.agent_sessions._shared.value_objects import (
    OperationRecord,
    SessionStatus,
    TokenMetrics,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.commands.CompleteSessionCommand import (
        CompleteSessionCommand,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.RecordOperationCommand import (
        RecordOperationCommand,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )
    from syn_domain.contexts.agent_sessions.domain.events.OperationRecordedEvent import (
        OperationRecordedEvent,
    )
    from syn_domain.contexts.agent_sessions.domain.events.SessionCompletedEvent import (
        SessionCompletedEvent,
    )
    from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import (
        SessionStartedEvent,
    )


@aggregate("AgentSession")
class AgentSessionAggregate(AggregateRoot["SessionStartedEvent"]):
    """AgentSession aggregate root.

    Tracks an agent execution session including:
    - Token usage and costs
    - Operations performed (requests, tool executions)
    - Session lifecycle (running, completed, failed)

    Uses event sourcing to track all state changes.
    """

    # Type hint for decorator-set attribute
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._workflow_id: str | None = None
        self._execution_id: str | None = None
        self._phase_id: str | None = None
        self._milestone_id: str | None = None
        self._agent_provider: str | None = None
        self._agent_model: str | None = None
        self._status: SessionStatus = SessionStatus.RUNNING
        self._tokens: TokenMetrics = TokenMetrics()
        self._operations: list[OperationRecord] = []
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._metadata: dict[str, str | int | float | bool | None] = {}

    def get_aggregate_type(self) -> str:
        """Return aggregate type name."""
        return self._aggregate_type

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def workflow_id(self) -> str | None:
        """Get the workflow ID this session belongs to."""
        return self._workflow_id

    @property
    def phase_id(self) -> str | None:
        """Get the phase ID within the workflow."""
        return self._phase_id

    @property
    def status(self) -> SessionStatus:
        """Get session status."""
        return self._status

    @property
    def tokens(self) -> TokenMetrics:
        """Get accumulated token metrics."""
        return self._tokens

    @property
    def operations(self) -> list[OperationRecord]:
        """Get list of recorded operations."""
        return list(self._operations)

    @property
    def operation_count(self) -> int:
        """Get number of operations recorded."""
        return len(self._operations)

    @property
    def duration_seconds(self) -> float | None:
        """Get session duration in seconds."""
        if self._started_at is None:
            return None
        end = self._completed_at or datetime.now(UTC)
        return (end - self._started_at).total_seconds()

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("StartSessionCommand")
    def start_session(self, command: StartSessionCommand) -> None:
        """Handle StartSessionCommand.

        Creates a new session for tracking agent execution.
        """
        from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import (
            SessionStartedEvent,
        )

        # Validate: session must not already exist
        if self.id is not None:
            msg = "Session already exists"
            raise ValueError(msg)

        # Generate ID if not provided
        session_id = command.aggregate_id or str(uuid4())

        # Initialize aggregate
        self._initialize(session_id)

        # Create and apply event
        event = SessionStartedEvent(
            session_id=session_id,
            workflow_id=command.workflow_id,
            execution_id=command.execution_id,
            phase_id=command.phase_id,
            milestone_id=command.milestone_id,
            agent_provider=command.agent_provider,
            agent_model=command.agent_model,
            started_at=datetime.now(UTC),
            metadata=command.metadata or {},
        )

        self._apply(event)

    @command_handler("RecordOperationCommand")
    def record_operation(self, command: RecordOperationCommand) -> None:
        """Handle RecordOperationCommand.

        Records an operation (message, tool call, thinking, etc.).
        Supports full observability with type-specific fields.
        """
        from syn_domain.contexts.agent_sessions.domain.events.OperationRecordedEvent import (
            OperationRecordedEvent,
        )

        # Validate: session must be running
        if self._status != SessionStatus.RUNNING:
            msg = f"Cannot record operation: session is {self._status.value}"
            raise ValueError(msg)

        # Generate operation ID
        operation_id = str(uuid4())

        # Create and apply event with all fields
        event = OperationRecordedEvent(
            session_id=str(self.id),
            operation_id=operation_id,
            operation_type=command.operation_type,
            timestamp=datetime.now(UTC),
            duration_seconds=command.duration_seconds,
            success=command.success,
            # Token metrics
            input_tokens=command.input_tokens,
            output_tokens=command.output_tokens,
            cache_creation_tokens=command.cache_creation_tokens,
            cache_read_tokens=command.cache_read_tokens,
            total_tokens=command.total_tokens,
            # Tool details
            tool_name=command.tool_name,
            tool_use_id=command.tool_use_id,
            tool_input=command.tool_input,
            tool_output=command.tool_output,
            # Message details
            message_role=command.message_role,
            message_content=command.message_content,
            # Thinking details
            thinking_content=command.thinking_content,
            # Metadata
            metadata=command.metadata or {},
        )

        self._apply(event)

    @command_handler("CompleteSessionCommand")
    def complete_session(self, command: CompleteSessionCommand) -> None:
        """Handle CompleteSessionCommand.

        Marks the session as completed (or failed).
        """
        from syn_domain.contexts.agent_sessions.domain.events.SessionCompletedEvent import (
            SessionCompletedEvent,
        )

        # Validate: session must be running
        if self._status != SessionStatus.RUNNING:
            msg = f"Cannot complete session: session is {self._status.value}"
            raise ValueError(msg)

        # Determine final status (explicit override takes precedence)
        if command.final_status is not None:
            status = command.final_status
        else:
            status = SessionStatus.COMPLETED if command.success else SessionStatus.FAILED

        # Create and apply event
        event = SessionCompletedEvent(
            session_id=str(self.id),
            status=status,
            completed_at=datetime.now(UTC),
            total_input_tokens=self._tokens.input_tokens,
            total_output_tokens=self._tokens.output_tokens,
            total_cache_creation_tokens=self._tokens.cache_creation_tokens,
            total_cache_read_tokens=self._tokens.cache_read_tokens,
            total_tokens=self._tokens.total_tokens,
            operation_count=len(self._operations),
            error_message=command.error_message,
        )

        self._apply(event)

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("SessionStarted")
    def on_session_started(self, event: SessionStartedEvent) -> None:
        """Apply SessionStartedEvent."""
        self._workflow_id = event.workflow_id
        self._execution_id = event.execution_id
        self._phase_id = event.phase_id
        self._milestone_id = event.milestone_id
        self._agent_provider = event.agent_provider
        self._agent_model = event.agent_model
        self._status = SessionStatus.RUNNING
        self._started_at = event.started_at
        self._metadata = dict(event.metadata)

    @event_sourcing_handler("OperationRecorded")
    def on_operation_recorded(self, event: OperationRecordedEvent) -> None:
        """Apply OperationRecordedEvent.

        Handles both v1 and v2 events for backward compatibility.
        New fields default to None if not present in older events.
        """
        # Create token metrics if available
        tokens = None
        if event.total_tokens:
            tokens = TokenMetrics(
                input_tokens=event.input_tokens or 0,
                output_tokens=event.output_tokens or 0,
                cache_creation_tokens=event.cache_creation_tokens or 0,
                cache_read_tokens=event.cache_read_tokens or 0,
            )
            # Update accumulated tokens
            self._tokens = self._tokens + tokens

        # Create operation record with all fields (new fields default to None for v1 events)
        operation = OperationRecord(
            operation_id=event.operation_id,
            operation_type=event.operation_type,
            timestamp=event.timestamp,
            duration_seconds=event.duration_seconds,
            tokens=tokens,
            success=event.success,
            # Tool details
            tool_name=event.tool_name,
            tool_use_id=getattr(event, "tool_use_id", None),
            tool_input=getattr(event, "tool_input", None),
            tool_output=getattr(event, "tool_output", None),
            # Message details
            message_role=getattr(event, "message_role", None),
            message_content=getattr(event, "message_content", None),
            # Thinking details
            thinking_content=getattr(event, "thinking_content", None),
            # Metadata
            metadata=dict(event.metadata),
        )
        self._operations.append(operation)

    @event_sourcing_handler("SessionCompleted")
    def on_session_completed(self, event: SessionCompletedEvent) -> None:
        """Apply SessionCompletedEvent."""
        self._status = event.status
        self._completed_at = event.completed_at
        # Final token values are stored in event for consistency (cost is Lane 2, #695)
        self._tokens = TokenMetrics(
            input_tokens=event.total_input_tokens,
            output_tokens=event.total_output_tokens,
            cache_creation_tokens=getattr(event, "total_cache_creation_tokens", 0) or 0,
            cache_read_tokens=getattr(event, "total_cache_read_tokens", 0) or 0,
        )
