"""Sessions bounded context - tracks agent execution sessions.

Public API for cross-context consumers (ADR-062). This context provides
aggregates, commands, and events for tracking agent sessions including
token usage and operations. Cost is Lane 2 telemetry — use
``SessionCostQueryService`` for per-session cost (#695).

Usage:
    from syn_domain.contexts.agent_sessions import (
        AgentSessionAggregate,
        StartSessionCommand,
        CompleteSessionCommand,
        # Convenience functions for recording operations
        record_tool_started,
        record_tool_completed,
        record_message_response,
    )

    # Create session
    session = AgentSessionAggregate()
    session.start_session(StartSessionCommand(
        workflow_id="wf-123",
        phase_id="research",
        agent_provider="claude",
    ))

    # Record tool operations (type-safe convenience functions)
    cmd = record_tool_started(str(session.id), "Read", "tool-123", {"path": "/foo"})
    session.record_operation(cmd)

    cmd = record_tool_completed(str(session.id), "Read", "tool-123", "file contents...")
    session.record_operation(cmd)

    # Complete session
    session.complete_session(CompleteSessionCommand(
        aggregate_id=str(session.id),
        success=True,
    ))
"""

from syn_domain.contexts.agent_sessions._shared import (
    AgentSessionAggregate,
    OperationRecord,
    OperationType,
    SessionStatus,
    TokenMetrics,
)
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.agent_sessions.slices.complete_session import (
    CompleteSessionCommand,
    SessionCompletedEvent,
)
from syn_domain.contexts.agent_sessions.slices.complete_session.CompleteSessionHandler import (
    CompleteSessionHandler,
)
from syn_domain.contexts.agent_sessions.slices.record_operation import (
    OperationRecordedEvent,
    RecordOperationCommand,
    # Convenience factory functions
    record_error,
    record_message_request,
    record_message_response,
    record_thinking,
    record_tool_blocked,
    record_tool_completed,
    record_tool_started,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.start_session import (
    SessionStartedEvent,
    StartSessionCommand,
)
from syn_domain.contexts.agent_sessions.slices.start_session.StartSessionHandler import (
    StartSessionHandler,
)

__all__ = [
    "AgentSessionAggregate",
    "CompleteSessionCommand",
    "CompleteSessionHandler",
    "CostCalculator",
    "ObservationType",
    "OperationRecord",
    "OperationRecordedEvent",
    "OperationType",
    "RecordOperationCommand",
    "SessionCompletedEvent",
    "SessionCostQueryService",
    "SessionStartedEvent",
    "SessionStatus",
    "StartSessionCommand",
    "StartSessionHandler",
    "TokenMetrics",
    "record_error",
    "record_message_request",
    "record_message_response",
    "record_thinking",
    "record_tool_blocked",
    "record_tool_completed",
    "record_tool_started",
]
