"""GlobalClaudePluginAdded event - a plugin was added to the global registry (issue #726)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  Pydantic needs runtime types

from event_sourcing import DomainEvent, event


@event("GlobalClaudePluginAdded", "v1")
class GlobalClaudePluginAddedEvent(DomainEvent):
    name: str
    source_url: str
    version: str
    resolved_sha: str
    added_at: datetime
