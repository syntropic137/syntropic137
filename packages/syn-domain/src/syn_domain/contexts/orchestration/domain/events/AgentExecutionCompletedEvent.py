"""AgentExecutionCompleted event - agent finished executing in workspace."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Final

from pydantic import field_validator

from event_sourcing import DomainEvent, event

#: How much of the agent's closing message this event will carry.
#:
#: The message is here because a salvage has to survive a restart, not because
#: the event store is a place to keep transcripts - and an agent's final
#: message has no upper bound. 64,000 characters is far above any conclusion
#: observed (#1195's verdict is 60, #1300's implement reports are a few
#: thousand) and far below a size that would make a stream expensive to
#: replay. Truncation is marked rather than silent, so a reader of a salvaged
#: artifact can tell a short conclusion from a cut one.
MAX_LAST_AGENT_MESSAGE: Final[int] = 64_000

_TRUNCATED: Final[str] = "\n\n[truncated: the agent's closing message exceeded {limit} characters]"


@event("AgentExecutionCompleted", "v1")
class AgentExecutionCompletedEvent(DomainEvent):
    """Event emitted when the agent has finished executing in a workspace.

    Captures the fact that execution completed and basic metrics. Stream
    chunks, tool traces and cost are observability and are not here.

    `last_agent_message` IS here, and is the one piece of what the agent
    produced that this lane keeps. It is not telemetry: it is the input to
    the #1195/#1300 salvage, which decides whether a phase that wrote no
    readable deliverable completes or fails. That is a domain outcome, so by
    this repository's own rule - if you need it after a restart, it must be an
    event - it belongs on the stream. Held in the processor's memory instead,
    as it was until #1300's review, it was lost by any restart between the
    agent finishing and its artifacts being collected: the salvage then worked
    only for runs where nothing much had gone wrong, which is when it was
    least needed.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    session_id: str | None
    completed_at: datetime
    exit_code: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last_agent_message: str | None = None

    @field_validator("last_agent_message")
    @classmethod
    def _bound_the_transcript(cls, value: str | None) -> str | None:
        """Keep the stream replayable whatever an agent decided to say.

        Enforced on the event rather than at the one call site that builds it,
        because the limit is a property of what a stream may carry and has to
        hold for every writer, including a replay of a record written before
        the limit existed.
        """
        if value is None or len(value) <= MAX_LAST_AGENT_MESSAGE:
            return value
        return value[:MAX_LAST_AGENT_MESSAGE] + _TRUNCATED.format(limit=MAX_LAST_AGENT_MESSAGE)
