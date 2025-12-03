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
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentic_logging import get_logger

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

    from aef_adapters.projection_stores import ProjectionStoreProtocol
    from aef_adapters.projections import ProjectionManager

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
    ) -> None:
        """Initialize the subscription service.

        Args:
            event_store_client: Event store client for subscriptions.
            projection_manager: Manager to dispatch events to projections.
            projection_store: Store for persisting subscription position.
            batch_size: Number of events to process before saving position.
            position_save_interval: Seconds between position saves during live.
        """
        self._event_store = event_store_client
        self._projection_manager = projection_manager
        self._projection_store = projection_store
        self._batch_size = batch_size
        self._position_save_interval = position_save_interval

        # State
        self._running = False
        self._caught_up = False
        self._last_position: int = 0
        self._events_processed: int = 0
        self._last_position_save: datetime | None = None

        # Background task
        self._subscription_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

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

    async def start(self) -> None:
        """Start the subscription service.

        This loads the last position and starts the subscription loop
        as a background task.
        """
        if self._running:
            logger.warning("Subscription service already running")
            return

        logger.info("Starting event subscription service...")

        # Load last position from projection store
        await self._load_position()

        # Reset state
        self._stop_event.clear()
        self._running = True
        self._caught_up = False
        self._events_processed = 0

        # Start subscription loop as background task
        self._subscription_task = asyncio.create_task(
            self._subscription_loop(),
            name="event-subscription-loop",
        )

        logger.info(
            "Event subscription service started",
            extra={"from_position": self._last_position},
        )

    async def stop(self) -> None:
        """Stop the subscription service gracefully.

        This signals the subscription to stop, waits for cleanup,
        and saves the final position.
        """
        if not self._running:
            logger.warning("Subscription service not running")
            return

        logger.info("Stopping event subscription service...")

        # Signal stop
        self._stop_event.set()
        self._running = False

        # Wait for task to complete
        if self._subscription_task:
            try:
                await asyncio.wait_for(self._subscription_task, timeout=5.0)
            except TimeoutError:
                logger.warning("Subscription task did not stop in time, cancelling")
                self._subscription_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._subscription_task

        # Save final position
        await self._save_position()

        logger.info(
            "Event subscription service stopped",
            extra={
                "last_position": self._last_position,
                "events_processed": self._events_processed,
            },
        )

    async def _load_position(self) -> None:
        """Load last processed position from projection store."""
        try:
            position = await self._projection_store.get_position(SUBSCRIPTION_POSITION_KEY)
            if position is not None:
                self._last_position = position
                logger.info(
                    "Loaded subscription position",
                    extra={"position": self._last_position},
                )
            else:
                self._last_position = 0
                logger.info("No previous subscription position found, starting from 0")
        except Exception as e:
            logger.warning(
                "Failed to load subscription position, starting from 0",
                extra={"error": str(e)},
            )
            self._last_position = 0

    async def _save_position(self) -> None:
        """Save current position to projection store."""
        try:
            await self._projection_store.set_position(
                SUBSCRIPTION_POSITION_KEY,
                self._last_position,
            )
            self._last_position_save = datetime.now(UTC)
            logger.debug(
                "Saved subscription position",
                extra={"position": self._last_position},
            )
        except Exception as e:
            logger.error(
                "Failed to save subscription position",
                extra={"error": str(e), "position": self._last_position},
            )

    async def _subscription_loop(self) -> None:
        """Main subscription loop.

        This runs catch-up first, then switches to live subscription.
        """
        try:
            # Phase 1: Catch-up
            logger.info("Starting catch-up phase...")
            await self._run_catchup()

            self._caught_up = True
            logger.info(
                "Catch-up complete, switching to live subscription",
                extra={
                    "position": self._last_position,
                    "events_processed": self._events_processed,
                },
            )

            # Phase 2: Live subscription
            await self._run_live_subscription()

        except asyncio.CancelledError:
            logger.info("Subscription loop cancelled")
            raise
        except Exception as e:
            logger.exception(
                "Subscription loop failed",
                extra={"error": str(e)},
            )
            self._running = False

    async def _run_catchup(self) -> None:
        """Run catch-up subscription to process historical events."""
        events_in_batch = 0

        while not self._stop_event.is_set():
            # Read batch of events
            events = await self._event_store.read_all_events_from(
                after_global_nonce=self._last_position,
                limit=self._batch_size,
            )

            if not events:
                # No more events, catch-up complete
                break

            # Process events
            for envelope in events:
                if self._stop_event.is_set():
                    break

                await self._dispatch_event(envelope)
                events_in_batch += 1

                # Update position
                if envelope.metadata.global_nonce is not None:
                    self._last_position = envelope.metadata.global_nonce

            # Save position periodically during catch-up
            if events_in_batch >= self._batch_size:
                await self._save_position()
                events_in_batch = 0
                logger.debug(
                    "Catch-up progress",
                    extra={
                        "position": self._last_position,
                        "events_processed": self._events_processed,
                    },
                )

        # Final save after catch-up
        if events_in_batch > 0:
            await self._save_position()

    async def _run_live_subscription(self) -> None:
        """Run live subscription for real-time events."""
        events_since_save = 0
        last_save_time = datetime.now(UTC)

        # Start subscription from current position + 1 (since we've processed up to current)
        async for envelope in self._event_store.subscribe(
            from_global_nonce=self._last_position + 1
        ):
            if self._stop_event.is_set():
                break

            await self._dispatch_event(envelope)
            events_since_save += 1

            # Update position
            if envelope.metadata.global_nonce is not None:
                self._last_position = envelope.metadata.global_nonce

            # Save position periodically
            now = datetime.now(UTC)
            should_save = (
                events_since_save >= self._batch_size
                or (now - last_save_time).total_seconds() >= self._position_save_interval
            )

            if should_save:
                await self._save_position()
                events_since_save = 0
                last_save_time = now

    async def _dispatch_event(self, envelope: object) -> None:
        """Dispatch an event to projections via validated envelope.

        This uses process_event_envelope() which validates that events
        came through the proper event store channel, enforcing event
        sourcing guarantees.

        Args:
            envelope: Event envelope from the event store.
        """
        try:
            # Use the new validated dispatch method
            # This validates provenance and extracts event data
            provenance = await self._projection_manager.process_event_envelope(envelope)
            self._events_processed += 1

            logger.debug(
                "Dispatched event to projections",
                extra={
                    "event_type": provenance.event_type,
                    "stream_id": provenance.stream_id,
                    "global_nonce": provenance.global_nonce,
                },
            )

        except ValueError as e:
            # Invalid envelope - log but continue
            logger.warning(
                "Invalid event envelope",
                extra={"error": str(e)},
            )

        except Exception as e:
            # Log error but continue processing
            # Don't let one bad event break the entire subscription
            logger.error(
                "Failed to dispatch event to projections",
                extra={
                    "error": str(e),
                    "event_type": getattr(
                        getattr(envelope, "event", None), "event_type", "unknown"
                    ),
                },
                exc_info=True,
            )
