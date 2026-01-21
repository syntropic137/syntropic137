"""Workflows bounded context - workflow management and execution."""

from aef_domain.contexts.workflows._shared import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseDefinition,
    PhaseExecutionType,
    PhaseInput,
    PhaseResult,
    PhaseStatus,
    WorkflowAggregate,
    WorkflowClassification,
    WorkflowDefinition,
    WorkflowType,
    load_workflow_definitions,
    validate_workflow_yaml,
)
from aef_domain.contexts.workflows.execute_workflow import (
    ExecuteWorkflowCommand,
    PhaseCompletedEvent,
    PhaseStartedEvent,
    WorkflowCompletedEvent,
    WorkflowExecutionEngine,
    WorkflowExecutionResult,
    WorkflowExecutionStartedEvent,
    WorkflowFailedEvent,
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

__all__ = [
    # Value Objects & Aggregates
    "AgentConfiguration",
    "ExecutablePhase",
    "ExecutionMetrics",
    "ExecutionStatus",
    "PhaseDefinition",
    "PhaseExecutionType",
    "PhaseInput",
    "PhaseResult",
    "PhaseStatus",
    "WorkflowAggregate",
    "WorkflowClassification",
    "WorkflowDefinition",
    "WorkflowType",
    # Commands
    "ExecuteWorkflowCommand",
    # Events
    "PhaseCompletedEvent",
    "PhaseStartedEvent",
    "WorkflowCompletedEvent",
    "WorkflowExecutionStartedEvent",
    "WorkflowFailedEvent",
    # Services (will be deprecated in M5)
    "WorkflowExecutionEngine",
    "WorkflowExecutionResult",
    # Seeders
    "SeedReport",
    "SeedResult",
    "WorkflowSeeder",
    # Utilities
    "load_workflow_definitions",
    "validate_workflow_yaml",
    # Ports (NEW in M1)
    "AgentFactoryPort",
    "ArtifactContentStoragePort",
    "ArtifactQueryServicePort",
    "ArtifactRepositoryPort",
    "ConversationStoragePort",
    "ObservabilityServicePort",
    "SessionRepositoryPort",
    "WorkflowExecutionRepositoryPort",
    "WorkflowRepositoryPort",
    "WorkspaceServicePort",
]
