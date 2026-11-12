"""Projection manager for event dispatch and catch-up.

IMPORTANT: Events should ONLY flow through aggregates and the event store.
Use process_event_envelope() from EventSubscriptionService, NOT dispatch_event().
"""

import logging
from functools import lru_cache
from typing import Any

from event_sourcing import CheckpointedProjection, DomainEvent, EventEnvelope

from syn_adapters.projection_stores import get_projection_store
from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_adapters.projections.manager_event_map import (
    EventProvenance as EventProvenance,
)
from syn_adapters.projections.manager_event_map import (
    Projection as Projection,
)
from syn_adapters.projections.manager_registry import build_projection_registry
from syn_adapters.projections.session_timeline_memory import reset_in_memory_session_timeline
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
from syn_domain.contexts.orchestration.slices.list_evals import EvalListProjection
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

logger = logging.getLogger(__name__)


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
        self._projections: dict[str, Any] = {}  # heterogeneous projection registry
        self._initialized = False
        self._delivered: list[CheckpointedProjection] | None = None

    def _ensure_initialized(self) -> None:
        """Lazily initialize projections."""
        if self._initialized:
            return

        self._projections = build_projection_registry(self._store)
        self._initialized = True

    def get_projection(self, name: str) -> Any:  # noqa: ANN401  # heterogeneous registry
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

    async def process_event_envelope(self, envelope: EventEnvelope[DomainEvent]) -> EventProvenance:
        """Deliver one stored event to these read models, as the coordinator would.

        Each projection receives it through its own ``handle_event``, wrapped
        exactly as the coordinator registers it (#2265), so test mode and
        production cannot route an event differently.

        Raises:
            ValueError: If envelope is not from event store.
        """
        from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed, deliver

        provenance = EventProvenance.from_envelope(envelope)
        self._ensure_initialized()
        if self._delivered is None:
            adapted = (as_checkpointed(p) for p in self._projections.values())
            self._delivered = [p for p in adapted if p is not None]
        await deliver(self._delivered, envelope)
        return provenance

    @property
    def store(self) -> ProjectionStoreProtocol:
        """Access the underlying projection store (ProjectionStoreProtocol)."""
        return self._store

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

    @property
    def eval_list(self) -> EvalListProjection:
        """Get the eval list and detail projection (#967)."""
        self._ensure_initialized()
        return self._projections["evals"]

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
    def realtime(self) -> object:
        """Get the real-time projection for SSE push."""
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
    """Reset the projection manager singleton (for testing).

    The in-memory session timeline goes with it. It is reached through the
    manager and nowhere else, so leaving it behind would carry one test's
    recorded operations into the next.
    """
    get_projection_manager.cache_clear()
    reset_in_memory_session_timeline()
