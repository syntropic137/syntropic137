"""GlobalClaudePluginRemoved event - a plugin was removed from the global registry (issue #726)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  Pydantic needs runtime types

from event_sourcing import DomainEvent, event


@event("GlobalClaudePluginRemoved", "v1")
class GlobalClaudePluginRemovedEvent(DomainEvent):
    name: str
    removed_at: datetime
