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
from syn_domain.contexts.orchestration._shared.eval_admission import (
    EvalUnavailableError,
    launch_eval_for,
    open_eval,
)
from syn_domain.contexts.orchestration._shared.eval_choice import (
    EvalChoice,
    LaunchEval,
    RepositoryOutsideBaselineError,
)
from syn_domain.contexts.orchestration._shared.eval_membership_edit import (
    EvalMembershipResult,
)
from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,
)
from syn_domain.contexts.orchestration._shared.retired_phase_fields import (
    RETIRED_PHASE_FIELDS,
    retired_field_notices,
)
from syn_domain.contexts.orchestration._shared.skill_errors import (
    SkillError,
    SkillInvalidName,
    SkillNotRegistered,
)
from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillRef,
)
from syn_domain.contexts.orchestration._shared.tags import (
    InvalidTagsError,
    TagSet,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PHASE_ID_PATTERN,
    RESERVED_INPUT_NAMES,
    WorkflowDefinition,
    is_phase_id,
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
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalId
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
    ResumeExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.resume_start import (
    refuse_resume_start,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DelegationAttempt,
    DelegationFailure,
    DelegationFailureReason,
    ExecutablePhase,
    ExecutionStatus,
    FailureClassification,
    PhaseUsage,
    QuarantinedRef,
    ReportedFailureReason,
    ReviewVerdict,
    SideEffectStatus,
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
    AddExecutionTagsCommand,
    AddWorkflowTagsCommand,
    ArchiveWorkflowTemplateCommand,
    AttachExecutionToEvalCommand,
    CreateWorkflowTemplateCommand,
    CreateWorkspaceCommand,
    DetachExecutionFromEvalCommand,
    ExecuteCommandCommand,
    ExecuteWorkflowCommand,
    InjectTokensCommand,
    RemoveExecutionTagsCommand,
    RemoveWorkflowTagsCommand,
    SetWorkflowDefaultEvalCommand,
    TerminateWorkspaceCommand,
    UpdatePhasePromptCommand,
    UpdateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.archive_workflow_template.ArchiveWorkflowTemplateHandler import (
    ArchiveWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.attach_execution_to_eval import (
    AttachExecutionToEvalHandler,
)
from syn_domain.contexts.orchestration.slices.create_workflow_template.CreateWorkflowTemplateHandler import (
    CreateWorkflowTemplateHandler,
)
from syn_domain.contexts.orchestration.slices.detach_execution_from_eval import (
    DetachExecutionFromEvalHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AGENT_LAUNCH_MARKER,
    announce_as,
    mint_wrapper_name,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    AttemptClock,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.cancelled_work_record import (
    CancelledWorkLedger,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CredentialRenewalFailedError,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    InheritanceUnavailableError,
    inherited_outputs,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.stranded_salvage import (
    salvage_stranded_phase,
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
from syn_domain.contexts.orchestration.slices.notify_quarantine import (
    PullRequestCommenter,
    QuarantineNoticeProcessManager,
)
from syn_domain.contexts.orchestration.slices.set_workflow_default_eval import (
    SetWorkflowDefaultEvalHandler,
)
from syn_domain.contexts.orchestration.slices.show_claude_plugin import (
    ClaudePluginNotFoundError,
)
from syn_domain.contexts.orchestration.slices.start_resume import (
    MAX_START_ATTEMPTS,
    ResumeStarter,
    ResumeStartProcessManager,
    ResumeStartRecord,
    ResumeStartStatus,
    StartResumeHandler,
    read_record,
)
from syn_domain.contexts.orchestration.slices.tag_execution import (
    AddExecutionTagsHandler,
    RemoveExecutionTagsHandler,
)
from syn_domain.contexts.orchestration.slices.tag_workflow import (
    AddWorkflowTagsHandler,
    RemoveWorkflowTagsHandler,
)
from syn_domain.contexts.orchestration.slices.update_workflow_phase.UpdateWorkflowPhaseHandler import (
    UpdateWorkflowPhaseHandler,
)

__all__ = [
    # Constants
    "AGENT_LAUNCH_MARKER",
    "MAX_START_ATTEMPTS",
    "PHASE_ID_PATTERN",
    "RESERVED_INPUT_NAMES",
    "RETIRED_PHASE_FIELDS",
    # Tag edits after creation (#967)
    "AddExecutionTagsCommand",
    "AddExecutionTagsHandler",
    "AddWorkflowTagsCommand",
    "AddWorkflowTagsHandler",
    # Test support types (used by syn_domain.testing)
    "AgentExecutionCompletedCommand",
    "AgentExecutionResult",
    # A phase's own verdict on itself - the type of `StreamResult.verdict` (#1256)
    "AgentVerdict",
    # Commands
    "ArchiveWorkflowTemplateCommand",
    # Handlers
    "ArchiveWorkflowTemplateHandler",
    "AttachExecutionToEvalCommand",
    "AttachExecutionToEvalHandler",
    # The clock a phase's retry budget is measured on (#1303)
    "AttemptClock",
    # Claude plugin types + errors (issue #726)
    "CancelledWorkLedger",
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
    "CredentialRenewalFailedError",
    "DelegationAttempt",
    "DelegationFailure",
    "DelegationFailureReason",
    "DetachExecutionFromEvalCommand",
    "DetachExecutionFromEvalHandler",
    # Errors
    "DuplicateExecutionError",
    "EvalChoice",
    "EvalId",
    "EvalMembershipResult",
    "EvalUnavailableError",
    # Value objects - execution
    "ExecutablePhase",
    "ExecuteCommandCommand",
    "ExecuteWorkflowCommand",
    "ExecuteWorkflowHandler",
    # Query services
    "ExecutionCostQueryService",
    "ExecutionJournal",
    "ExecutionResumedEvent",
    "ExecutionStatus",
    "FailExecutionCommand",
    "FailureClassification",
    "GlobalClaudePluginEntry",
    "GlobalClaudePluginNotFoundError",
    # Aggregates
    "HandlerResult",
    # Value objects - workspace
    "ImageManifest",
    "InheritanceUnavailableError",
    "InjectTokensCommand",
    # Value objects - workflow template
    "InputDeclaration",
    "InvalidTagsError",
    "IsolationConfig",
    "LaunchEval",
    # Value objects - workflow
    "PhaseDefinition",
    "PhaseExecutionType",
    # What a phase spent, as the failure path reports it (#1262)
    "PhaseUsage",
    "PullRequestCommenter",
    "QuarantineNoticeProcessManager",
    "QuarantinedRef",
    "RemoveExecutionTagsCommand",
    "RemoveExecutionTagsHandler",
    "RemoveWorkflowTagsCommand",
    "RemoveWorkflowTagsHandler",
    "ReportedFailureReason",
    "RepositoryOutsideBaselineError",
    "ResolvedClaudePlugin",
    "ResolvedSkill",
    "ResumeExecutionCommand",
    "ResumeStartProcessManager",
    "ResumeStartRecord",
    "ResumeStartStatus",
    "ResumeStarter",
    "ReviewVerdict",
    "SecurityPolicy",
    "SetWorkflowDefaultEvalCommand",
    "SetWorkflowDefaultEvalHandler",
    "SideEffectStatus",
    "SidecarConfig",
    "SkillError",
    "SkillInvalidName",
    "SkillNotRegistered",
    "SkillRef",
    "StartResumeHandler",
    "StreamResult",
    "SubagentTracker",
    "TagSet",
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
    "WorkflowExecutionStartedEvent",
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
    "inherited_outputs",
    "is_phase_id",
    "launch_eval_for",
    "mint_wrapper_name",
    "open_eval",
    "read_record",
    "refuse_resume_start",
    "render_workspace_prompt",
    "require_supported_execution_type",
    "retired_field_notices",
    "salvage_stranded_phase",
    "validate_phase_declarations",
    "validate_workflow_yaml",
]
