"""Async watcher runner for hook and transcript file monitoring.

Extracted from cli.py to reduce module complexity.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


async def _create_watch_task(
    watcher: object,
    client: object,
    shutdown_event: asyncio.Event,
) -> None:
    """Run a single watcher, emitting events to the client until shutdown.

    Args:
        watcher: A BaseWatcher instance with a ``watch()`` async iterator.
        client: An EventCollectorClient with an ``emit()`` method.
        shutdown_event: Signals graceful shutdown.
    """
    async for event in watcher.watch(from_end=True):  # type: ignore[attr-defined]
        if shutdown_event.is_set():
            break
        await client.emit(event)  # type: ignore[attr-defined]


async def _run_periodic_flush(
    client: object,
    interval_ms: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically flush the client buffer until shutdown.

    Args:
        client: An EventCollectorClient with a ``flush()`` method.
        interval_ms: Milliseconds between flush attempts.
        shutdown_event: Signals graceful shutdown.
    """
    while not shutdown_event.is_set():
        await asyncio.sleep(interval_ms / 1000)
        try:
            await client.flush()  # type: ignore[attr-defined]
        except Exception as e:
            logger.error(f"Flush error: {e}")


async def run_watcher(
    hooks_file: Path,
    transcript_dir: Path,
    collector_url: str,
    api_key: str | None,
    batch_size: int,
    batch_interval_ms: int,
) -> None:
    """Run the file watcher with HTTP client.

    Args:
        hooks_file: Path to hook events JSONL
        transcript_dir: Directory with transcript files
        collector_url: Collector service URL
        api_key: Optional API key
        batch_size: Events per batch
        batch_interval_ms: Max ms between flushes
    """
    from syn_collector.client.http import EventCollectorClient
    from syn_collector.watcher.hooks import HookWatcher
    from syn_collector.watcher.transcript import TranscriptWatcher

    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    async with EventCollectorClient(
        collector_url,
        api_key=api_key,
        batch_size=batch_size,
        batch_interval_ms=batch_interval_ms,
    ) as client:
        hook_watcher = HookWatcher(hooks_file)
        transcript_watcher = TranscriptWatcher(transcript_dir)

        tasks = [
            asyncio.create_task(_create_watch_task(hook_watcher, client, shutdown_event)),
            asyncio.create_task(_create_watch_task(transcript_watcher, client, shutdown_event)),
            asyncio.create_task(_run_periodic_flush(client, batch_interval_ms, shutdown_event)),
        ]

        await shutdown_event.wait()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Performing final flush...")
        await client.flush()
        logger.info(f"Watcher stopped. Stats: {client.stats}")
