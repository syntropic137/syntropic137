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
        event_store: Any,
        projections: list[CheckpointedProjection],
        realtime_projection: RealTimeProjection | None = None,
    ) -> None:
        """Initialize the coordinator subscription service.

        Args:
            event_store: Event store client with subscribe() method
            projections: List of CheckpointedProjection instances
            realtime_projection: Optional RealTimeProjection for SSE broadcast
        """
        self._event_store = event_store
        self._projections = projections
        self._realtime_projection = realtime_projection

        # Will be set on start
        self._db_pool: asyncpg.Pool | None = None
        self._checkpoint_store: PostgresCheckpointStore | None = None
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
    event_store: Any,
    projection_store: Any,
    realtime_projection: RealTimeProjection | None = None,
    execution_service: Any = None,
) -> CoordinatorSubscriptionService:
    """Factory to create the coordinator subscription service.

    Args:
        event_store: Event store client
        projection_store: Projection store (for creating projections)
        realtime_projection: Optional RealTimeProjection

    Returns:
        Configured CoordinatorSubscriptionService
    """
    from syn_adapters.projections.trigger_query_projection import TriggerQueryProjection
    from syn_adapters.subscriptions.realtime_adapter import (
        OrganizationListAdapter as _OrganizationListAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        RepoListAdapter as _RepoListAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        SystemListAdapter as _SystemListAdapter,
    )
    from syn_domain.contexts.agent_sessions.slices.list_sessions import SessionListProjection
    from syn_domain.contexts.artifacts.slices.list_artifacts import ArtifactListProjection
    from syn_domain.contexts.github.slices.dispatch_triggered_workflow import (
        WorkflowDispatchProjection,
    )
    from syn_domain.contexts.orchestration.slices.dashboard_metrics import (
        DashboardMetricsProjection,
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
    from syn_domain.contexts.organization._shared.organization_projection import (
        OrganizationProjection,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
    from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection

    # Create all checkpointed projections
    projections: list[CheckpointedProjection] = [
        WorkflowListProjection(projection_store),
        WorkflowDetailProjection(projection_store),
        WorkflowExecutionListProjection(projection_store),
        WorkflowExecutionDetailProjection(projection_store),
        SessionListProjection(projection_store),
        ArtifactListProjection(projection_store),
        DashboardMetricsProjection(projection_store),
        WorkflowDispatchProjection(execution_service=execution_service, store=projection_store),
        TriggerQueryProjection(projection_store),
        # Organization context — namespace-qualified events require adapters
        _OrganizationListAdapter(OrganizationProjection(projection_store)),
        _SystemListAdapter(SystemProjection(projection_store)),
        _RepoListAdapter(RepoProjection(projection_store)),
    ]

    return CoordinatorSubscriptionService(
        event_store=event_store,
        projections=projections,
        realtime_projection=realtime_projection,
    )
