"""RegisterSkill command - register a fetched + content-addressed skill (issue #772).

The caller (register_skill slice handler) computes `aggregate_id` via
`SkillRegistrationAggregate.compute_stream_id(source_url, version, skill_name)`
so identity is deterministic and concurrent registers collide via NoStream.
Mirrors RegisterClaudePluginCommand (issue #726).
"""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.orchestration._shared.skill_ref import (
    SkillManifest,  # noqa: TC001 - needed at runtime for Pydantic field validation
)


@command("RegisterSkill", "Registers a fetched skill tree as a lock entry")
class RegisterSkillCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregate_id: str = Field(
        ..., description="Deterministic stream id from (source_url, version, skill_name)"
    )
    source_url: str
    version: str
    resolved_sha: str
    skill_name: str
    tree_storage_prefix: str
    # WHY SkillManifest (issue #772): SKILL.md frontmatter is opaque metadata
    # downstream so we preserve the original shape rather than losing
    # structure to scalar coercion.
    manifest: SkillManifest = Field(default_factory=dict)
