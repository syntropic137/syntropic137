"""Projection manager for event dispatch and catch-up."""

import logging
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from aef_adapters.projection_stores import get_projection_store
from aef_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
from aef_domain.contexts.metrics.slices.get_metrics import DashboardMetricsProjection
from aef_domain.contexts.sessions.slices.list_sessions import SessionListProjection
from aef_domain.contexts.workflows.slices.get_workflow_detail import (
    WorkflowDetailProjection,
)
from aef_domain.contexts.workflows.slices.list_workflows import WorkflowListProjection

logger = logging.getLogger(__name__)


@runtime_checkable
class Projection(Protocol):
    """Protocol for projections that can handle events."""

    @property
    def name(self) -> str:
        """Get the projection name."""
        ...


# Event type to projection method mapping
EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    # Workflow events
    "WorkflowCreated": [
        ("workflow_list", "on_workflow_created"),
        ("workflow_detail", "on_workflow_created"),
        ("dashboard_metrics", "on_workflow_created"),
    ],
    "WorkflowExecutionStarted": [
        ("workflow_detail", "on_workflow_execution_started"),
        ("dashboard_metrics", "on_workflow_execution_started"),
    ],
    "PhaseStarted": [
        ("workflow_list", "on_phase_started"),
        ("workflow_detail", "on_phase_started"),
    ],
    "PhaseCompleted": [
        ("workflow_detail", "on_phase_completed"),
    ],
    "WorkflowCompleted": [
        ("workflow_list", "on_workflow_completed"),
        ("workflow_detail", "on_workflow_completed"),
        ("dashboard_metrics", "on_workflow_completed"),
    ],
    "WorkflowFailed": [
        ("workflow_list", "on_workflow_failed"),
        ("workflow_detail", "on_workflow_failed"),
        ("dashboard_metrics", "on_workflow_failed"),
    ],
    # Session events
    "SessionStarted": [
        ("session_list", "on_session_started"),
        ("dashboard_metrics", "on_session_started"),
    ],
    "OperationRecorded": [
        ("session_list", "on_operation_recorded"),
    ],
    "SessionCompleted": [
        ("session_list", "on_session_completed"),
        ("dashboard_metrics", "on_session_completed"),
    ],
    # Artifact events
    "ArtifactCreated": [
        ("artifact_list", "on_artifact_created"),
        ("dashboard_metrics", "on_artifact_created"),
    ],
}


class ProjectionManager:
    """Manages projection instances and event dispatch.

    This class is responsible for:
    1. Creating and caching projection instances
    2. Routing events to appropriate projections
    3. Managing projection catch-up from event store
    """

    def __init__(self) -> None:
        """Initialize the projection manager."""
        self._store = get_projection_store()
        self._projections: dict[str, Any] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazily initialize projections."""
        if self._initialized:
            return

        self._projections = {
            "workflow_list": WorkflowListProjection(self._store),
            "workflow_detail": WorkflowDetailProjection(self._store),
            "session_list": SessionListProjection(self._store),
            "artifact_list": ArtifactListProjection(self._store),
            "dashboard_metrics": DashboardMetricsProjection(self._store),
        }
        self._initialized = True

    def get_projection(self, name: str) -> Any:
        """Get a projection by name.

        Args:
            name: The projection name

        Returns:
            The projection instance

        Raises:
            KeyError: If projection not found
        """
        self._ensure_initialized()
        return self._projections[name]

    async def dispatch_event(self, event_type: str, event_data: dict) -> None:
        """Dispatch an event to all interested projections.

        Args:
            event_type: The type of event
            event_data: The event payload
        """
        self._ensure_initialized()

        handlers = EVENT_HANDLERS.get(event_type, [])
        for projection_name, method_name in handlers:
            projection = self._projections.get(projection_name)
            if projection:
                handler = getattr(projection, method_name, None)
                if handler:
                    try:
                        await handler(event_data)
                    except Exception as e:
                        logger.error(
                            f"Error in projection {projection_name}.{method_name}: {e}"
                        )

    async def catch_up_all(self, events: list[dict]) -> None:
        """Catch up all projections from a list of events.

        Args:
            events: List of event dictionaries with 'event_type' and payload
        """
        for event in events:
            event_type = event.get("event_type", "")
            await self.dispatch_event(event_type, event)

    @property
    def workflow_list(self) -> WorkflowListProjection:
        """Get the workflow list projection."""
        self._ensure_initialized()
        return self._projections["workflow_list"]

    @property
    def workflow_detail(self) -> WorkflowDetailProjection:
        """Get the workflow detail projection."""
        self._ensure_initialized()
        return self._projections["workflow_detail"]

    @property
    def session_list(self) -> SessionListProjection:
        """Get the session list projection."""
        self._ensure_initialized()
        return self._projections["session_list"]

    @property
    def artifact_list(self) -> ArtifactListProjection:
        """Get the artifact list projection."""
        self._ensure_initialized()
        return self._projections["artifact_list"]

    @property
    def dashboard_metrics(self) -> DashboardMetricsProjection:
        """Get the dashboard metrics projection."""
        self._ensure_initialized()
        return self._projections["dashboard_metrics"]


@lru_cache
def get_projection_manager() -> ProjectionManager:
    """Get the singleton projection manager instance."""
    return ProjectionManager()


def reset_projection_manager() -> None:
    """Reset the projection manager singleton (for testing)."""
    get_projection_manager.cache_clear()

