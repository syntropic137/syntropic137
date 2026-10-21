"""Port interfaces for the workflows bounded context.

This module defines the port (interface) layer for workflow execution.
Per Hexagonal Architecture / Ports & Adapters pattern:

- **Ports** (here): Interface definitions (Protocols)
- **Adapters** (syn-adapters): Concrete implementations

The domain layer depends ONLY on these port interfaces, never on concrete adapters.
This keeps the domain pure and testable in isolation.

Port Naming Convention:
- Repository ports: {Aggregate}RepositoryPort
- Service ports: {Capability}ServicePort
- "Port" suffix makes the port/adapter distinction explicit

Example Usage:
    from syn_domain.contexts.orchestration.ports import WorkflowTemplateRepositoryPort

    def create_workflow_service(
        workflow_repository: WorkflowTemplateRepositoryPort,  # Port type
        execution_repository: WorkflowExecutionRepositoryPort,
        workspace_service: WorkspaceServicePort,
    ) -> WorkflowExecutionService:
        # Implementation...

See ADR-040: Ports Per Bounded Context for architectural decisions.
"""

from syn_domain.contexts.orchestration.ports.ArtifactQueryServicePort import (
    ArtifactQueryServicePort,
)
from syn_domain.contexts.orchestration.ports.ArtifactRepositoryPort import (
    ArtifactRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginRegistrationRepositoryPort import (
    ClaudePluginRegistrationRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.ClaudePluginStoragePort import (
    ClaudePluginFile,
    ClaudePluginStoragePort,
    StoredClaudePluginTree,
)
from syn_domain.contexts.orchestration.ports.CodexRolloutPort import (
    CodexRolloutPort,
)
from syn_domain.contexts.orchestration.ports.DelegationEvidencePort import (
    DelegationAttempt,
    DelegationEvidencePort,
    DelegationEvidenceUnavailableError,
    DelegationOutcome,
)
from syn_domain.contexts.orchestration.ports.EvidenceRunnerPort import (
    EvidenceRunnerPort,
)
from syn_domain.contexts.orchestration.ports.ExecutionRunQueuePort import (
    DEFAULT_EXECUTOR_POOL,
    Capability,
    ClaimedRun,
    ExecutionRunQueue,
    ExecutionStreamProbe,
    ExecutorHost,
    ExecutorPool,
    FencedRun,
    IsolationLevel,
    OpeningSweep,
    PoolDefinitionConflict,
    RunCounts,
    RunLeaseLost,
    StreamPresence,
)
from syn_domain.contexts.orchestration.ports.GlobalClaudePluginRegistryRepositoryPort import (
    GlobalClaudePluginRegistryRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.ObservabilityServicePort import (
    ObservabilityServicePort,
)
from syn_domain.contexts.orchestration.ports.RemoteBranchPort import (
    RemoteBranchPort,
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.ports.RemoteBranchWriterPort import (
    RemoteBranchWriterPort,
)
from syn_domain.contexts.orchestration.ports.RemoteTreePort import RemoteTreePort
from syn_domain.contexts.orchestration.ports.SessionRepositoryPort import (
    SessionRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.SourceCommitResolverPort import (
    SourceCommitResolverPort,
)
from syn_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
    WorkflowExecutionRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.WorkflowTemplateRepositoryPort import (
    WorkflowTemplateRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.WorkspaceServicePort import (
    WorkspaceServicePort,
)

__all__ = [
    "DEFAULT_EXECUTOR_POOL",
    "ArtifactQueryServicePort",
    "ArtifactRepositoryPort",
    "Capability",
    "ClaimedRun",
    "ClaudePluginFile",
    "ClaudePluginRegistrationRepositoryPort",
    "ClaudePluginStoragePort",
    "CodexRolloutPort",
    "DelegationAttempt",
    "DelegationEvidencePort",
    "DelegationEvidenceUnavailableError",
    "DelegationOutcome",
    "EvidenceRunnerPort",
    "ExecutionRunQueue",
    "ExecutionStreamProbe",
    "ExecutorHost",
    "ExecutorPool",
    "FencedRun",
    "GlobalClaudePluginRegistryRepositoryPort",
    "IsolationLevel",
    "ObservabilityServicePort",
    "OpeningSweep",
    "PoolDefinitionConflict",
    "RemoteBranchPort",
    "RemoteBranchReading",
    "RemoteBranchWriterPort",
    "RemoteTreePort",
    "RunCounts",
    "RunLeaseLost",
    "SessionRepositoryPort",
    "SourceCommitResolverPort",
    "StoredClaudePluginTree",
    "StreamPresence",
    "WorkflowExecutionRepositoryPort",
    # Repository Ports
    "WorkflowTemplateRepositoryPort",
    # Service Ports
    "WorkspaceServicePort",
]
