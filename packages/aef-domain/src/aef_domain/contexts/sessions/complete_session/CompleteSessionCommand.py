"""CompleteSession command - marks a session as completed."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("CompleteSession", "Marks an agent session as completed")
class CompleteSessionCommand(BaseModel):
    """Command to complete an agent session.

    Call when the session is finished (successfully or with failure).
    """

    model_config = ConfigDict(frozen=True)

    # Target session
    aggregate_id: str = Field(..., description="Session ID to complete")

    # Outcome
    success: bool = Field(default=True, description="Whether session completed successfully")
    error_message: str | None = Field(default=None, description="Error message if failed")
