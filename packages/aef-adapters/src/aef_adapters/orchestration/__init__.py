"""Orchestration layer for agentic workflow execution.

This module provides the unified WorkflowExecutor which orchestrates
workflow execution using the AgenticProtocol with required observability:

- Multi-turn agent execution with tool use
- Isolated workspace per phase (via WorkspaceService)
- Artifact bundles for phase-to-phase context
- REQUIRED ObservabilityPort for telemetry (Poka-Yoke pattern)

Example (recommended):
    from aef_adapters.orchestration import create_workflow_executor

    # Factory handles DI wiring
    executor = create_workflow_executor(
        workspace_service=workspace_service,
    )

    async for event in executor.execute(workflow, inputs):
        print(f"Event: {event}")

Legacy (deprecated):
    AgenticWorkflowExecutor is deprecated. Use WorkflowExecutor instead.

See:
- ADR-021: Isolated Workspace Architecture
- ADR-027: Unified Workflow Executor Architecture (M8)
"""

from aef_adapters.orchestration.executor import (
    AgenticWorkflowExecutor,  # Deprecated: use WorkflowExecutor
    ExecutionCancelled,
    ExecutionEvent,
    ExecutionPaused,
    ExecutionResumed,
    PhaseCompleted,
    PhaseFailed,
    PhaseStarted,
    ToolBlockedExecution,
    ToolStarted,
    ToolUsed,
    TurnUpdate,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowStarted,
)
from aef_adapters.orchestration.factory import (
    AgenticAgentFactory,
    WorkspaceFactory,
    create_workflow_executor,
    execute_in_workspace,
    get_agentic_agent,
    get_workspace,
    get_workspace_local,
)
from aef_adapters.orchestration.workflow_executor import WorkflowExecutor

__all__ = [
    # Factories
    "AgenticAgentFactory",
    # Legacy (deprecated)
    "AgenticWorkflowExecutor",
    # Execution Events
    "ExecutionCancelled",
    "ExecutionEvent",
    "ExecutionPaused",
    "ExecutionResumed",
    "PhaseCompleted",
    "PhaseFailed",
    "PhaseStarted",
    "ToolBlockedExecution",
    "ToolStarted",
    "ToolUsed",
    "TurnUpdate",
    "WorkflowCompleted",
    # Unified Executor (M8 - recommended)
    "WorkflowExecutor",
    "WorkflowFailed",
    "WorkflowStarted",
    "WorkspaceFactory",
    "create_workflow_executor",
    "execute_in_workspace",
    "get_agentic_agent",
    "get_workspace",
    "get_workspace_local",
]
