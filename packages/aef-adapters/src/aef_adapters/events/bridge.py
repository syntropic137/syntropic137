"""Event bridge for connecting hook events to AEF event store.

The EventBridge orchestrates the flow from hook events (JSONL) to
domain events in the AEF event store:

1. Read hook events from JSONL files (batch or real-time)
2. Translate to domain events
3. Append to event store
4. Optionally publish for projections

This enables the agentic-primitives hook system to feed into
AEF's event-sourced architecture.

Example:
    from aef_adapters.events import EventBridge
    from aef_adapters.storage import PostgresEventStore

    async with get_pool() as pool:
        store = PostgresEventStore(pool)
        bridge = EventBridge(store)

        # Process existing events
        count = await bridge.process_file(
            Path(".agentic/analytics/events.jsonl")
        )
        print(f"Processed {count} events")

        # Watch for new events
        await bridge.watch(
            Path(".agentic/analytics/events.jsonl"),
            callback=on_event,
        )
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING, Any, Protocol

from aef_adapters.events.translator import DomainEvent, HookToDomainTranslator
from aef_adapters.events.watcher import JSONLWatcher

if TYPE_CHECKING:
    from agentic_hooks import HookEvent

logger = logging.getLogger(__name__)


class EventStoreProtocol(Protocol):
    """Protocol for event stores that can receive domain events."""

    async def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        event_data: dict[str, Any],
        version: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append an event to the store."""
        ...


# Type alias for event callbacks
EventCallback = Callable[[DomainEvent], Any]


class EventBridge:
    """Bridge hook events to AEF event store.

    Reads hook events from JSONL files and translates them to
    domain events for storage in the AEF event store.

    The bridge maintains position tracking for resumable processing
    and supports both batch and real-time modes.

    Attributes:
        event_store: The event store to append events to.
        translator: Hook to domain event translator.
    """

    def __init__(
        self,
        event_store: EventStoreProtocol | None = None,
        *,
        translator: HookToDomainTranslator | None = None,
        include_raw_event: bool = False,
    ) -> None:
        """Initialize the event bridge.

        Args:
            event_store: Event store for appending domain events.
                If None, events are translated but not stored.
            translator: Custom translator instance.
            include_raw_event: Include raw hook event in metadata.
        """
        self._event_store = event_store
        self._translator = translator or HookToDomainTranslator(
            include_raw_event=include_raw_event,
        )
        self._positions: dict[Path, int] = {}
        self._running = False

    async def process_file(
        self,
        path: Path,
        *,
        from_position: int | None = None,
        callback: EventCallback | None = None,
    ) -> tuple[int, int]:
        """Process events from a JSONL file.

        Reads all events from the file (or from a specific position),
        translates them, and optionally stores them.

        Args:
            path: Path to the JSONL file.
            from_position: Start from this byte position.
            callback: Optional callback for each processed event.

        Returns:
            Tuple of (events_processed, new_position).
        """
        watcher = JSONLWatcher(path)

        # Use stored position or provided position
        position = from_position
        if position is None:
            position = self._positions.get(path, 0)

        hook_events, new_position = await watcher.read_from(position)

        events_processed = 0
        for hook_event in hook_events:
            domain_event = self._translator.translate(hook_event)

            # Store in event store if configured
            if self._event_store is not None:
                await self._store_event(domain_event)

            # Call callback if provided
            if callback is not None:
                result = callback(domain_event)
                if asyncio.iscoroutine(result):
                    await result

            events_processed += 1

        # Update stored position
        self._positions[path] = new_position

        logger.info(
            f"Processed {events_processed} events from {path}",
            extra={
                "path": str(path),
                "events_processed": events_processed,
                "new_position": new_position,
            },
        )

        return events_processed, new_position

    async def watch(
        self,
        path: Path,
        *,
        callback: EventCallback | None = None,
        process_existing: bool = False,
    ) -> None:
        """Watch a file for new events.

        Continuously monitors the file and processes new events
        as they are appended.

        Args:
            path: Path to the JSONL file to watch.
            callback: Callback for each new event.
            process_existing: Process existing events first.
        """
        watcher = JSONLWatcher(path)

        self._running = True
        logger.info(f"Starting event bridge watch on {path}")

        try:
            async for hook_event in watcher.tail(from_end=not process_existing):
                if not self._running:
                    break

                domain_event = self._translator.translate(hook_event)

                # Store in event store if configured
                if self._event_store is not None:
                    await self._store_event(domain_event)

                # Call callback if provided
                if callback is not None:
                    result = callback(domain_event)
                    if asyncio.iscoroutine(result):
                        await result

        except asyncio.CancelledError:
            logger.info("Event bridge watch cancelled")
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop watching for events."""
        self._running = False

    async def _store_event(self, event: DomainEvent) -> str:
        """Store a domain event in the event store.

        Args:
            event: The domain event to store.

        Returns:
            The event ID.
        """
        if self._event_store is None:
            return event.event_id

        return await self._event_store.append(
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            event_type=event.event_type,
            event_data=event.event_data,
            version=event.version,
            metadata=event.metadata,
        )

    def get_position(self, path: Path) -> int:
        """Get the stored position for a file.

        Args:
            path: Path to the file.

        Returns:
            Byte position (0 if not tracked).
        """
        return self._positions.get(path, 0)

    def set_position(self, path: Path, position: int) -> None:
        """Set the position for a file.

        Useful for resuming from a checkpoint.

        Args:
            path: Path to the file.
            position: Byte position to set.
        """
        self._positions[path] = position

    def translate(self, hook_event: HookEvent) -> DomainEvent:
        """Translate a single hook event to domain event.

        Useful for manual event processing without file I/O.

        Args:
            hook_event: The hook event to translate.

        Returns:
            The translated domain event.
        """
        return self._translator.translate(hook_event)

    @property
    def is_running(self) -> bool:
        """Check if the bridge is currently watching."""
        return self._running
