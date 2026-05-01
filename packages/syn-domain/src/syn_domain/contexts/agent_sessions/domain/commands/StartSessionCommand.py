"""StartSession command - represents intent to start a new agent session."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("StartSession", "Starts a new agent session for tracking execution")
class StartSessionCommand(BaseModel):
    """Command to start a new agent session.

    Sessions track agent execution including token usage,
    operations performed, and associated costs.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (auto-generated UUID if not provided)
    aggregate_id: str = Field(default_factory=lambda: str(uuid4()))

    # Context
    workflow_id: str = Field(..., description="Workflow this session belongs to")
    execution_id: str | None = Field(default=None, description="Workflow execution/run ID")
    phase_id: str = Field(..., description="Phase within the workflow")
    milestone_id: str | None = Field(default=None, description="Optional milestone")

    # Agent info
    agent_provider: str = Field(..., description="Agent provider (claude, openai, mock)")
    agent_model: str | None = Field(default=None, description="Specific model used")

    # Repository context (owner/repo slugs from the workflow execution)
    repos: list[str] = Field(default_factory=list, description="Repos this session has access to")

    # Optional metadata
    metadata: dict[str, Any] | None = None
