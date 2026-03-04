"""CLI for Syn137 Event Collector.

Provides commands for:
- serve: Start the collector service
- watch: Watch files and send events
- sidecar: Combined mode for containers
"""

from __future__ import annotations

import asyncio
import logging
import os
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
    """Syn137 Event Collector CLI.

    Scalable event collection for AI agent observability.
    """
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    setup_logging(log_level)


def _resolve_db_url(db_url: str | None) -> str | None:
    """Resolve DB URL from CLI flag or environment.

    Priority: CLI flag > SYN_OBSERVABILITY_DB_URL env var > None
    """
    if db_url:
        return db_url
    return os.environ.get("SYN_OBSERVABILITY_DB_URL")


@main.command()
@click.option("--port", default=8080, help="Port to listen on")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option(
    "--db-url",
    default=None,
    envvar="SYN_OBSERVABILITY_DB_URL",
    help="TimescaleDB connection URL for observability events",
)
@click.option("--dedup-max-size", default=100000, help="Max dedup cache size")
@click.pass_context
def serve(
    ctx: click.Context,
    port: int,
    host: str,
    db_url: str | None,
    dedup_max_size: int,
) -> None:
    """Start the event collector service.

    Receives batched events from sidecars and writes
    to TimescaleDB via AgentEventStore.

    Requires --db-url or SYN_OBSERVABILITY_DB_URL unless
    APP_ENVIRONMENT is test/offline.
    """
    import uvicorn

    from syn_adapters.storage.in_memory import InMemoryStorageError
    from syn_collector.collector.service import create_app
    from syn_collector.collector.store import (
        InMemoryObservabilityStore,
        ObservabilityStoreProtocol,
        TimescaleDBObservabilityStore,
    )

    resolved_url = _resolve_db_url(db_url)
    store: ObservabilityStoreProtocol

    if resolved_url:
        logger.info(f"Starting collector service on {host}:{port} with TimescaleDB")
        store = TimescaleDBObservabilityStore(resolved_url)
    else:
        # Attempt in-memory — will raise InMemoryStorageError if not test/offline
        app_env = os.environ.get("APP_ENVIRONMENT", "production")
        try:
            store = InMemoryObservabilityStore()
            logger.warning(
                f"No DB URL provided — using InMemoryObservabilityStore (APP_ENVIRONMENT={app_env})"
            )
        except InMemoryStorageError as e:
            click.echo(
                f"Error: No database URL provided and in-memory storage not allowed.\n"
                f"  Set --db-url or SYN_OBSERVABILITY_DB_URL for production use.\n"
                f"  Set APP_ENVIRONMENT=test for testing without a database.\n"
                f"  Detail: {e}",
                err=True,
            )
            sys.exit(1)

    app = create_app(
        store=store,
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
