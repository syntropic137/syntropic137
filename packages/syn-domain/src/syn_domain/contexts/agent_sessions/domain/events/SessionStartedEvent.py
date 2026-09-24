"""SessionStarted event - represents the fact that a session was started."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SessionStarted", "v1")
class SessionStartedEvent(DomainEvent):
    """Event emitted when an agent session is started.

    Sessions track agent execution for observability.
    """

    # Session identity
    session_id: str

    # Context
    workflow_id: str
    execution_id: str | None = None  # Links session to a specific workflow execution/run
    phase_id: str
    milestone_id: str | None = None

    # Delegation linkage (issue #792). Optional with None default for backward
    # compatibility with pre-delegation events; there is no upcaster framework,
    # readers are tolerant.
    parent_session_id: str | None = None
    root_session_id: str | None = None

    # Agent info
    agent_provider: str
    #: The model the phase REQUESTED (often an alias such as ``opus``), fixed
    #: when the session starts, before any harness has said what it runs. It
    #: is NOT the model that ran: that is only known from the harness's own
    #: report and is carried on Lane 2 observations as ``model``, with this
    #: value repeated there as ``requested_model`` (ADR-067). Kept under its
    #: historical name because a stored event's field cannot be renamed.
    agent_model: str | None = None

    # Repository context (owner/repo slugs from the workflow execution).
    # Optional with empty default for backward compatibility with pre-repos events.
    repos: list[str] = Field(default_factory=list)

    # Timing
    started_at: datetime

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012
