"""StartSession command - represents intent to start a new agent session."""

from __future__ import annotations

from typing import Any

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("StartSession", "Starts a new agent session for tracking execution")
class StartSessionCommand(BaseModel):
    """Command to start a new agent session.

    Sessions track agent execution including token usage,
    operations performed, and associated costs.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (generated if not provided)
    aggregate_id: str | None = None

    # Context
    workflow_id: str = Field(..., description="Workflow this session belongs to")
    phase_id: str = Field(..., description="Phase within the workflow")
    milestone_id: str | None = Field(default=None, description="Optional milestone")

    # Agent info
    agent_provider: str = Field(..., description="Agent provider (claude, openai, mock)")
    agent_model: str | None = Field(default=None, description="Specific model used")

    # Optional metadata
    metadata: dict[str, Any] | None = None
