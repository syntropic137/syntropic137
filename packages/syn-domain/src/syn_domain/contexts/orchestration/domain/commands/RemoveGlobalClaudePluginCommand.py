"""RemoveGlobalClaudePlugin command - remove a plugin from the global singleton (issue #726)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RemoveGlobalClaudePlugin", "Removes a claude plugin from the global registry")
class RemoveGlobalClaudePluginCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregate_id: str = Field(..., description="Always the singleton id 'global-claude-plugins'")
    name: str
