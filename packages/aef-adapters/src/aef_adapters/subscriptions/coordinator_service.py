"""Coordinator-based subscription service using SubscriptionCoordinator (ADR-014).

This replaces the legacy EventSubscriptionService with the new architecture
that provides per-projection checkpoint tracking.

Architecture:
    Event Store → SubscriptionCoordinator → CheckpointedProjections
                                         └→ RealTimeProjection (side-effect)
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncpg
from agentic_logging import get_logger
from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    PostgresCheckpointStore,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
    SubscriptionCoordinator,
)

from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from aef_adapters.projections.realtime import RealTimeProjection

logger = get_logger(__name__)


class RealTimeProjectionAdapter(CheckpointedProjection):
    """Adapter to make RealTimeProjection work with SubscriptionCoordinator.

    This wraps the RealTimeProjection (which broadcasts to WebSocket clients)
    as a CheckpointedProjection. Since RealTimeProjection doesn't persist data,
    we always return SKIP but still call the handlers for broadcasting.

    The checkpoint is saved but only to track position - no data is persisted.
    """

    PROJECTION_NAME = "realtime_websocket"
    VERSION = 1

    def __init__(self, realtime_projection: RealTimeProjection) -> None:
        self._realtime = realtime_projection

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        """Subscribe to all events for WebSocket broadcast."""
        return {
            "WorkflowExecutionStarted",
            "PhaseStarted",
            "PhaseCompleted",
            "WorkflowCompleted",
            "WorkflowFailed",
            "SessionStarted",
            "OperationRecorded",
            "SessionCompleted",
            "ArtifactCreated",
        }

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        """Forward events to RealTimeProjection for WebSocket broadcast."""
        event_type = envelope.event.event_type
        event_data = envelope.event.payload
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            # Map event type to handler method
            handler_name = f"on_{self._to_snake_case(event_type)}"
            handler = getattr(self._realtime, handler_name, None)

            if handler:
                await handler(event_data)
                logger.debug(
                    "Broadcasted event to WebSocket clients",
                    extra={
                        "event_type": event_type,
                        "handler": handler_name,
                    },
                )

            # Save checkpoint - we don't persist data, but track position
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception as e:
            logger.error(
                "Error broadcasting to WebSocket",
                extra={"event_type": event_type, "error": str(e)},
                exc_info=True,
            )
            # Don't fail the projection for WebSocket errors
            return ProjectionResult.SKIP

    def _to_snake_case(self, name: str) -> str:
        """Convert CamelCase to snake_case."""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


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
            realtime_projection: Optional RealTimeProjection for WebSocket broadcast
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

        # Create database pool for checkpoint store
        settings = get_settings()
        database_url = str(settings.database_url)
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
        """Run the coordinator with error handling."""
        assert self._coordinator is not None, "Coordinator not initialized"
        try:
            await self._coordinator.start()
        except asyncio.CancelledError:
            logger.info("Coordinator subscription cancelled")
            raise
        except Exception as e:
            logger.error(
                "Coordinator subscription error",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    async def stop(self) -> None:
        """Stop the coordinator subscription service gracefully."""
        if not self._running:
            return

        logger.info("Stopping coordinator subscription service...")
        self._running = False

        if self._coordinator:
            await self._coordinator.stop()

        if self._subscription_task:
            self._subscription_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._subscription_task

        # Close database pool
        if self._db_pool:
            await self._db_pool.close()
            logger.info("Checkpoint database pool closed")

        logger.info("Coordinator subscription service stopped")


def create_coordinator_service(
    event_store: Any,
    projection_store: Any,
    realtime_projection: RealTimeProjection | None = None,
) -> CoordinatorSubscriptionService:
    """Factory to create the coordinator subscription service.

    Args:
        event_store: Event store client
        projection_store: Projection store (for creating projections)
        realtime_projection: Optional RealTimeProjection

    Returns:
        Configured CoordinatorSubscriptionService
    """
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

    # Create all checkpointed projections
    projections: list[CheckpointedProjection] = [
        WorkflowListProjection(projection_store),
        WorkflowDetailProjection(projection_store),
        WorkflowExecutionListProjection(projection_store),
        WorkflowExecutionDetailProjection(projection_store),
        SessionListProjection(projection_store),
        ArtifactListProjection(projection_store),
        DashboardMetricsProjection(projection_store),
    ]

    return CoordinatorSubscriptionService(
        event_store=event_store,
        projections=projections,
        realtime_projection=realtime_projection,
    )
