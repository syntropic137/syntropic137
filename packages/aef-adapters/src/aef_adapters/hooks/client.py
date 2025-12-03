"""AEF Hook Client - wrapper around agentic_hooks with settings integration.

This module provides a configured HookClient that automatically uses
AEF settings for backend URL, batch size, and flush intervals.

Example:
    from aef_adapters.hooks import get_hook_client

    async with get_hook_client() as client:
        await client.emit(HookEvent(
            event_type=EventType.TOOL_EXECUTION_STARTED,
            session_id="session-123",
        ))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentic_hooks import EventType, HookClient, HookEvent

if TYPE_CHECKING:
    from aef_shared.settings import Settings


@dataclass
class AEFHookClient:
    """Wrapper around HookClient with AEF settings integration.

    This client provides the same interface as HookClient but
    automatically configures itself from AEF settings.

    Attributes:
        _client: The underlying HookClient instance.
        _settings: AEF settings for configuration.
    """

    _client: HookClient
    _settings: Settings | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> AEFHookClient:
        """Create an AEFHookClient from settings.

        Args:
            settings: Optional settings. If not provided, loads from environment.

        Returns:
            Configured AEFHookClient.
        """
        if settings is None:
            from aef_shared.settings import get_settings

            settings = get_settings()

        client = HookClient(
            backend_url=settings.hook_backend_url,
            batch_size=settings.hook_batch_size,
            flush_interval_seconds=settings.hook_flush_interval_seconds,
        )

        return cls(_client=client, _settings=settings)

    async def start(self) -> None:
        """Start the client and background flush task."""
        await self._client.start()

    async def close(self) -> None:
        """Close the client and flush remaining events."""
        await self._client.close()

    async def emit(self, event: HookEvent) -> None:
        """Emit a hook event (buffered, async).

        Args:
            event: Event to emit.
        """
        await self._client.emit(event)

    async def emit_many(self, events: list[HookEvent]) -> None:
        """Emit multiple events at once.

        Args:
            events: Events to emit.
        """
        await self._client.emit_many(events)

    async def flush(self) -> None:
        """Force flush all buffered events."""
        await self._client.flush()

    @property
    def pending_count(self) -> int:
        """Number of events waiting to be flushed."""
        return int(self._client.pending_count)

    async def __aenter__(self) -> AEFHookClient:
        """Enter async context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager."""
        await self.close()


def get_hook_client(settings: Settings | None = None) -> AEFHookClient:
    """Get a configured hook client for AEF.

    This is the primary entry point for getting a hook client.
    The client is configured from AEF settings (environment variables).

    Args:
        settings: Optional settings override.

    Returns:
        Configured AEFHookClient ready for use.

    Example:
        async with get_hook_client() as client:
            await client.emit(HookEvent(
                event_type=EventType.AGENT_REQUEST_STARTED,
                session_id="session-123",
            ))
    """
    return AEFHookClient.from_settings(settings)


# Re-export for convenience
__all__ = [
    "AEFHookClient",
    "EventType",
    "HookClient",
    "HookEvent",
    "get_hook_client",
]
