"""Internal composition root — wires adapters to domain handlers.

Consolidates the duplicated factory-call patterns from CLI and dashboard
into a single location. All v1 module functions use these helpers to
obtain properly-configured domain handlers and projections.
"""

from __future__ import annotations

from typing import Any

from aef_adapters.agents import AgentProvider, get_agent
from aef_adapters.conversations import get_conversation_storage
from aef_adapters.events import get_event_store
from aef_adapters.projections.manager import ProjectionManager, get_projection_manager
from aef_adapters.storage import (
    connect_event_store,
    disconnect_event_store,
    get_artifact_repository,
    get_event_publisher,
    get_session_repository,
    get_workflow_repository,
)
from aef_adapters.storage.artifact_storage import get_artifact_storage
from aef_adapters.storage.repositories import get_workflow_execution_repository
from aef_adapters.workspace_backends.service import WorkspaceService
from aef_domain.contexts.artifacts import ArtifactQueryService
from aef_domain.contexts.orchestration.slices.execute_workflow import (
    WorkflowExecutionEngine,
)


async def ensure_connected() -> None:
    """Ensure the event store connection is established."""
    await connect_event_store()


async def disconnect() -> None:
    """Gracefully disconnect from the event store."""
    await disconnect_event_store()


def get_projection_mgr() -> ProjectionManager:
    """Return the singleton ProjectionManager."""
    return get_projection_manager()


async def get_execution_engine() -> WorkflowExecutionEngine:
    """Wire up WorkflowExecutionEngine with all dependencies.

    Consolidation of ExecutionService._create_execution_engine()
    and CLI's inline _execute() wiring.
    """

    def agent_factory(provider: str) -> Any:
        try:
            provider_enum = AgentProvider(provider.lower())
        except ValueError:
            provider_enum = AgentProvider.CLAUDE
        return get_agent(provider_enum)

    event_store = get_event_store()
    await event_store.initialize()

    artifact_storage = await get_artifact_storage()
    conversation_storage = await get_conversation_storage()

    manager = get_projection_manager()
    artifact_query = ArtifactQueryService(manager.artifact_list)

    return WorkflowExecutionEngine(
        workflow_repository=get_workflow_repository(),
        execution_repository=get_workflow_execution_repository(),
        workspace_service=WorkspaceService.create(),
        session_repository=get_session_repository(),
        artifact_repository=get_artifact_repository(),
        agent_factory=agent_factory,
        observability_writer=event_store,
        artifact_query_service=artifact_query,
        artifact_content_storage=artifact_storage,
        conversation_storage=conversation_storage,
    )


def get_workflow_repo():
    """Return the workflow template repository."""
    return get_workflow_repository()


def get_session_repo():
    """Return the agent session repository."""
    return get_session_repository()


def get_artifact_repo():
    """Return the artifact repository."""
    return get_artifact_repository()


def get_publisher():
    """Return the event publisher."""
    return get_event_publisher()


async def sync_published_events_to_projections() -> None:
    """Dispatch published events from InMemoryEventPublisher to projections.

    In test mode (APP_ENVIRONMENT=test), events are stored by the
    InMemoryEventPublisher but NOT automatically dispatched to projections
    (there's no subscription service running). This helper bridges the gap
    so that API-level integration tests can verify create→list round-trips.

    No-op in production (NoOpEventPublisher has no stored events).
    """
    from aef_adapters.storage.in_memory import InMemoryEventPublisher

    publisher = get_event_publisher()
    if not isinstance(publisher, InMemoryEventPublisher):
        return

    manager = get_projection_manager()
    for envelope in publisher.get_published_events():
        await manager.process_event_envelope(envelope)

    # Clear processed events to avoid re-processing
    publisher._published_events.clear()
