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

from syn_domain.contexts.orchestration.ports.ArtifactContentStoragePort import (
    ArtifactContentStoragePort,
)
from syn_domain.contexts.orchestration.ports.ArtifactQueryServicePort import (
    ArtifactQueryServicePort,
)
from syn_domain.contexts.orchestration.ports.ArtifactRepositoryPort import (
    ArtifactRepositoryPort,
)
from syn_domain.contexts.orchestration.ports.ConversationStoragePort import (
    ConversationStoragePort,
)
from syn_domain.contexts.orchestration.ports.ObservabilityServicePort import (
    ObservabilityServicePort,
)
from syn_domain.contexts.orchestration.ports.SessionRepositoryPort import (
    SessionRepositoryPort,
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
    "ArtifactContentStoragePort",
    "ArtifactQueryServicePort",
    "ArtifactRepositoryPort",
    "ConversationStoragePort",
    "ObservabilityServicePort",
    "SessionRepositoryPort",
    "WorkflowExecutionRepositoryPort",
    # Repository Ports
    "WorkflowTemplateRepositoryPort",
    # Service Ports
    "WorkspaceServicePort",
]
