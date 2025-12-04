"""Projection manager for event dispatch and catch-up.

IMPORTANT: Events should ONLY flow through aggregates and the event store.
Use process_event_envelope() from EventSubscriptionService, NOT dispatch_event().
"""

import logging
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from aef_adapters.projection_stores import get_projection_store
from aef_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
from aef_domain.contexts.metrics.slices.get_metrics import DashboardMetricsProjection
from aef_domain.contexts.sessions.slices.list_sessions import SessionListProjection
from aef_domain.contexts.workflows.slices.get_execution_detail import (
    WorkflowExecutionDetailProjection,
)
from aef_domain.contexts.workflows.slices.get_workflow_detail import (
    WorkflowDetailProjection,
)
from aef_domain.contexts.workflows.slices.list_executions import (
    WorkflowExecutionListProjection,
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


@dataclass(frozen=True, slots=True)
class EventProvenance:
    """Provenance metadata for events from event store.

    This lightweight dataclass validates that events came through
    the proper channel (event store subscription) and not from
    direct dispatch calls that bypass event sourcing.

    Performance: ~50ns to create, O(1) validation - NOT a bottleneck.
    At 1000 concurrent agents, this adds <0.05ms total overhead.
    """

    stream_id: str
    global_nonce: int | None
    event_type: str

    @classmethod
    def from_envelope(cls, envelope: Any) -> "EventProvenance":
        """Extract provenance from an event store envelope.

        Args:
            envelope: Event envelope from event store subscription.

        Returns:
            EventProvenance with stream and position info.

        Raises:
            ValueError: If envelope doesn't have required metadata.
        """
        metadata = getattr(envelope, "metadata", None)
        if metadata is None:
            raise ValueError("Event envelope missing metadata - not from event store")

        stream_id = getattr(metadata, "stream_id", None)
        global_nonce = getattr(metadata, "global_nonce", None)

        event = getattr(envelope, "event", None)
        if event is None:
            raise ValueError("Event envelope missing event")

        event_type = getattr(event, "event_type", None) or type(event).__name__

        return cls(
            stream_id=stream_id or "unknown",
            global_nonce=global_nonce,
            event_type=event_type,
        )


# Event type to projection method mapping
EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    # Workflow events
    "WorkflowCreated": [
        ("workflow_list", "on_workflow_created"),
        ("workflow_detail", "on_workflow_created"),
        ("dashboard_metrics", "on_workflow_created"),
    ],
    # WorkflowExecution events (from WorkflowExecutionAggregate)
    # These update the workflow projections when executions start/complete
    "WorkflowExecutionStarted": [
        ("workflow_list", "on_phase_started"),  # Triggers "in_progress" status
        ("workflow_detail", "on_workflow_execution_started"),
        ("execution_list", "on_workflow_execution_started"),
        ("execution_detail", "on_workflow_execution_started"),
        ("dashboard_metrics", "on_workflow_execution_started"),
    ],
    "PhaseStarted": [
        ("workflow_list", "on_phase_started"),
        ("workflow_detail", "on_phase_started"),
        ("execution_detail", "on_phase_started"),
    ],
    "PhaseCompleted": [
        ("workflow_detail", "on_phase_completed"),
        ("execution_list", "on_phase_completed"),
        ("execution_detail", "on_phase_completed"),
    ],
    "WorkflowCompleted": [
        ("workflow_list", "on_workflow_completed"),
        ("workflow_detail", "on_workflow_completed"),
        ("execution_list", "on_workflow_completed"),
        ("execution_detail", "on_workflow_completed"),
        ("dashboard_metrics", "on_workflow_completed"),
    ],
    "WorkflowFailed": [
        ("workflow_list", "on_workflow_failed"),
        ("workflow_detail", "on_workflow_failed"),
        ("execution_list", "on_workflow_failed"),
        ("execution_detail", "on_workflow_failed"),
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
            "execution_list": WorkflowExecutionListProjection(self._store),
            "execution_detail": WorkflowExecutionDetailProjection(self._store),
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

    async def process_event_envelope(self, envelope: Any) -> EventProvenance:
        """Process an event envelope from the event store.

        This is the ONLY correct way to dispatch events to projections.
        Events MUST come through the event store subscription, ensuring
        proper event sourcing guarantees.

        Args:
            envelope: Event envelope from event store (has metadata, event).

        Returns:
            EventProvenance with stream/position info for tracking.

        Raises:
            ValueError: If envelope is not from event store.
        """
        # Validate provenance - ensures event came from event store
        # O(1) check, ~50ns overhead - NOT a performance concern
        provenance = EventProvenance.from_envelope(envelope)

        # Extract event data
        event = envelope.event
        if hasattr(event, "to_dict"):
            event_data = event.to_dict()
        elif hasattr(event, "model_dump"):
            event_data = event.model_dump()
        else:
            event_data = vars(event) if hasattr(event, "__dict__") else {}

        # Dispatch to handlers
        await self._dispatch_to_handlers(provenance.event_type, event_data)

        return provenance

    async def _dispatch_to_handlers(self, event_type: str, event_data: dict) -> None:
        """Internal: Dispatch event data to projection handlers.

        DO NOT CALL DIRECTLY - use process_event_envelope() instead.
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
                        logger.error(f"Error in projection {projection_name}.{method_name}: {e}")

    async def dispatch_event(self, event_type: str, event_data: dict) -> None:
        """DEPRECATED: Use process_event_envelope() instead.

        This method bypasses event store validation and should not be used.
        Events MUST flow through aggregates and the event store to maintain
        event sourcing guarantees.

        Args:
            event_type: The type of event
            event_data: The event payload
        """
        warnings.warn(
            "dispatch_event() bypasses event sourcing. "
            "Use aggregates and event store subscription instead. "
            "Events should flow: Command → Aggregate → Event Store → Projection",
            DeprecationWarning,
            stacklevel=2,
        )
        await self._dispatch_to_handlers(event_type, event_data)

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
    def execution_list(self) -> WorkflowExecutionListProjection:
        """Get the workflow execution list projection."""
        self._ensure_initialized()
        return self._projections["execution_list"]

    @property
    def execution_detail(self) -> WorkflowExecutionDetailProjection:
        """Get the workflow execution detail projection."""
        self._ensure_initialized()
        return self._projections["execution_detail"]

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
