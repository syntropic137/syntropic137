"""Projection manager for event dispatch and catch-up.

IMPORTANT: Events should ONLY flow through aggregates and the event store.
Use process_event_envelope() from EventSubscriptionService, NOT dispatch_event().
"""

import logging
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from syn_adapters.projection_stores import get_projection_store
from syn_adapters.projections.session_tools import SessionToolsProjection
from syn_domain.contexts.agent_sessions.slices.list_sessions import SessionListProjection
from syn_domain.contexts.agent_sessions.slices.session_cost.projection import SessionCostProjection
from syn_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineProjection
from syn_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
from syn_domain.contexts.orchestration.slices.dashboard_metrics import DashboardMetricsProjection
from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
    ExecutionCostProjection,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.get_workflow_detail import (
    WorkflowDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions import (
    WorkflowExecutionListProjection,
)
from syn_domain.contexts.orchestration.slices.list_workflows import WorkflowListProjection
from syn_domain.contexts.orchestration.slices.workflow_phase_metrics import (
    WorkflowPhaseMetricsProjection,
)
from syn_domain.contexts.organization.slices.repo_correlation import (
    RepoCorrelationProjection,
)
from syn_domain.contexts.organization.slices.repo_cost import RepoCostProjection
from syn_domain.contexts.organization.slices.repo_health import RepoHealthProjection
from syn_shared.events import (
    SESSION_SUMMARY,
    TOKEN_USAGE,
    TOOL_BLOCKED,
    TOOL_EXECUTION_COMPLETED,
    TOOL_EXECUTION_STARTED,
)

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
#
# IMPORTANT: Workflow TEMPLATE projections (workflow_list, workflow_detail)
# only handle template events (WorkflowCreated) and runs_count updates.
# Execution events go to EXECUTION projections (execution_list, execution_detail).
#
# The "realtime" projection pushes events to WebSocket clients for live UI updates.
# It doesn't persist data - it's a pure forwarding layer.
EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    # GitHub trigger events (cross-context correlation)
    "github.TriggerFired": [
        ("repo_correlation", "on_trigger_fired"),
    ],
    # Workflow TEMPLATE events
    "WorkflowTemplateCreated": [
        ("workflow_list", "on_workflow_template_created"),
        ("workflow_detail", "on_workflow_template_created"),
        ("dashboard_metrics", "on_workflow_template_created"),
    ],
    # Legacy event type (before rename to WorkflowTemplateCreated)
    "WorkflowCreated": [
        ("workflow_list", "on_workflow_template_created"),
        ("workflow_detail", "on_workflow_template_created"),
        ("dashboard_metrics", "on_workflow_template_created"),
    ],
    # WorkflowExecution events (from WorkflowExecutionAggregate)
    # Template projections only update runs_count, not status
    "WorkflowExecutionStarted": [
        ("workflow_list", "on_workflow_execution_started"),  # Increment runs_count
        ("workflow_detail", "on_workflow_execution_started"),  # Increment runs_count
        ("workflow_execution_list", "on_workflow_execution_started"),
        ("workflow_execution_detail", "on_workflow_execution_started"),
        ("dashboard_metrics", "on_workflow_execution_started"),
        ("repo_correlation", "on_workflow_execution_started"),  # Repo ↔ execution mapping
        ("realtime", "on_workflow_execution_started"),  # Real-time UI push
    ],
    # Execution events - go to EXECUTION projections only
    "PhaseStarted": [
        ("workflow_execution_detail", "on_phase_started"),
        ("workflow_phase_metrics", "on_phase_started"),
        ("realtime", "on_phase_started"),  # Real-time UI push
    ],
    "PhaseCompleted": [
        ("workflow_execution_list", "on_phase_completed"),
        ("workflow_execution_detail", "on_phase_completed"),
        ("workflow_phase_metrics", "on_phase_completed"),
        ("realtime", "on_phase_completed"),  # Real-time UI push
    ],
    "WorkflowCompleted": [
        ("workflow_execution_list", "on_workflow_completed"),
        ("workflow_execution_detail", "on_workflow_completed"),
        ("dashboard_metrics", "on_workflow_completed"),
        ("repo_health", "on_workflow_completed"),  # Per-repo health tracking
        ("repo_cost", "on_workflow_completed"),  # Per-repo cost tracking
        ("realtime", "on_workflow_completed"),  # Real-time UI push
    ],
    "WorkflowFailed": [
        ("workflow_execution_list", "on_workflow_failed"),
        ("workflow_execution_detail", "on_workflow_failed"),
        ("dashboard_metrics", "on_workflow_failed"),
        ("repo_health", "on_workflow_failed"),  # Per-repo health tracking
        ("repo_cost", "on_workflow_failed"),  # Per-repo cost tracking
        ("realtime", "on_workflow_failed"),  # Real-time UI push
    ],
    # Control plane events
    "ExecutionPaused": [
        ("workflow_execution_list", "on_execution_paused"),
        ("workflow_execution_detail", "on_execution_paused"),
    ],
    "ExecutionResumed": [
        ("workflow_execution_list", "on_execution_resumed"),
        ("workflow_execution_detail", "on_execution_resumed"),
    ],
    "ExecutionCancelled": [
        ("workflow_execution_list", "on_execution_cancelled"),
        ("workflow_execution_detail", "on_execution_cancelled"),
    ],
    # Session events
    "SessionStarted": [
        ("session_list", "on_session_started"),
        ("dashboard_metrics", "on_session_started"),
        ("realtime", "on_session_started"),  # Real-time UI push
    ],
    "OperationRecorded": [
        ("session_list", "on_operation_recorded"),
        ("realtime", "on_operation_recorded"),  # Real-time UI push
    ],
    "SessionCompleted": [
        ("session_list", "on_session_completed"),
        ("dashboard_metrics", "on_session_completed"),
        ("realtime", "on_session_completed"),  # Real-time UI push
    ],
    # Subagent lifecycle events (from agentic_isolation v0.3.0)
    "SubagentStarted": [
        ("session_list", "on_subagent_started"),
        ("realtime", "on_subagent_started"),  # Real-time UI push
    ],
    "SubagentStopped": [
        ("session_list", "on_subagent_stopped"),
        ("realtime", "on_subagent_stopped"),  # Real-time UI push
    ],
    # Artifact events
    "ArtifactCreated": [
        ("artifact_list", "on_artifact_created"),
        ("dashboard_metrics", "on_artifact_created"),
        ("realtime", "on_artifact_created"),  # Real-time UI push
    ],
    # Observability events (Pattern 2: Event Log + CQRS, see ADR-018)
    # These are observations from syn-collector, not commands
    # Use constants from syn_shared.events for type safety
    TOOL_EXECUTION_STARTED: [
        ("tool_timeline", "on_tool_execution_started"),
    ],
    TOOL_EXECUTION_COMPLETED: [
        ("tool_timeline", "on_tool_execution_completed"),
        ("session_cost", "on_agent_observation"),
        ("execution_cost", "on_agent_observation"),
    ],
    TOOL_BLOCKED: [
        ("tool_timeline", "on_tool_blocked"),
    ],
    TOKEN_USAGE: [
        ("session_cost", "on_agent_observation"),
        ("execution_cost", "on_agent_observation"),
    ],
    # Session summary (end of session with accurate cumulative totals)
    SESSION_SUMMARY: [
        ("session_cost", "on_session_summary"),
        ("execution_cost", "on_session_summary"),
    ],
    # Cost tracking events
    "CostRecorded": [
        ("session_cost", "on_cost_recorded"),
        ("execution_cost", "on_cost_recorded"),
    ],
    "SessionCostFinalized": [
        ("session_cost", "on_session_cost_finalized"),
        ("execution_cost", "on_session_cost_finalized"),
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

        from .realtime import get_realtime_projection

        self._projections = {
            "workflow_list": WorkflowListProjection(self._store),
            "workflow_detail": WorkflowDetailProjection(self._store),
            "workflow_execution_list": WorkflowExecutionListProjection(self._store),
            "workflow_execution_detail": WorkflowExecutionDetailProjection(self._store),
            "session_list": SessionListProjection(self._store),
            "artifact_list": ArtifactListProjection(self._store),
            "dashboard_metrics": DashboardMetricsProjection(self._store),
            "workflow_phase_metrics": WorkflowPhaseMetricsProjection(self._store),
            # Observability projections (Pattern 2: Event Log + CQRS)
            "tool_timeline": ToolTimelineProjection(self._store),
            # Cost tracking projections (now query TimescaleDB directly)
            "session_cost": self._create_session_cost_projection(),
            "execution_cost": ExecutionCostProjection(self._store),
            # TimescaleDB-backed observability projections (CQRS pattern)
            "session_tools": self._create_session_tools_projection(),
            # Organization projections
            "repo_correlation": RepoCorrelationProjection(self._store),
            "repo_health": RepoHealthProjection(self._store),
            "repo_cost": RepoCostProjection(self._store),
            # Real-time projection for WebSocket push (doesn't use store)
            "realtime": get_realtime_projection(),
        }
        self._initialized = True

    def _create_session_tools_projection(self) -> SessionToolsProjection:
        """Create SessionToolsProjection with TimescaleDB access.

        This projection queries TimescaleDB for tool operations.
        See ADR-029: Simplified Event System

        Note: We don't pass the pool here because the store may not be
        initialized yet. The projection will get the pool lazily.
        """
        # Return projection without pool initially - it will get pool lazily
        return SessionToolsProjection(pool=None)

    def _create_session_cost_projection(self) -> SessionCostProjection:
        """Create SessionCostProjection with TimescaleDB access.

        This projection now queries TimescaleDB directly for real-time cost calculation.
        See ADR-029: Simplified Event System
        """
        try:
            from syn_adapters.events import get_event_store

            store = get_event_store()
            # SessionCostProjection needs to be updated to use the new event store
            # For now, pass the pool directly
            return SessionCostProjection(self._store, pool=store.pool)
        except Exception as e:
            # Fallback to event store-based projection if TimescaleDB unavailable
            logger.warning(
                "Could not connect to TimescaleDB for cost projection, "
                "falling back to event store: %s",
                e,
            )
            return SessionCostProjection(self._store)

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
        if not handlers:
            logger.debug("No handlers registered for event type: %s", event_type)

        for projection_name, method_name in handlers:
            projection = self._projections.get(projection_name)
            if projection:
                handler = getattr(projection, method_name, None)
                if handler:
                    try:
                        await handler(event_data)
                    except Exception as e:
                        logger.error(
                            "Error in projection handler",
                            extra={
                                "projection": projection_name,
                                "method": method_name,
                                "event_type": event_type,
                                "error": str(e),
                            },
                            exc_info=True,
                        )

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
    def workflow_execution_list(self) -> WorkflowExecutionListProjection:
        """Get the workflow execution list projection."""
        self._ensure_initialized()
        return self._projections["workflow_execution_list"]

    @property
    def workflow_execution_detail(self) -> WorkflowExecutionDetailProjection:
        """Get the workflow execution detail projection."""
        self._ensure_initialized()
        return self._projections["workflow_execution_detail"]

    # Backward compatibility aliases
    @property
    def execution_list(self) -> WorkflowExecutionListProjection:
        """Alias for workflow_execution_list (deprecated)."""
        return self.workflow_execution_list

    @property
    def execution_detail(self) -> WorkflowExecutionDetailProjection:
        """Alias for workflow_execution_detail (deprecated)."""
        return self.workflow_execution_detail

    @property
    def dashboard_metrics(self) -> DashboardMetricsProjection:
        """Get the dashboard metrics projection."""
        self._ensure_initialized()
        return self._projections["dashboard_metrics"]

    @property
    def workflow_phase_metrics(self) -> WorkflowPhaseMetricsProjection:
        """Get the workflow phase metrics projection."""
        self._ensure_initialized()
        return self._projections["workflow_phase_metrics"]

    # Observability projections (Pattern 2: Event Log + CQRS)
    @property
    def tool_timeline(self) -> ToolTimelineProjection:
        """Get the tool timeline projection."""
        self._ensure_initialized()
        return self._projections["tool_timeline"]

    @property
    def realtime(self) -> Any:
        """Get the real-time projection for WebSocket push."""
        self._ensure_initialized()
        return self._projections["realtime"]

    # Organization projections
    @property
    def repo_correlation(self) -> RepoCorrelationProjection:
        """Get the repo-execution correlation projection."""
        self._ensure_initialized()
        return self._projections["repo_correlation"]

    @property
    def repo_health(self) -> RepoHealthProjection:
        """Get the repo health projection."""
        self._ensure_initialized()
        return self._projections["repo_health"]

    @property
    def repo_cost(self) -> RepoCostProjection:
        """Get the repo cost projection."""
        self._ensure_initialized()
        return self._projections["repo_cost"]

    # Cost tracking projections
    @property
    def session_cost(self) -> SessionCostProjection:
        """Get the session cost projection."""
        self._ensure_initialized()
        return self._projections["session_cost"]

    @property
    def execution_cost(self) -> ExecutionCostProjection:
        """Get the execution cost projection."""
        self._ensure_initialized()
        return self._projections["execution_cost"]

    @property
    def session_tools(self) -> SessionToolsProjection:
        """Get the session tools projection (TimescaleDB-backed)."""
        self._ensure_initialized()
        return self._projections["session_tools"]


@lru_cache
def get_projection_manager() -> ProjectionManager:
    """Get the singleton projection manager instance."""
    return ProjectionManager()


def reset_projection_manager() -> None:
    """Reset the projection manager singleton (for testing)."""
    get_projection_manager.cache_clear()
