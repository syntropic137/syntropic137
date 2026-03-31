"""UpdatePhasePrompt command - represents intent to update a workflow phase's prompt and config."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("UpdatePhasePrompt", "Updates prompt and config for a workflow phase")
class UpdatePhasePromptCommand(BaseModel):
    """Command to update a workflow phase's prompt template and optional config.

    Uses @command decorator for VSA discovery.
    Commands represent intent - what we want to do.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (required — workflow must already exist)
    aggregate_id: str = Field(..., min_length=1)

    # Target phase within the workflow
    phase_id: str = Field(..., min_length=1)

    # Updated prompt content (required, non-empty)
    prompt_template: str = Field(..., min_length=1)

    # Optional config overrides (None = keep existing value)
    model: str | None = None
    timeout_seconds: int | None = None
    allowed_tools: list[str] | None = None
