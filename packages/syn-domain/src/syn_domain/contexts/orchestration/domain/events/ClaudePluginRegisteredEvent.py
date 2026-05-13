"""ClaudePluginRegistered event - a claude plugin tree was content-addressed and stored (issue #726).

Emitted once per (source_url, version) on first successful registration.
Identity-by-key uses sha256(source_url|version) at the aggregate-stream layer.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  Pydantic needs runtime types

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("ClaudePluginRegistered", "v1")
class ClaudePluginRegisteredEvent(DomainEvent):
    source_url: str
    version: str
    resolved_sha: str
    name: str
    tree_storage_prefix: str
    # WHY ``dict[str, object]`` (issue #726): plugin.json may contain arrays
    # and nested objects. Manifest is opaque metadata for downstream consumers
    # so we preserve the original shape rather than collapsing to scalars.
    manifest: dict[str, object] = Field(default_factory=dict)
    registered_at: datetime
