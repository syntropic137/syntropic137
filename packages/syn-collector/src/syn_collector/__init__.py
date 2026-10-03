"""Syn137 Event Collector - Scalable observability for AI agents.

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

from syn_collector.collector.version import collector_version
from syn_collector.events.types import (
    BatchResponse,
    CollectedEvent,
    EventBatch,
    EventType,
)

#: The installed release, read through the package's one version accessor. This
#: was a hardcoded "0.1.0" that contradicted the very metadata /health and
#: openapi.json already reported, which is the two-homes drift #1380 exists to
#: remove - leaving it here would have kept the defect in the package that
#: claimed to have fixed it.
#:
#: ``None``, never a placeholder string, when the distribution is not installed.
__version__: str | None = collector_version()

__all__ = [
    "BatchResponse",
    "CollectedEvent",
    "EventBatch",
    "EventType",
    "__version__",
]
