"""CLI for AEF Event Collector.

Provides commands for:
- serve: Start the collector service
- watch: Watch files and send events
- sidecar: Combined mode for containers
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import click

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for CLI.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.option("--log-level", default="INFO", help="Log level")
@click.pass_context
def main(ctx: click.Context, log_level: str) -> None:
    """AEF Event Collector CLI.

    Scalable event collection for AI agent observability.
    """
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    setup_logging(log_level)


@main.command()
@click.option("--port", default=8080, help="Port to listen on")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--eventstore-host", default="localhost", help="Event store host")
@click.option("--eventstore-port", default=50051, help="Event store port")
@click.option("--dedup-max-size", default=100000, help="Max dedup cache size")
@click.pass_context
def serve(
    ctx: click.Context,
    port: int,
    host: str,
    eventstore_host: str,
    eventstore_port: int,
    dedup_max_size: int,
) -> None:
    """Start the event collector service.

    Receives batched events from sidecars and writes
    to the event store.
    """
    import uvicorn

    from syn_collector.collector.service import create_app
    from syn_collector.collector.store import InMemoryEventStore

    logger.info(f"Starting collector service on {host}:{port}")
    # TODO: Use eventstore_host and eventstore_port to create real gRPC client
    logger.info(f"Event store: {eventstore_host}:{eventstore_port} (not connected yet)")

    # TODO: Create real event store client when available
    # For now, use in-memory store
    event_store = InMemoryEventStore()

    app = create_app(
        event_store=event_store,
        dedup_max_size=dedup_max_size,
    )

    uvicorn.run(app, host=host, port=port, log_level=ctx.obj["log_level"].lower())


@main.command()
@click.option(
    "--hooks-file",
    required=True,
    type=click.Path(exists=False),
    help="Path to hook events JSONL file",
)
@click.option(
    "--transcript-dir",
    required=True,
    type=click.Path(exists=False),
    help="Directory containing transcript files",
)
@click.option("--collector-url", default="http://localhost:8080", help="Collector service URL")
@click.option("--api-key", envvar="EVENT_COLLECTOR_API_KEY", help="API key for authentication")
@click.option("--batch-size", default=100, help="Events per batch")
@click.option("--batch-interval", default=1000, help="Max ms between flushes")
def watch(
    hooks_file: str,
    transcript_dir: str,
    collector_url: str,
    api_key: str | None,
    batch_size: int,
    batch_interval: int,
) -> None:
    """Watch files and send events to collector.

    Monitors hook events and transcript files, sending
    collected events to the collector service.
    """
    logger.info(f"Starting file watcher: hooks={hooks_file}, transcripts={transcript_dir}")
    logger.info(f"Collector URL: {collector_url}")

    asyncio.run(
        _run_watcher(
            hooks_file=Path(hooks_file),
            transcript_dir=Path(transcript_dir),
            collector_url=collector_url,
            api_key=api_key,
            batch_size=batch_size,
            batch_interval_ms=batch_interval,
        )
    )


@main.command()
@click.option(
    "--hooks-file",
    required=True,
    type=click.Path(exists=False),
    help="Path to hook events JSONL file",
)
@click.option(
    "--transcript-dir",
    required=True,
    type=click.Path(exists=False),
    help="Directory containing transcript files",
)
@click.option("--collector-url", default="http://localhost:8080", help="Collector service URL")
@click.option("--api-key", envvar="EVENT_COLLECTOR_API_KEY", help="API key for authentication")
def sidecar(
    hooks_file: str,
    transcript_dir: str,
    collector_url: str,
    api_key: str | None,
) -> None:
    """Run in sidecar mode for containers.

    Combined watcher with container-friendly defaults.
    """
    logger.info("Starting in sidecar mode")

    asyncio.run(
        _run_watcher(
            hooks_file=Path(hooks_file),
            transcript_dir=Path(transcript_dir),
            collector_url=collector_url,
            api_key=api_key,
            batch_size=50,  # Smaller batches for containers
            batch_interval_ms=500,  # Faster flushes
        )
    )


async def _run_watcher(
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

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Create client and watchers
    async with EventCollectorClient(
        collector_url,
        api_key=api_key,
        batch_size=batch_size,
        batch_interval_ms=batch_interval_ms,
    ) as client:
        hook_watcher = HookWatcher(hooks_file)
        transcript_watcher = TranscriptWatcher(transcript_dir)

        # Watch tasks
        async def watch_hooks() -> None:
            async for event in hook_watcher.watch(from_end=True):
                if shutdown_event.is_set():
                    break
                await client.emit(event)

        async def watch_transcripts() -> None:
            async for event in transcript_watcher.watch(from_end=True):
                if shutdown_event.is_set():
                    break
                await client.emit(event)

        async def periodic_flush() -> None:
            while not shutdown_event.is_set():
                await asyncio.sleep(batch_interval_ms / 1000)
                try:
                    await client.flush()
                except Exception as e:
                    logger.error(f"Flush error: {e}")

        # Run all tasks concurrently
        tasks = [
            asyncio.create_task(watch_hooks()),
            asyncio.create_task(watch_transcripts()),
            asyncio.create_task(periodic_flush()),
        ]

        # Wait for shutdown
        await shutdown_event.wait()

        # Cancel tasks
        for task in tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        # Final flush
        logger.info("Performing final flush...")
        await client.flush()

        logger.info(f"Watcher stopped. Stats: {client.stats}")


if __name__ == "__main__":
    main()
