"""MarkAgentLaunched command - records that an agent process was launched."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command(
    "MarkAgentLaunched",
    "Records that a session's agent process was actually launched",
)
class MarkAgentLaunchedCommand(BaseModel):
    """Command to record that the agent process for a session was launched.

    Call this once, right before the agent is invoked - after workspace
    provisioning succeeds but before the CLI process is started. This is
    the domain fact that distinguishes a session that died before its
    agent ever ran (e.g. provisioning failure) from one whose agent ran
    and later failed (#1047, #1065). Token counts cannot make that
    distinction: both cases can legitimately have zero recorded tokens.
    """

    model_config = ConfigDict(frozen=True)

    # Target session
    aggregate_id: str = Field(..., description="Session ID whose agent was launched")
