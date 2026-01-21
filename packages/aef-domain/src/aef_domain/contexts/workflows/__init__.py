"""Workflows bounded context - workflow management and execution."""

from aef_domain.contexts.workflows._shared import (
    AgentConfiguration,
    ArtifactSummary,
    ArtifactUploadResult,
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseDefinition,
    PhaseExecutionType,
    PhaseInput,
    PhaseResult,
    PhaseStatus,
    SessionContext,
    WorkflowAggregate,
    WorkflowClassification,
    WorkflowDefinition,
    WorkflowType,
    load_workflow_definitions,
    validate_workflow_yaml,
)
from aef_domain.contexts.workflows.ports import (
    AgentFactoryPort,
    ArtifactContentStoragePort,
    ArtifactQueryServicePort,
    ArtifactRepositoryPort,
    ConversationStoragePort,
    ObservabilityServicePort,
    SessionRepositoryPort,
    WorkflowExecutionRepositoryPort,
    WorkflowRepositoryPort,
    WorkspaceServicePort,
)
from aef_domain.contexts.workflows.seed_workflow import (
    SeedReport,
    SeedResult,
    WorkflowSeeder,
)
from aef_domain.contexts.workflows.slices.execute_workflow import (
    ExecuteWorkflowCommand,
    PhaseCompletedEvent,
    PhaseStartedEvent,
    WorkflowCompletedEvent,
    WorkflowExecutionEngine,
    WorkflowExecutionResult,
    WorkflowExecutionStartedEvent,
    WorkflowFailedEvent,
)

__all__ = [
    # Value Objects & Aggregates
    "AgentConfiguration",
    # Ports (NEW in M1)
    "AgentFactoryPort",
    "ArtifactContentStoragePort",
    "ArtifactQueryServicePort",
    "ArtifactRepositoryPort",
    "ArtifactSummary",
    "ArtifactUploadResult",
    "ConversationStoragePort",
    "ExecutablePhase",
    # Commands
    "ExecuteWorkflowCommand",
    "ExecutionMetrics",
    "ExecutionStatus",
    "ObservabilityServicePort",
    # Events
    "PhaseCompletedEvent",
    "PhaseDefinition",
    "PhaseExecutionType",
    "PhaseInput",
    "PhaseResult",
    "PhaseStartedEvent",
    "PhaseStatus",
    # Seeders
    "SeedReport",
    "SeedResult",
    "SessionContext",
    "SessionRepositoryPort",
    "WorkflowAggregate",
    "WorkflowClassification",
    "WorkflowCompletedEvent",
    "WorkflowDefinition",
    # Services (will be deprecated in M5)
    "WorkflowExecutionEngine",
    "WorkflowExecutionRepositoryPort",
    "WorkflowExecutionResult",
    "WorkflowExecutionStartedEvent",
    "WorkflowFailedEvent",
    "WorkflowRepositoryPort",
    "WorkflowSeeder",
    "WorkflowType",
    "WorkspaceServicePort",
    # Utilities
    "load_workflow_definitions",
    "validate_workflow_yaml",
]
