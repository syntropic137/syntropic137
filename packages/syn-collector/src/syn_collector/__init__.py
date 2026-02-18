"""AEF Event Collector - Scalable observability for AI agents.

This package provides:
- Event collection service (FastAPI) for receiving batched events
- File watchers for hook JSONL and Claude transcripts
- HTTP client for sidecars to post events
- CLI for running collector and sidecar modes

Example usage:
    # Start collector service
    uv run syn-collector serve --port 8080

    # Start file watcher (sidecar mode)
    uv run syn-collector watch \
        --hooks-file .agentic/analytics/events.jsonl \
        --transcript-dir ~/.claude/projects/
"""

__version__ = "0.1.0"

from syn_collector.events.types import (
    BatchResponse,
    CollectedEvent,
    EventBatch,
    EventType,
)

__all__ = [
    "BatchResponse",
    "CollectedEvent",
    "EventBatch",
    "EventType",
    "__version__",
]
