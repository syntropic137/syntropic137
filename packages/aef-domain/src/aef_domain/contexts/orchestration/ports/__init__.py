"""Port interfaces for the workflows bounded context.

This module defines the port (interface) layer for workflow execution.
Per Hexagonal Architecture / Ports & Adapters pattern:

- **Ports** (here): Interface definitions (Protocols)
- **Adapters** (aef-adapters): Concrete implementations

The domain layer depends ONLY on these port interfaces, never on concrete adapters.
This keeps the domain pure and testable in isolation.

Port Naming Convention:
- Repository ports: {Aggregate}RepositoryPort
- Service ports: {Capability}ServicePort
- "Port" suffix makes the port/adapter distinction explicit

Example Usage:
    from aef_domain.contexts.orchestration.ports import WorkflowTemplateRepositoryPort

    def create_workflow_service(
        workflow_repository: WorkflowTemplateRepositoryPort,  # Port type
        execution_repository: WorkflowExecutionRepositoryPort,
        workspace_service: WorkspaceServicePort,
    ) -> WorkflowExecutionService:
        # Implementation...

See ADR-040: Ports Per Bounded Context for architectural decisions.
"""

from aef_domain.contexts.orchestration.ports.AgentFactoryPort import AgentFactoryPort
from aef_domain.contexts.orchestration.ports.ArtifactContentStoragePort import (
    ArtifactContentStoragePort,
)
from aef_domain.contexts.orchestration.ports.ArtifactQueryServicePort import (
    ArtifactQueryServicePort,
)
from aef_domain.contexts.orchestration.ports.ArtifactRepositoryPort import (
    ArtifactRepositoryPort,
)
from aef_domain.contexts.orchestration.ports.ConversationStoragePort import (
    ConversationStoragePort,
)
from aef_domain.contexts.orchestration.ports.ObservabilityServicePort import (
    ObservabilityServicePort,
)
from aef_domain.contexts.orchestration.ports.SessionRepositoryPort import (
    SessionRepositoryPort,
)
from aef_domain.contexts.orchestration.ports.WorkflowExecutionRepositoryPort import (
    WorkflowExecutionRepositoryPort,
)
from aef_domain.contexts.orchestration.ports.WorkflowTemplateRepositoryPort import (
    WorkflowTemplateRepositoryPort,
)
from aef_domain.contexts.orchestration.ports.WorkspaceServicePort import (
    WorkspaceServicePort,
)

__all__ = [
    # Factory Ports
    "AgentFactoryPort",
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
