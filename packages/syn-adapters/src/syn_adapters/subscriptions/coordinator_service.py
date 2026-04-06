"""Coordinator-based subscription service using SubscriptionCoordinator (ADR-014).

This replaces the legacy EventSubscriptionService with the new architecture
that provides per-projection checkpoint tracking.

Architecture:
    Event Store → SubscriptionCoordinator → CheckpointedProjections
                                         └→ RealTimeProjection (side-effect)
                                              │
                                              ▼
                                        SSE Clients
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import asyncpg
from agentic_logging import get_logger
from event_sourcing import (
    CheckpointedProjection,
    PostgresCheckpointStore,
    SubscriptionCoordinator,
)

from syn_adapters.subscriptions.realtime_adapter import (
    RealTimeProjectionAdapter as RealTimeProjectionAdapter,
)
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from event_sourcing.core.checkpoint import ProjectionCheckpointStore

    from syn_adapters.projections.realtime import RealTimeProjection

logger = get_logger(__name__)


class CoordinatorSubscriptionService:
    """Subscription service using SubscriptionCoordinator (ADR-014).

    This service:
    1. Creates a PostgresCheckpointStore for checkpoint persistence
    2. Collects all CheckpointedProjection instances
    3. Wraps RealTimeProjection as a CheckpointedProjection
    4. Runs the SubscriptionCoordinator

    Key benefits over legacy EventSubscriptionService:
    - Per-projection checkpoint tracking
    - Automatic version-based rebuild
    - Proper error handling (no silent failures)
    - Event type filtering for performance
    """

    def __init__(
        self,
        event_store: Any,  # noqa: ANN401
        projections: list[CheckpointedProjection],
        realtime_projection: RealTimeProjection | None = None,
        checkpoint_store: ProjectionCheckpointStore | None = None,
    ) -> None:
        """Initialize the coordinator subscription service.

        Args:
            event_store: Event store client with subscribe() method
            projections: List of CheckpointedProjection instances
            realtime_projection: Optional RealTimeProjection for SSE broadcast
            checkpoint_store: Optional injected checkpoint store (e.g. MemoryCheckpointStore
                for tests). If None, a PostgresCheckpointStore is created on start().
        """
        self._event_store = event_store
        self._projections = projections
        self._realtime_projection = realtime_projection
        self._injected_checkpoint_store = checkpoint_store

        # Will be set on start
        self._db_pool: asyncpg.Pool | None = None
        self._checkpoint_store: ProjectionCheckpointStore | None = None
        self._coordinator: SubscriptionCoordinator | None = None
        self._subscription_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if the subscription is running."""
        return self._running

    def get_status(self) -> dict:
        """Get service status for health checks."""
        return {
            "running": self._running,
            "projection_count": len(self._projections),
            "realtime_enabled": self._realtime_projection is not None,
        }

    async def start(self) -> None:
        """Start the coordinator subscription service."""
        if self._running:
            logger.warning("Coordinator subscription service already running")
            return

        logger.info("Starting coordinator subscription service...")

        if self._injected_checkpoint_store:
            # Use injected checkpoint store (e.g. MemoryCheckpointStore for tests)
            self._checkpoint_store = self._injected_checkpoint_store
            logger.info("Using injected checkpoint store")
        else:
            # Create database pool for checkpoint store (ADR-030)
            settings = get_settings()
            if not settings.syn_observability_db_url:
                raise ValueError(
                    "SYN_OBSERVABILITY_DB_URL must be configured for subscription service. "
                    "Set it in your .env file."
                )
            database_url = str(settings.syn_observability_db_url)
            self._db_pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=10,
            )
            logger.info("Database pool created for checkpoint store")

            # Create checkpoint store (table is created on first operation)
            self._checkpoint_store = PostgresCheckpointStore(self._db_pool)
            logger.info("Checkpoint store initialized")

        # Build projection list (add realtime adapter if configured)
        all_projections = list(self._projections)
        if self._realtime_projection:
            realtime_adapter = RealTimeProjectionAdapter(self._realtime_projection)
            all_projections.append(realtime_adapter)
            logger.info("RealTimeProjection adapter added")

        # Create coordinator
        self._coordinator = SubscriptionCoordinator(
            event_store=self._event_store,
            checkpoint_store=self._checkpoint_store,
            projections=all_projections,
        )

        # Start coordinator in background task
        self._running = True
        self._subscription_task = asyncio.create_task(
            self._run_coordinator(),
            name="coordinator-subscription",
        )

        logger.info(
            "Coordinator subscription service started",
            extra={"projection_count": len(all_projections)},
        )

    async def _run_coordinator(self) -> None:
        """Run the coordinator with exponential-backoff reconnect on error."""
        from syn_adapters.subscriptions.coordinator_helpers import run_coordinator

        await run_coordinator(self)

    async def stop(self) -> None:
        """Stop the coordinator subscription service gracefully."""
        from syn_adapters.subscriptions.coordinator_helpers import stop_coordinator_service

        await stop_coordinator_service(self)


def create_coordinator_service(
    event_store: Any,  # noqa: ANN401
    projection_store: Any,  # noqa: ANN401
    realtime_projection: RealTimeProjection | None = None,
    execution_service: Any = None,  # noqa: ANN401
    checkpoint_store: ProjectionCheckpointStore | None = None,
    pool: asyncpg.Pool | None = None,
) -> CoordinatorSubscriptionService:
    """Factory to create the coordinator subscription service.

    This is the single registry for all checkpointed projections (ADR-055).
    Every projection that must stay in sync with the event store must be
    instantiated in the ``projections`` list below.

    To add a new projection:
      1. Create a CheckpointedProjection subclass in the owning context's slices/
      2. Import it here and add to the ``projections`` list below
      3. Update the fitness test count in ci/fitness/event_sourcing/test_projection_wiring.py
      4. The fitness test will fail with guidance if you forget step 3

    Args:
        event_store: Event store client
        projection_store: Projection store (for creating projections)
        realtime_projection: Optional RealTimeProjection
        execution_service: Optional execution service (required by WorkflowDispatchProjection)
        checkpoint_store: Optional injected checkpoint store (e.g. MemoryCheckpointStore
            for tests). If None, a PostgresCheckpointStore is created on start().
        pool: Optional asyncpg Pool for TimescaleDB direct queries.
            Cost projections use this to bypass empty projection stores
            and read from the actual observability data source (Lane 2).

    Returns:
        Configured CoordinatorSubscriptionService
    """
    from syn_adapters.projections.manager_registry import create_session_cost_projection
    from syn_adapters.projections.trigger_query_projection import TriggerQueryProjection
    from syn_adapters.subscriptions.projection_adapters import (
        ExecutionCostAdapter,
        SessionCostAdapter,
        ToolTimelineAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        OrganizationListAdapter as _OrganizationListAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        RepoCorrelationAdapter as _RepoCorrelationAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        RepoListAdapter as _RepoListAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        SystemListAdapter as _SystemListAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        TriggerHistoryAdapter as _TriggerHistoryAdapter,
    )
    from syn_domain.contexts.agent_sessions.slices.list_sessions import SessionListProjection
    from syn_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineProjection
    from syn_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
    from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
        WorkflowDispatchProjection,
    )
    from syn_domain.contexts.github.slices.trigger_history.projection import (
        TriggerHistoryProjection,
    )
    from syn_domain.contexts.orchestration.slices.dashboard_metrics import (
        DashboardMetricsProjection,
    )
    from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
        ExecutionCostProjection,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
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
    from syn_domain.contexts.organization._shared.organization_projection import (
        OrganizationProjection,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
    from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection
    from syn_domain.contexts.organization.slices.repo_correlation import (
        RepoCorrelationProjection,
    )
    from syn_domain.contexts.organization.slices.repo_cost import RepoCostProjection
    from syn_domain.contexts.organization.slices.repo_health import RepoHealthProjection

    # Create all checkpointed projections (21 total)
    projections: list[CheckpointedProjection] = [
        # --- Orchestration context (AutoDispatchProjection — direct) ---
        WorkflowListProjection(projection_store),
        WorkflowDetailProjection(projection_store),
        WorkflowExecutionListProjection(projection_store),
        WorkflowExecutionDetailProjection(projection_store),
        DashboardMetricsProjection(projection_store),
        WorkflowPhaseMetricsProjection(projection_store),
        ExecutionTodoProjection(store=projection_store),
        WorkflowDispatchProjection(execution_service=execution_service, store=projection_store),
        TriggerQueryProjection(projection_store),
        # --- Agent sessions context ---
        SessionListProjection(projection_store),
        # --- Artifacts context ---
        ArtifactListProjection(projection_store),
        # --- Organization context — namespace-qualified events require adapters ---
        _OrganizationListAdapter(OrganizationProjection(projection_store)),
        _SystemListAdapter(SystemProjection(projection_store)),
        _RepoListAdapter(RepoProjection(projection_store)),
        # Organization insight projections (AutoDispatchProjection — direct)
        RepoHealthProjection(projection_store),
        RepoCostProjection(projection_store, pool=pool),
        # RepoCorrelation handles mixed namespaces (github.* + unnamespaced)
        _RepoCorrelationAdapter(RepoCorrelationProjection(projection_store)),
        # Trigger history — github.TriggerFired → fire log entries
        _TriggerHistoryAdapter(TriggerHistoryProjection(projection_store)),
        # --- Observability projections — plain classes wrapped via adapters ---
        ToolTimelineAdapter(ToolTimelineProjection(projection_store)),
        ExecutionCostAdapter(ExecutionCostProjection(projection_store, pool=pool)),
        SessionCostAdapter(create_session_cost_projection(projection_store)),
    ]

    return CoordinatorSubscriptionService(
        event_store=event_store,
        projections=projections,
        realtime_projection=realtime_projection,
        checkpoint_store=checkpoint_store,
    )
