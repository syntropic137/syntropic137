"""CompleteSession command - marks a session as completed."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions._shared.value_objects import SessionStatus  # noqa: TC001


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
    final_status: SessionStatus | None = Field(
        default=None,
        description="Override final status (e.g. CANCELLED). Defaults to COMPLETED/FAILED from success flag.",
    )
