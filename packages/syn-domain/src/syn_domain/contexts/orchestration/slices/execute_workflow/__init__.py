"""Execute workflow vertical slice.

This slice handles the execution of workflows, including:
- Starting workflow execution
- Managing phase execution lifecycle
- Tracking execution state and metrics
"""

from syn_domain.contexts.orchestration.domain.commands import ExecuteWorkflowCommand
from syn_domain.contexts.orchestration.domain.events import (
    ExecutionCancelledEvent,
    ExecutionPausedEvent,
    ExecutionResumedEvent,
    PhaseCompletedEvent,
    PhaseStartedEvent,
    WorkflowCompletedEvent,
    WorkflowExecutionStartedEvent,
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionEngine import (
    WorkflowExecutionEngine,
    WorkflowExecutionResult,
)

__all__ = [
    "ExecuteWorkflowCommand",
    "ExecutionCancelledEvent",
    "ExecutionPausedEvent",
    "ExecutionResumedEvent",
    "PhaseCompletedEvent",
    "PhaseStartedEvent",
    "WorkflowCompletedEvent",
    "WorkflowExecutionEngine",
    "WorkflowExecutionResult",
    "WorkflowExecutionStartedEvent",
    "WorkflowFailedEvent",
]
