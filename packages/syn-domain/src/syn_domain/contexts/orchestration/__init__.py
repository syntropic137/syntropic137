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
    ArchiveWorkflowTemplateCommand,
    CreateWorkflowTemplateCommand,
    CreateWorkspaceCommand,
    ExecuteCommandCommand,
    ExecuteWorkflowCommand,
    InjectTokensCommand,
    TerminateWorkspaceCommand,
    UpdatePhasePromptCommand,
)
from syn_domain.contexts.orchestration._shared.WorkflowValueObjects import (
    PhaseDefinition,
    PhaseExecutionType,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    validate_workflow_yaml,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ImageManifest,
    IsolationConfig,
    SecurityPolicy,
    SidecarConfig,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.archive_workflow_template.ArchiveWorkflowTemplateHandler import (
    ArchiveWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkflowNotFoundError,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
    SYN_WORKSPACE_PROMPT,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)

__all__ = [
    # Aggregates
    "HandlerResult",
    "WorkflowExecutionAggregate",
    "WorkflowTemplateAggregate",
    "WorkspaceAggregate",
    # Commands
    "ArchiveWorkflowTemplateCommand",
    "CreateWorkflowTemplateCommand",
    "CreateWorkspaceCommand",
    "ExecuteCommandCommand",
    "ExecuteWorkflowCommand",
    "InjectTokensCommand",
    "TerminateWorkspaceCommand",
    "UpdatePhasePromptCommand",
    # Value objects - workflow
    "PhaseDefinition",
    "PhaseExecutionType",
    "WorkflowClassification",
    "WorkflowType",
    "WorkflowDefinition",
    "validate_workflow_yaml",
    # Value objects - workflow template
    "InputDeclaration",
    # Value objects - workspace
    "ImageManifest",
    "IsolationConfig",
    "SecurityPolicy",
    "SidecarConfig",
    # Value objects - execution
    "ExecutablePhase",
    # Handlers
    "ArchiveWorkflowTemplateHandler",
    "CreateWorkflowTemplateHandler",
    "ExecuteWorkflowHandler",
    "UpdateWorkflowPhaseHandler",
    # Errors
    "WorkflowNotFoundError",
    # Query services
    "ExecutionCostQueryService",
    # Constants
    "SYN_WORKSPACE_PROMPT",
    # Test support types (used by syn_domain.testing)
    "AgentExecutionCompletedCommand",
    "AgentExecutionResult",
    "StreamResult",
    "SubagentTracker",
    "TokenAccumulator",
    "WorkflowExecutionProcessor",
]
