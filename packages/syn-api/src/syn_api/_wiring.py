"""Internal composition root — wires adapters to domain handlers.

Consolidates the duplicated factory-call patterns from CLI and dashboard
into a single location. All v1 module functions use these helpers to
obtain properly-configured domain handlers and projections.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from syn_adapters.agents import AgentProvider, get_agent
from syn_adapters.conversations import get_conversation_storage
from syn_adapters.events import get_event_store
from syn_adapters.projections.manager import ProjectionManager, get_projection_manager
from syn_adapters.storage import (
    connect_event_store,
    disconnect_event_store,
    get_artifact_repository,
    get_event_publisher,
    get_event_store_client,
    get_session_repository,
    get_workflow_repository,
)
from syn_adapters.storage.artifact_storage import get_artifact_storage
from syn_adapters.storage.repositories import (
    get_trigger_repository,
    get_workflow_execution_repository,
)
from syn_adapters.workspace_backends.service import WorkspaceService
from syn_domain.contexts.artifacts import ArtifactQueryService
from syn_domain.contexts.orchestration.slices.execute_workflow import (
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
        controller=get_controller(),
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


class _InMemoryAggregateRepository:
    """Simple in-memory repository for test mode (trigger aggregates).

    InMemoryTriggerQueryStore from the domain layer lacks the save()/get_by_id()
    interface required by domain handlers, so we provide a minimal implementation.
    """

    def __init__(self) -> None:
        self._aggregates: dict[str, Any] = {}

    async def get_by_id(self, aggregate_id: str) -> Any:
        return self._aggregates.get(aggregate_id)

    async def save(self, aggregate: Any) -> None:
        agg_id = str(aggregate.id) if hasattr(aggregate, "id") else str(aggregate.trigger_id)
        self._aggregates[agg_id] = aggregate

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self._aggregates


_test_trigger_repo: _InMemoryAggregateRepository | None = None


def get_trigger_repo():
    """Return the trigger rule repository.

    In test mode, returns a NullRepository since InMemoryTriggerQueryStore
    lacks save()/get_by_id() required by domain handlers.
    """
    from syn_shared.settings import get_settings

    settings = get_settings()
    if settings.uses_in_memory_stores:
        global _test_trigger_repo
        if _test_trigger_repo is None:
            _test_trigger_repo = _InMemoryAggregateRepository()
        return _test_trigger_repo

    return get_trigger_repository()


def get_trigger_store():
    """Return the trigger query store."""
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        get_trigger_query_store,
    )

    return get_trigger_query_store()


async def sync_published_events_to_projections() -> None:
    """Dispatch published events from InMemoryEventPublisher to projections.

    In test mode (APP_ENVIRONMENT=test), events are stored by the
    InMemoryEventPublisher but NOT automatically dispatched to projections
    (there's no subscription service running). This helper bridges the gap
    so that API-level integration tests can verify create→list round-trips.

    No-op in production (NoOpEventPublisher has no stored events).
    """
    from syn_adapters.storage.in_memory import InMemoryEventPublisher

    publisher = get_event_publisher()
    if not isinstance(publisher, InMemoryEventPublisher):
        return

    manager = get_projection_manager()
    for envelope in publisher.get_published_events():
        await manager.process_event_envelope(envelope)

    # Clear processed events to avoid re-processing
    publisher._published_events.clear()


# ---------------------------------------------------------------------------
# Phase 3 additions — execution control, events, conversations, etc.
# ---------------------------------------------------------------------------


def get_controller() -> Any:
    """Return a singleton ExecutionController for pause/resume/cancel/inject.

    Wraps: ExecutionController(ProjectionControlStateAdapter, signal_adapter)
    """
    from syn_adapters.control import ExecutionController
    from syn_adapters.control.adapters.projection import ProjectionControlStateAdapter
    from syn_adapters.projection_stores import get_projection_store

    state_adapter = ProjectionControlStateAdapter(get_projection_store())

    env = os.environ.get("APP_ENVIRONMENT", "")
    if env in ("test", "offline"):
        from syn_adapters.control.adapters.memory import InMemorySignalQueueAdapter

        signal_adapter: Any = InMemorySignalQueueAdapter()
    else:
        signal_adapter = _NullSignalQueueAdapter()

    return ExecutionController(
        state_port=state_adapter,
        signal_port=signal_adapter,
    )


logger = logging.getLogger(__name__)


class BackgroundWorkflowDispatcher:
    """Bridges WorkflowDispatchProjection → WorkflowExecutionEngine.

    - run_workflow() → execute() method name bridge
    - Fire-and-forget via asyncio.Task (never blocks projection loop)
    - Tracks tasks for graceful shutdown
    """

    def __init__(self, engine: WorkflowExecutionEngine) -> None:
        self._engine = engine
        self._tasks: set[asyncio.Task] = set()

    async def run_workflow(self, workflow_id: str, inputs: dict, execution_id: str = "") -> None:
        task = asyncio.create_task(
            self._run(workflow_id, inputs, execution_id),
            name=f"workflow-exec-{execution_id or workflow_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, workflow_id: str, inputs: dict, execution_id: str) -> None:
        try:
            await self._engine.execute(
                workflow_id=workflow_id,
                inputs=inputs,
                execution_id=execution_id or None,
            )
        except Exception:
            logger.exception(
                "Background workflow failed",
                extra={"workflow_id": workflow_id, "execution_id": execution_id},
            )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


async def get_workflow_dispatcher() -> BackgroundWorkflowDispatcher:
    """Create a BackgroundWorkflowDispatcher backed by the execution engine."""
    engine = await get_execution_engine()
    return BackgroundWorkflowDispatcher(engine)


class _NullSignalQueueAdapter:
    """No-op signal adapter when Redis is not available."""

    async def enqueue(self, _execution_id: str, _signal: object) -> None:
        pass

    async def dequeue(self, _execution_id: str) -> None:
        return None

    async def get_signal(self, _execution_id: str) -> None:
        return None


def get_event_store_instance() -> Any:
    """Return the AgentEventStore for TimescaleDB queries."""
    return get_event_store()


async def get_conversation_store() -> Any:
    """Return the conversation storage (MinIO-backed)."""
    return await get_conversation_storage()


def get_realtime() -> Any:
    """Return the RealTimeProjection singleton."""
    from syn_adapters.projections.realtime import get_realtime_projection

    return get_realtime_projection()


def get_subscription_coordinator(
    realtime_projection: Any = None,
    execution_service: Any = None,
) -> Any:
    """Create the CoordinatorSubscriptionService.

    Wraps: create_coordinator_service(event_store, projection_store, ...)
    """
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.subscriptions import create_coordinator_service

    return create_coordinator_service(
        event_store=get_event_store_client(),
        projection_store=get_projection_store(),
        realtime_projection=realtime_projection,
        execution_service=execution_service,
    )


def get_github_settings() -> Any:
    """Return the GitHubAppSettings instance."""
    from syn_shared.settings.github import get_github_settings as _get

    return _get()
