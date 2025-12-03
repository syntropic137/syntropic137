"""Orchestration layer for agentic workflow execution.

This module provides the AgenticWorkflowExecutor which orchestrates
workflow execution using the new AgenticProtocol:

- Multi-turn agent execution with tool use
- Workspace isolation per phase
- Artifact bundles for phase-to-phase context
- Hook event integration via EventBridge

Example:
    from aef_adapters.orchestration import AgenticWorkflowExecutor
    from aef_adapters.agents import ClaudeAgenticAgent
    from aef_adapters.workspaces import LocalWorkspace

    executor = AgenticWorkflowExecutor(
        agent=ClaudeAgenticAgent(),
        workspace_factory=LocalWorkspace.create,
    )

    async for event in executor.execute(workflow, inputs):
        print(f"Event: {event}")
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
    get_agentic_agent,
    get_workspace,
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
    "get_agentic_agent",
    "get_workspace",
]
