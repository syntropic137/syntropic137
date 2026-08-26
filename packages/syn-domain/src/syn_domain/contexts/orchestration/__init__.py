"""Orchestration bounded context - workflow execution and workspace management.

Public API for cross-context consumers (ADR-062). Import from here, not from
internal subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.orchestration import (
        WorkspaceAggregate,
        WorkflowExecutionAggregate,
        CreateWorkspaceCommand,
        ExecuteWorkflowCommand,
    )
"""

from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginError,
    ClaudePluginInvalidName,
    ClaudePluginInvalidPath,
    ClaudePluginManifestInvalid,
    ClaudePluginManifestMissing,
    ClaudePluginNotRegistered,
)
from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
    ClaudePluginRef,
)
from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,
)
from syn_domain.contexts.orchestration._shared.skill_errors import (
    SkillError,
    SkillInvalidName,
    SkillNotRegistered,
)
from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
    validate_workflow_yaml,
)
from syn_domain.contexts.orchestration._shared.WorkflowValueObjects import (
    PhaseDefinition,
    PhaseExecutionType,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain import (
    HandlerResult,
    WorkflowExecutionAggregate,
    WorkflowTemplateAggregate,
    WorkspaceAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.errors import (
    WorkflowTemplateConflictError,
    WorkflowTemplateDigestMismatchError,
    WorkflowTemplateProvenanceStrippedError,
    WorkflowTemplateVersionAlreadyInstalledError,
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
from syn_domain.contexts.orchestration.domain.commands import (
    ArchiveWorkflowTemplateCommand,
    CreateWorkflowTemplateCommand,
    CreateWorkspaceCommand,
    ExecuteCommandCommand,
    ExecuteWorkflowCommand,
    InjectTokensCommand,
    TerminateWorkspaceCommand,
    UpdatePhasePromptCommand,
    UpdateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.slices.archive_workflow_template.ArchiveWorkflowTemplateHandler import (
    ArchiveWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DuplicateExecutionError,
    WorkflowNotFoundError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
    SYN_WORKSPACE_PROMPT,
)
from syn_domain.contexts.orchestration.slices.execution_cost.query_service import (
    ExecutionCostQueryService,
)
from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins import (
    GlobalClaudePluginEntry,
    GlobalClaudePluginNotFoundError,
)
from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
    ClaudePluginNotFoundError,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)

__all__ = [
    # Constants
    "SYN_WORKSPACE_PROMPT",
    # Test support types (used by syn_domain.testing)
    "AgentExecutionCompletedCommand",
    "AgentExecutionResult",
    # Commands
    "ArchiveWorkflowTemplateCommand",
    # Handlers
    "ArchiveWorkflowTemplateHandler",
    # Claude plugin types + errors (issue #726)
    "ClaudePluginError",
    "ClaudePluginInvalidName",
    "ClaudePluginInvalidPath",
    "ClaudePluginManifestInvalid",
    "ClaudePluginManifestMissing",
    "ClaudePluginNotFoundError",
    "ClaudePluginNotRegistered",
    "ClaudePluginRef",
    "CreateWorkflowTemplateCommand",
    "CreateWorkflowTemplateHandler",
    "CreateWorkspaceCommand",
    # Errors
    "DuplicateExecutionError",
    # Value objects - execution
    "ExecutablePhase",
    "ExecuteCommandCommand",
    "ExecuteWorkflowCommand",
    "ExecuteWorkflowHandler",
    # Query services
    "ExecutionCostQueryService",
    "GlobalClaudePluginEntry",
    "GlobalClaudePluginNotFoundError",
    # Aggregates
    "HandlerResult",
    # Value objects - workspace
    "ImageManifest",
    "InjectTokensCommand",
    # Value objects - workflow template
    "InputDeclaration",
    "IsolationConfig",
    # Value objects - workflow
    "PhaseDefinition",
    "PhaseExecutionType",
    "ResolvedClaudePlugin",
    "ResolvedSkill",
    "SecurityPolicy",
    "SidecarConfig",
    "SkillError",
    "SkillInvalidName",
    "SkillNotRegistered",
    "SkillRef",
    "StreamResult",
    "SubagentTracker",
    "TerminateWorkspaceCommand",
    "TokenAccumulator",
    "UpdatePhasePromptCommand",
    "UpdateWorkflowPhaseHandler",
    "UpdateWorkflowTemplateCommand",
    "WorkflowClassification",
    "WorkflowDefinition",
    "WorkflowExecutionAggregate",
    "WorkflowExecutionProcessor",
    # Errors
    "WorkflowNotFoundError",
    "WorkflowTemplateAggregate",
    "WorkflowTemplateConflictError",
    "WorkflowTemplateDigestMismatchError",
    "WorkflowTemplateProvenanceStrippedError",
    "WorkflowTemplateVersionAlreadyInstalledError",
    "WorkflowType",
    "WorkspaceAggregate",
    "build_command_from_definition",
    "validate_workflow_yaml",
]
