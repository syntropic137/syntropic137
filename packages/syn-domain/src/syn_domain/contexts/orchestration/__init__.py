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
    ClaudePluginVersionHashMismatch,
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
    RESERVED_INPUT_NAMES,
    WorkflowDefinition,
    validate_workflow_yaml,
)
from syn_domain.contexts.orchestration._shared.WorkflowValueObjects import (
    PhaseDefinition,
    PhaseExecutionType,
    UnsupportedExecutionTypeError,
    WorkflowClassification,
    WorkflowType,
    require_supported_execution_type,
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
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionStatus,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
    announce_as,
    mint_wrapper_name,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DuplicateExecutionError,
    UnsupportedToolPolicyForProviderError,
    WorkflowNotFoundError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
    validate_phase_declarations,
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
    render_workspace_prompt,
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
    "AGENT_LAUNCH_MARKER",
    "RESERVED_INPUT_NAMES",
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
    "ClaudePluginVersionHashMismatch",
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
    "ExecutionStatus",
    "FailExecutionCommand",
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
    "UnsupportedExecutionTypeError",
    "UnsupportedToolPolicyForProviderError",
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
    "announce_as",
    "build_command_from_definition",
    "mint_wrapper_name",
    "render_workspace_prompt",
    "require_supported_execution_type",
    "validate_phase_declarations",
    "validate_workflow_yaml",
]
