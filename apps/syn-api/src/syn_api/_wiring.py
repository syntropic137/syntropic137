"""Internal composition root — wires adapters to domain handlers.

Consolidates the duplicated factory-call patterns from CLI and dashboard
into a single location. All v1 module functions use these helpers to
obtain properly-configured domain handlers and projections.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_api.services.webhook_health_tracker import WebhookHealthTracker
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

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
    WorkflowExecutionProcessor,
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


async def get_execution_processor() -> WorkflowExecutionProcessor:
    """Wire up WorkflowExecutionProcessor with all dependencies (ISS-196).

    Replaces the old get_execution_engine() — uses the Processor To-Do List
    pattern instead of the imperative WorkflowExecutionEngine.
    """
    event_store = get_event_store()
    await event_store.initialize()

    artifact_storage = await get_artifact_storage()
    conversation_storage = await get_conversation_storage()

    manager = get_projection_manager()
    artifact_query = ArtifactQueryService(manager.artifact_list)

    from syn_adapters.projection_stores import get_projection_store
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    return WorkflowExecutionProcessor(
        execution_repository=get_workflow_execution_repository(),
        session_repository=get_session_repository(),
        workspace_service=WorkspaceService.create(),
        artifact_repository=get_artifact_repository(),
        artifact_content_storage=artifact_storage,
        artifact_query=artifact_query,
        conversation_storage=conversation_storage,
        observability_writer=event_store,
        controller=get_controller(),
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_claude_command,
        todo_projection=ExecutionTodoProjection(store=get_projection_store()),
    )


def _build_claude_command(
    phase: ExecutablePhase,
    prompt: str,
) -> list[str]:
    """Build the Claude CLI command for agent execution."""
    model = phase.agent_config.model
    cmd = [
        "claude",
        "--model",
        model,
        "--verbose",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
    ]

    if phase.agent_config.allowed_tools:
        for tool in phase.agent_config.allowed_tools:
            cmd.extend(["--allowedTools", tool])

    return cmd


def _substitute_builtins(
    template: str,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
) -> str:
    """Layer 1: Replace built-in variables in the prompt template."""
    result = template.replace("{{execution_id}}", execution_id)
    result = result.replace("{{workflow_id}}", workflow_id)
    result = result.replace("{{repo_url}}", repo_url or "")
    return result


def _substitute_inputs(
    template: str,
    phase: ExecutablePhase,
    inputs: dict[str, Any] | None,
    phase_outputs: dict[str, str],
) -> str:
    """Layers 2a-2d: Replace workflow inputs, phase inputs, outputs, and $ARGUMENTS."""
    result = template

    # Layer 2a: Workflow inputs
    if inputs:
        for key, value in inputs.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))

    # Layer 2b: Phase-level static inputs
    for phase_input in phase.inputs:
        if phase_input.value is not None:
            result = result.replace(f"{{{{{phase_input.name}}}}}", phase_input.value)

    # Layer 2c: Phase outputs inline
    for pid, content in phase_outputs.items():
        result = result.replace(f"{{{{{pid}}}}}", content[:2000])

    # Layer 2d: $ARGUMENTS substitution (ISS-211 CC command pattern)
    task = (inputs or {}).get("task", "")
    result = result.replace("$ARGUMENTS", str(task))

    return result


def _build_context_appendix(phase_outputs: dict[str, str]) -> str:
    """Layer 3: Build the context appendix from previous phase outputs."""
    parts = ["\n## Context from Previous Phases"]
    for pid, content in phase_outputs.items():
        parts.append(f"\n### Phase {pid}\n{content[:2000]}")
    return "\n".join(parts)


async def _build_workspace_prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: dict[str, Any] | None = None,
) -> str:
    """Build the workspace prompt for a phase.

    Substitution layers (in order):
    1. Built-in variables: {{execution_id}}, {{workflow_id}}, {{repo_url}}
    2a. Workflow inputs: {{key}} → value from inputs dict
    2b. Phase-level static inputs: {{name}} → value from phase definition
    2c. Phase outputs: {{phase-id}} → previous phase artifact content (inline)
    2d. $ARGUMENTS → task string from inputs["task"]
    3. Context appendix: previous phase outputs appended as fallback section
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
        SYN_WORKSPACE_PROMPT,
    )

    phase_prompt = _substitute_builtins(phase.prompt_template, execution_id, workflow_id, repo_url)
    phase_prompt = _substitute_inputs(phase_prompt, phase, inputs, phase_outputs)

    prompt_parts = [SYN_WORKSPACE_PROMPT, f"\n## Task\n{phase_prompt}"]

    if phase_outputs:
        prompt_parts.append(_build_context_appendix(phase_outputs))

    return "\n".join(prompt_parts)


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


# ---------------------------------------------------------------------------
# Event pipeline (ISS-386) — dedup + unified ingestion
# ---------------------------------------------------------------------------

_event_pipeline_singleton: object | None = None
_webhook_health_tracker_singleton: object | None = None


def get_event_pipeline() -> EventPipeline:
    """Return the singleton EventPipeline with Redis dedup (in-memory fallback)."""
    from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline

    global _event_pipeline_singleton
    if _event_pipeline_singleton is not None:
        assert isinstance(_event_pipeline_singleton, EventPipeline)
        return _event_pipeline_singleton

    dedup = _create_dedup_adapter()
    pipeline = EventPipeline(
        dedup=dedup,
        trigger_store=get_trigger_store(),
        trigger_repo=get_trigger_repo(),
    )
    _event_pipeline_singleton = pipeline
    return pipeline


def _create_dedup_adapter() -> object:
    """Create the appropriate dedup adapter based on environment."""
    from syn_shared.settings import get_settings

    settings = get_settings()

    if settings.uses_in_memory_stores:
        from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter

        return InMemoryDedupAdapter()

    try:
        import redis.asyncio as aioredis

        from syn_adapters.dedup.redis_dedup import RedisDedupAdapter

        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("EventPipeline using Redis dedup (%s)", settings.redis_url)
        return RedisDedupAdapter(redis_client)
    except Exception:
        logger.warning(
            "Redis unavailable for dedup — using in-memory fallback",
            exc_info=True,
        )
        from syn_adapters.dedup.memory_dedup import InMemoryDedupAdapter

        return InMemoryDedupAdapter()


def get_webhook_health_tracker() -> WebhookHealthTracker:
    """Return the singleton WebhookHealthTracker."""
    from syn_api.services.webhook_health_tracker import WebhookHealthTracker

    global _webhook_health_tracker_singleton
    if _webhook_health_tracker_singleton is not None:
        assert isinstance(_webhook_health_tracker_singleton, WebhookHealthTracker)
        return _webhook_health_tracker_singleton

    from syn_shared.settings import get_settings

    settings = get_settings()
    threshold = settings.polling.webhook_stale_threshold_seconds
    tracker = WebhookHealthTracker(stale_threshold=threshold)
    _webhook_health_tracker_singleton = tracker
    return tracker


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


_controller_singleton: Any = None


def get_controller() -> Any:
    """Return a singleton ExecutionController for pause/resume/cancel/inject.

    Returns the same instance on every call so the execution engine and API
    endpoints share the same signal queue — signals enqueued by an HTTP
    endpoint are visible to the engine polling in the same process.

    Uses a Redis-backed signal queue (REDIS_URL env var, defaults to
    redis://localhost:6379/0). Falls back to _NullSignalQueueAdapter only
    if Redis is explicitly unavailable (no URL and no connection possible).

    Wraps: ExecutionController(ProjectionControlStateAdapter, signal_adapter)
    """
    global _controller_singleton
    if _controller_singleton is not None:
        return _controller_singleton

    from syn_adapters.control import ExecutionController
    from syn_adapters.control.adapters.projection import ProjectionControlStateAdapter
    from syn_adapters.projection_stores import get_projection_store

    state_adapter = ProjectionControlStateAdapter(get_projection_store())

    from syn_shared.settings import get_settings

    redis_url = get_settings().redis_url
    try:
        import redis.asyncio as aioredis

        from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter

        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        signal_adapter: Any = RedisSignalQueueAdapter(redis_client)
        logger.info("ExecutionController using Redis signal queue (%s)", redis_url)
    except Exception:
        logger.warning(
            "Redis unavailable (%s) — control signals (pause/cancel/resume) will not work",
            redis_url,
            exc_info=True,
        )
        signal_adapter = _NullSignalQueueAdapter()

    _controller_singleton = ExecutionController(
        state_port=state_adapter,
        signal_port=signal_adapter,
    )
    return _controller_singleton


logger = logging.getLogger(__name__)


class BackgroundWorkflowDispatcher:
    """Bridges WorkflowDispatchProjection → ExecuteWorkflowHandler.

    - run_workflow() → handler.handle() bridge
    - Fire-and-forget via asyncio.Task (never blocks projection loop)
    - Tracks tasks for graceful shutdown
    """

    def __init__(self, handler: ExecuteWorkflowHandler) -> None:
        self._handler = handler
        self._tasks: set[asyncio.Task[None]] = set()

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str = "",
        task: str | None = None,
    ) -> None:
        asyncio_task = asyncio.create_task(
            self._run(workflow_id, inputs, execution_id, task=task),
            name=f"workflow-exec-{execution_id or workflow_id}",
        )
        self._tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._tasks.discard)

    async def _run(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
    ) -> None:
        from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
            ExecuteWorkflowCommand,
        )

        try:
            cmd = ExecuteWorkflowCommand(
                aggregate_id=workflow_id,
                inputs=inputs or {},
                execution_id=execution_id or None,
                task=task,
            )
            await self._handler.handle(cmd)
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
    """Create a BackgroundWorkflowDispatcher backed by the processor."""
    from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
        ExecuteWorkflowHandler,
    )

    processor = await get_execution_processor()
    handler = ExecuteWorkflowHandler(
        processor=processor,
        workflow_repository=get_workflow_repository(),
    )
    return BackgroundWorkflowDispatcher(handler)


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
