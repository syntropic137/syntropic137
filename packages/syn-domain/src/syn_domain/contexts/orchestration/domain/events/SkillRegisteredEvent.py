"""SkillRegistered event - a skill tree was content-addressed and stored (issue #772).

Emitted once per (source_url, version, skill_name) on first successful
registration. Identity-by-key uses sha256(source_url|version|skill_name) at
the aggregate-stream layer. Mirrors ClaudePluginRegisteredEvent (issue #726).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  Pydantic needs runtime types

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration._shared.event_refs.value_objects import (
    SkillManifest,  # noqa: TC001 - needed at runtime for Pydantic field validation
)


@event("SkillRegistered", "v1")
class SkillRegisteredEvent(DomainEvent):
    source_url: str
    version: str
    resolved_sha: str
    skill_name: str
    tree_storage_prefix: str
    # WHY SkillManifest (issue #772): SKILL.md frontmatter is opaque metadata
    # downstream so we preserve the original shape rather than collapsing to
    # scalars.
    manifest: SkillManifest = Field(default_factory=dict)
    registered_at: datetime
