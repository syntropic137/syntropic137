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
    from aef_domain.contexts.workflows.ports import WorkflowRepositoryPort

    def create_workflow_service(
        workflow_repository: WorkflowRepositoryPort,  # Port type
        execution_repository: WorkflowExecutionRepositoryPort,
        workspace_service: WorkspaceServicePort,
    ) -> WorkflowExecutionService:
        # Implementation...

See ADR-040: Ports Per Bounded Context for architectural decisions.
"""

from aef_domain.contexts.workflows.ports.AgentFactoryPort import AgentFactoryPort
from aef_domain.contexts.workflows.ports.ArtifactContentStoragePort import (
    ArtifactContentStoragePort,
)
from aef_domain.contexts.workflows.ports.ArtifactQueryServicePort import (
    ArtifactQueryServicePort,
)
from aef_domain.contexts.workflows.ports.ArtifactRepositoryPort import (
    ArtifactRepositoryPort,
)
from aef_domain.contexts.workflows.ports.ConversationStoragePort import (
    ConversationStoragePort,
)
from aef_domain.contexts.workflows.ports.ObservabilityServicePort import (
    ObservabilityServicePort,
)
from aef_domain.contexts.workflows.ports.SessionRepositoryPort import (
    SessionRepositoryPort,
)
from aef_domain.contexts.workflows.ports.WorkflowExecutionRepositoryPort import (
    WorkflowExecutionRepositoryPort,
)
from aef_domain.contexts.workflows.ports.WorkflowRepositoryPort import (
    WorkflowRepositoryPort,
)
from aef_domain.contexts.workflows.ports.WorkspaceServicePort import (
    WorkspaceServicePort,
)

__all__ = [
    # Repository Ports
    "WorkflowRepositoryPort",
    "WorkflowExecutionRepositoryPort",
    "SessionRepositoryPort",
    "ArtifactRepositoryPort",
    # Service Ports
    "WorkspaceServicePort",
    "ObservabilityServicePort",
    "ConversationStoragePort",
    "ArtifactContentStoragePort",
    "ArtifactQueryServicePort",
    # Factory Ports
    "AgentFactoryPort",
]
