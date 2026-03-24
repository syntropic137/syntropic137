"""Event subscription service for projection updates.

This service manages the lifecycle of event store subscriptions and dispatches
events to projections. It implements the catch-up subscription with live tailing
pattern.

Architecture:
    1. On start: Load last processed position from projection_states
    2. Catch-up: Read all events from last position to current
    3. Live: Keep subscription open and process events as they arrive
    4. Position: Periodically save position to projection_states
    5. On stop: Flush pending position updates and clean up
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.position_checkpoint import PositionCheckpoint
from syn_adapters.subscriptions.service_catchup import run_catchup
from syn_adapters.subscriptions.service_live import (
    dispatch_event,
    run_live_subscription,
    subscription_loop,
)

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

    from syn_adapters.projection_stores import ProjectionStoreProtocol
    from syn_adapters.projections import ProjectionManager

logger = get_logger(__name__)

# Projection state key for global subscription position
SUBSCRIPTION_POSITION_KEY = "global_subscription"


class EventSubscriptionService:
    """Manages event store subscriptions for projection updates.

    This service:
    1. Starts a catch-up subscription from last known position
    2. Dispatches events to ProjectionManager
    3. Tracks position in projection_states table
    4. Keeps subscription alive for real-time updates
    """

    def __init__(
        self,
        event_store_client: EventStoreClient,
        projection_manager: ProjectionManager,
        projection_store: ProjectionStoreProtocol,
        batch_size: int = 100,
        position_save_interval: int = 10,
        checkpoint: PositionCheckpoint | None = None,
    ) -> None:
        """Initialize the subscription service.

        Args:
            event_store_client: Event store client for subscriptions.
            projection_manager: Manager to dispatch events to projections.
            projection_store: Store for persisting subscription position.
            batch_size: Number of events to process before saving position.
            position_save_interval: Seconds between position saves during live.
            checkpoint: Optional position checkpoint for persistence and drift detection.
        """
        self._event_store = event_store_client
        self._projection_manager = projection_manager
        self._projection_store = projection_store
        self._batch_size = batch_size
        self._position_save_interval = position_save_interval
        self._checkpoint = checkpoint or PositionCheckpoint(
            projection_store, SUBSCRIPTION_POSITION_KEY
        )

        # State
        self._running = False
        self._caught_up = False
        self._last_position: int = 0
        self._events_processed: int = 0
        self._last_position_save: datetime | None = None
        self._reconnect_count: int = 0
        self._last_event_time: datetime | None = None

        # Background task
        self._subscription_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        logger.debug(
            "[SUBSCRIPTION] Service initialized",
            extra={
                "batch_size": batch_size,
                "position_save_interval": position_save_interval,
            },
        )

    @property
    def is_running(self) -> bool:
        """Check if subscription is running."""
        return self._running

    @property
    def is_caught_up(self) -> bool:
        """Check if caught up with live events."""
        return self._caught_up

    @property
    def last_position(self) -> int:
        """Get last processed global nonce."""
        return self._last_position

    @property
    def events_processed(self) -> int:
        """Get total events processed since start."""
        return self._events_processed

    @property
    def reconnect_count(self) -> int:
        """Get number of reconnection attempts."""
        return self._reconnect_count

    @property
    def last_event_time(self) -> datetime | None:
        """Get timestamp of last received event."""
        return self._last_event_time

    def get_status(self) -> dict:
        """Get detailed status of the subscription service."""
        from syn_adapters.subscriptions.service_helpers import get_status

        return get_status(self)

    async def start(self) -> None:
        """Start the subscription service.

        This loads the last position and starts the subscription loop
        as a background task.
        """
        if self._running:
            logger.warning("[SUBSCRIPTION] Service already running, ignoring start request")
            return

        logger.info("[SUBSCRIPTION] 🚀 Starting event subscription service...")

        # Load last position from projection store
        await self._load_position()

        # Reset state
        self._stop_event.clear()
        self._running = True
        self._caught_up = False
        self._events_processed = 0
        self._reconnect_count = 0

        logger.info(
            "[SUBSCRIPTION] ✅ Loaded checkpoint position",
            extra={
                "last_position": self._last_position,
                "will_start_from": self._last_position + 1 if self._last_position > 0 else 0,
            },
        )

        # Start subscription loop as background task
        self._subscription_task = asyncio.create_task(
            self._subscription_loop(),
            name="event-subscription-loop",
        )

        logger.info(
            "[SUBSCRIPTION] ✅ Background task started",
            extra={
                "task_name": "event-subscription-loop",
                "from_position": self._last_position,
            },
        )

    async def stop(self) -> None:
        """Stop the subscription service gracefully."""
        from syn_adapters.subscriptions.service_helpers import stop_service

        await stop_service(self)

    async def _load_position(self) -> None:
        """Load last processed position from projection store."""
        self._last_position = await self._checkpoint.load()
        await self._checkpoint.validate_consistency(self._last_position)

    async def _save_position(self) -> None:
        """Save current position to projection store."""
        await self._checkpoint.save(self._last_position)
        self._last_position_save = self._checkpoint.last_save_time

    async def _subscription_loop(self) -> None:
        """Main subscription loop with automatic reconnection."""
        await subscription_loop(self)

    async def _run_catchup(self) -> None:
        """Run catch-up subscription to process historical events."""
        await run_catchup(self)

    async def _run_live_subscription(self) -> None:
        """Run live subscription for real-time events."""
        await run_live_subscription(self)

    async def _dispatch_event(self, envelope: object) -> bool:
        """Dispatch an event to projections via validated envelope."""
        return await dispatch_event(self, envelope)

    async def health_check(self) -> dict:
        """Perform health check for subscription service."""
        from syn_adapters.subscriptions.service_health import health_check

        return await health_check(self)
