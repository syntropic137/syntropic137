"""Orchestration layer for agentic workflow execution.

This module provides the AgenticWorkflowExecutor which orchestrates
workflow execution using the new AgenticProtocol:

- Multi-turn agent execution with tool use
- Isolated workspace per phase (via WorkspaceRouter)
- Artifact bundles for phase-to-phase context
- Hook event integration via EventBridge

Example:
    from aef_adapters.orchestration import (
        AgenticWorkflowExecutor,
        get_agentic_agent,
        get_workspace,
    )

    # Create executor with isolated workspace factory
    executor = AgenticWorkflowExecutor(
        agent_factory=get_agentic_agent,
        workspace_factory=get_workspace,
    )

    async for event in executor.execute(workflow, inputs):
        print(f"Event: {event}")

See ADR-021: Isolated Workspace Architecture
"""

from aef_adapters.orchestration.executor import (
    AgenticWorkflowExecutor,
    ExecutionEvent,
    PhaseCompleted,
    PhaseFailed,
    PhaseStarted,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowStarted,
)
from aef_adapters.orchestration.factory import (
    AgenticAgentFactory,
    WorkspaceFactory,
    execute_in_workspace,
    get_agentic_agent,
    get_workspace,
    get_workspace_local,
)

__all__ = [
    "AgenticAgentFactory",
    "AgenticWorkflowExecutor",
    "ExecutionEvent",
    "PhaseCompleted",
    "PhaseFailed",
    "PhaseStarted",
    "WorkflowCompleted",
    "WorkflowFailed",
    "WorkflowStarted",
    "WorkspaceFactory",
    "execute_in_workspace",
    "get_agentic_agent",
    "get_workspace",
    "get_workspace_local",
]
