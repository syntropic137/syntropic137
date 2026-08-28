"""AddGlobalClaudePlugin command - add a registered claude plugin to the global singleton (issue #726).

`aggregate_id` is always the singleton id (`global-claude-plugins`); enforced by
the slice handler, not by the command itself.
"""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("AddGlobalClaudePlugin", "Adds a claude plugin to the global registry")
class AddGlobalClaudePluginCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregate_id: str = Field(..., description="Always the singleton id 'global-claude-plugins'")
    name: str
    source_url: str
    version: str
    resolved_sha: str
