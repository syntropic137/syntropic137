"""Infrastructure handlers for the Processor To-Do List pattern (ISS-196).

Each handler is single-responsibility, <200 LOC, and independently testable.
Handlers do infrastructure work and report results back via aggregate commands.
"""

from __future__ import annotations

from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)

HANDLER_REGISTRY: dict[TodoAction, type] = {
    TodoAction.PROVISION_WORKSPACE: WorkspaceProvisionHandler,
    TodoAction.RUN_AGENT: AgentExecutionHandler,
    TodoAction.COLLECT_ARTIFACTS: ArtifactCollectionHandler,
}

__all__ = [
    "HANDLER_REGISTRY",
    "AgentExecutionHandler",
    "ArtifactCollectionHandler",
    "WorkspaceProvisionHandler",
]
