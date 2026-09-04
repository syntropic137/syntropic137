"""MarkAgentLaunched command - records that an agent process was launched."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command(
    "MarkAgentLaunched",
    "Records that a session's agent process was actually launched",
)
class MarkAgentLaunchedCommand(BaseModel):
    """Command to record that an agent process existed for a session.

    Issued at the first observable sign of the process itself - not when the
    orchestrator decides to start one. Dispatch is an intention and can still
    be falsified by anything between the decision and the process; the point
    of this fact is that it cannot (#1047, #1065).

    Its absence at completion time is what lets a failed session be reported
    as never having run an agent, so recording it early would produce exactly
    the false statement the fact exists to prevent, in the other direction.
    """

    model_config = ConfigDict(frozen=True)

    # Target session
    aggregate_id: str = Field(..., description="Session ID whose agent was launched")
