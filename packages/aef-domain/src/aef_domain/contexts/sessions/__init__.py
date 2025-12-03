"""Sessions bounded context - tracks agent execution sessions.

This context provides aggregates, commands, and events for tracking
agent sessions including token usage, operations, and costs.

Usage:
    from aef_domain.contexts.sessions import (
        AgentSessionAggregate,
        StartSessionCommand,
        RecordOperationCommand,
        CompleteSessionCommand,
    )

    # Create session
    session = AgentSessionAggregate()
    session.start_session(StartSessionCommand(
        workflow_id="wf-123",
        phase_id="research",
        agent_provider="claude",
    ))

    # Record operations
    session.record_operation(RecordOperationCommand(
        aggregate_id=str(session.id),
        operation_type=OperationType.AGENT_REQUEST,
        total_tokens=1000,
    ))

    # Complete session
    session.complete_session(CompleteSessionCommand(
        aggregate_id=str(session.id),
        success=True,
    ))
"""

from aef_domain.contexts.sessions._shared import (
    AgentSessionAggregate,
    CostMetrics,
    OperationRecord,
    OperationType,
    SessionStatus,
    TokenMetrics,
)
from aef_domain.contexts.sessions.complete_session import (
    CompleteSessionCommand,
    SessionCompletedEvent,
)
from aef_domain.contexts.sessions.record_operation import (
    OperationRecordedEvent,
    RecordOperationCommand,
)
from aef_domain.contexts.sessions.start_session import (
    SessionStartedEvent,
    StartSessionCommand,
)

__all__ = [
    "AgentSessionAggregate",
    "CompleteSessionCommand",
    "CostMetrics",
    "OperationRecord",
    "OperationRecordedEvent",
    "OperationType",
    "RecordOperationCommand",
    "SessionCompletedEvent",
    "SessionStartedEvent",
    "SessionStatus",
    "StartSessionCommand",
    "TokenMetrics",
]
