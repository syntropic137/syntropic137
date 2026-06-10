"""RegisterClaudePlugin command - register a fetched + content-addressed claude plugin (issue #726).

The caller (Phase 5 slice handler) computes `aggregate_id` via
`ClaudePluginRegistrationAggregate.compute_stream_id(source_url, version)` so
identity is deterministic and concurrent registers collide via NoStream.
"""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RegisterClaudePlugin", "Registers a fetched claude plugin tree as a lock entry")
class RegisterClaudePluginCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregate_id: str = Field(..., description="Deterministic stream id from (source_url, version)")
    source_url: str
    version: str
    resolved_sha: str
    name: str
    tree_storage_prefix: str
    # WHY ``dict[str, object]`` (issue #726): plugin.json may contain arrays
    # (``commands``) and nested objects (``dependencies``). Manifest is opaque
    # metadata downstream so we preserve the original shape rather than
    # losing structure to scalar coercion.
    manifest: dict[str, object] = Field(default_factory=dict)
