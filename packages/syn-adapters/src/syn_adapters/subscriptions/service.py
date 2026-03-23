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
import logging
from datetime import UTC, datetime
from collections.abc import Sequence
from typing import TYPE_CHECKING

from agentic_logging import get_logger

from syn_adapters.subscriptions.position_checkpoint import PositionCheckpoint

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
        """Get detailed status of the subscription service.

        Returns a dictionary with current state information useful for
        debugging and health checks.
        """
        status = {
            "running": self._running,
            "caught_up": self._caught_up,
            "last_position": self._last_position,
            "events_processed": self._events_processed,
            "reconnect_count": self._reconnect_count,
            "last_event_time": self._last_event_time.isoformat() if self._last_event_time else None,
            "last_position_save": self._last_position_save.isoformat()
            if self._last_position_save
            else None,
        }
        logger.debug(
            "[SUBSCRIPTION] Status requested",
            extra=status,
        )
        return status

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
        self._last_position = await self._checkpoint.load()
        await self._checkpoint.validate_consistency(self._last_position)

    async def _save_position(self) -> None:
        """Save current position to projection store."""
        await self._checkpoint.save(self._last_position)
        self._last_position_save = self._checkpoint.last_save_time

    async def _subscription_loop(self) -> None:
        """Main subscription loop with automatic reconnection.

        Runs catch-up first, then switches to live subscription.
        Retries with exponential backoff on failure.
        """
        retry_delay = 1.0
        max_retry_delay = 60.0
        consecutive_failures = 0

        logger.info("[SUBSCRIPTION] Main loop started", extra={"position": self._last_position})

        while not self._stop_event.is_set():
            try:
                if consecutive_failures > 0 or self._reconnect_count > 0:
                    self._reconnect_count += 1
                    logger.info("[SUBSCRIPTION] Reconnecting", extra={"attempt": self._reconnect_count})

                await self._run_catchup()
                consecutive_failures = 0
                retry_delay = 1.0
                self._caught_up = True

                logger.info("[SUBSCRIPTION] Catch-up complete, starting live", extra={"position": self._last_position})
                await self._run_live_subscription()

                # Live subscription exited — reconnect
                self._caught_up = False
                logger.warning("[SUBSCRIPTION] Live stream ended, will reconnect")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                self._caught_up = False
                logger.error("[SUBSCRIPTION] Loop failed", extra={"error": str(e), "retry_delay": retry_delay}, exc_info=True)
                if not self._stop_event.is_set():
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)

        logger.info("[SUBSCRIPTION] Main loop stopped", extra={"position": self._last_position, "events": self._events_processed})
        self._running = False

    async def _run_catchup(self) -> None:
        """Run catch-up subscription to process historical events.

        Uses read_all RPC for reliable batch reading with explicit
        pagination and end-of-batch signals.
        """
        events_in_batch = 0
        from_position = self._last_position + 1 if self._last_position > 0 else 0

        logger.info("[SUBSCRIPTION] Catch-up starting", extra={"from": from_position})

        while not self._stop_event.is_set():
            events, is_end, next_position = await self._event_store.read_all(
                from_global_nonce=from_position,
                max_count=self._batch_size,
                forward=True,
            )

            if not events:
                break

            events_in_batch = await self._process_catchup_batch(events, events_in_batch)

            if events_in_batch >= self._batch_size:
                await self._save_position()
                events_in_batch = 0

            if is_end:
                break
            from_position = next_position

        if events_in_batch > 0:
            await self._save_position()

    async def _process_catchup_batch(self, events: Sequence[object], events_in_batch: int) -> int:
        """Process a batch of catch-up events, advancing position on success.

        Returns updated events_in_batch count.
        Raises RuntimeError if dispatch fails (triggers reconnect).
        """
        for envelope in events:
            if self._stop_event.is_set():
                break

            dispatch_success = await self._dispatch_event(envelope)
            self._last_event_time = datetime.now(UTC)

            # CRITICAL: Only advance position if dispatch succeeded
            if dispatch_success:
                events_in_batch += 1
                if envelope.metadata.global_nonce is not None:  # type: ignore[union-attr]
                    self._last_position = envelope.metadata.global_nonce  # type: ignore[union-attr]
            else:
                nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
                raise RuntimeError(
                    f"Event dispatch failed at position {nonce}. "
                    "Stopping to prevent position drift. Will retry on reconnect."
                )

        return events_in_batch

    async def _run_live_subscription(self) -> None:
        """Run live subscription for real-time events.

        Exits (not raises) when the stream ends, allowing the main loop to reconnect.
        """
        events_since_save = 0
        last_save_time = datetime.now(UTC)
        start_position = self._last_position + 1

        logger.info("[SUBSCRIPTION] Live subscription connecting", extra={"from": start_position})

        async for envelope in self._event_store.subscribe(from_global_nonce=start_position):
            if self._stop_event.is_set():
                return

            self._last_event_time = datetime.now(UTC)
            dispatch_success = await self._dispatch_event(envelope)

            # CRITICAL: Only advance position if dispatch succeeded
            if dispatch_success:
                events_since_save += 1
                if envelope.metadata.global_nonce is not None:
                    self._last_position = envelope.metadata.global_nonce
            else:
                nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)
                raise RuntimeError(f"Event dispatch failed at position {nonce}. Triggering reconnect.")

            # Save position periodically
            now = datetime.now(UTC)
            if events_since_save >= self._batch_size or (now - last_save_time).total_seconds() >= self._position_save_interval:
                await self._save_position()
                events_since_save = 0
                last_save_time = now

    async def _dispatch_event(self, envelope: object) -> bool:
        """Dispatch an event to projections via validated envelope.

        This uses process_event_envelope() which validates that events
        came through the proper event store channel, enforcing event
        sourcing guarantees.

        Args:
            envelope: Event envelope from the event store.

        Returns:
            True if event was successfully dispatched, False if it failed.
            Position should only be advanced if this returns True.
        """
        event_type = getattr(getattr(envelope, "event", None), "event_type", "unknown")
        global_nonce = getattr(getattr(envelope, "metadata", None), "global_nonce", None)

        try:
            # Use the new validated dispatch method
            # This validates provenance and extracts event data
            provenance = await self._projection_manager.process_event_envelope(envelope)
            self._events_processed += 1

            logger.debug(
                "[SUBSCRIPTION] ✅ Event dispatched to projections",
                extra={
                    "event_type": provenance.event_type,
                    "stream_id": provenance.stream_id,
                    "global_nonce": provenance.global_nonce,
                    "total_events_processed": self._events_processed,
                },
            )
            return True

        except ValueError as e:
            # Invalid envelope - log but DON'T advance position
            # This event needs to be investigated, not skipped
            logger.error(
                "[SUBSCRIPTION] ❌ Invalid event envelope - NOT advancing position",
                extra={
                    "error": str(e),
                    "event_type": event_type,
                    "global_nonce": global_nonce,
                },
            )
            return False

        except Exception as e:
            # Dispatch failed - DON'T advance position
            # Event will be retried on next restart
            logger.error(
                "[SUBSCRIPTION] ❌ Failed to dispatch event - NOT advancing position",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "event_type": event_type,
                    "global_nonce": global_nonce,
                },
                exc_info=True,
            )
            return False

    async def health_check(self) -> dict:
        """Perform health check for subscription service.

        This checks for consistency between saved position and the actual
        state of projections. Useful for detecting issues after crashes
        or unexpected shutdowns.

        Returns:
            Dictionary with health status:
            - healthy: bool - True if no issues detected
            - position_saved: int - Last saved position in projection_states
            - position_in_memory: int - Current position in memory
            - position_gap: int - Difference between saved and in-memory
            - warnings: list[str] - Any warnings detected
        """
        warnings_list: list[str] = []

        # Get saved position from store
        try:
            saved_position = await self._projection_store.get_position(SUBSCRIPTION_POSITION_KEY)
            if saved_position is None:
                saved_position = 0
        except Exception as e:
            saved_position = -1
            warnings_list.append(f"Failed to read saved position: {e}")

        # Check for position gaps
        position_gap = abs(self._last_position - (saved_position or 0))

        # If there's a large gap between memory and saved, something might be wrong
        if position_gap > self._batch_size * 2:
            warnings_list.append(
                f"Large gap between saved position ({saved_position}) "
                f"and in-memory position ({self._last_position})"
            )

        # Check if service is running but not processing
        if self._running and not self._caught_up:
            time_since_event = None
            if self._last_event_time:
                time_since_event = (datetime.now(UTC) - self._last_event_time).total_seconds()
                if time_since_event > 60:  # No events for 60+ seconds
                    warnings_list.append(
                        f"Running but no events processed for {time_since_event:.0f}s"
                    )

        # Check reconnect count (many reconnects might indicate problems)
        if self._reconnect_count > 10:
            warnings_list.append(
                f"High reconnect count ({self._reconnect_count}) - "
                "possible connectivity or event store issues"
            )

        health_status = {
            "healthy": len(warnings_list) == 0,
            "position_saved": saved_position,
            "position_in_memory": self._last_position,
            "position_gap": position_gap,
            "events_processed": self._events_processed,
            "reconnect_count": self._reconnect_count,
            "is_running": self._running,
            "is_caught_up": self._caught_up,
            "warnings": warnings_list,
        }

        logger.log(
            logging.WARNING if warnings_list else logging.DEBUG,
            "[SUBSCRIPTION] Health check completed",
            extra=health_status,
        )

        return health_status
