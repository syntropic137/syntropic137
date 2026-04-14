"""Orchestration bounded context - workflow execution and workspace management.

Public API for cross-context consumers. Import from here, not from internal
subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.orchestration import (
        WorkspaceAggregate,
        WorkflowExecutionAggregate,
        CreateWorkspaceCommand,
        ExecuteWorkflowCommand,
    )
"""

from syn_domain.contexts.orchestration.domain import (
    HandlerResult,
    WorkflowExecutionAggregate,
    WorkflowTemplateAggregate,
    WorkspaceAggregate,
)
from syn_domain.contexts.orchestration.domain.commands import (
    CreateWorkflowTemplateCommand,
    CreateWorkspaceCommand,
    ExecuteCommandCommand,
    ExecuteWorkflowCommand,
    InjectTokensCommand,
    TerminateWorkspaceCommand,
    UpdatePhasePromptCommand,
)

__all__ = [
    "CreateWorkflowTemplateCommand",
    "CreateWorkspaceCommand",
    "ExecuteCommandCommand",
    "ExecuteWorkflowCommand",
    "HandlerResult",
    "InjectTokensCommand",
    "TerminateWorkspaceCommand",
    "UpdatePhasePromptCommand",
    "WorkflowExecutionAggregate",
    "WorkflowTemplateAggregate",
    "WorkspaceAggregate",
]
