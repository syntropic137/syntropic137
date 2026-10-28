"""SandboxSpoolRecorded event - where a session's capture spool lives on a remote sandbox."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from event_sourcing import DomainEvent, event
from pydantic import Field

RemoteSpoolBackend = Literal["e2b"]
"""A spool backend whose bytes live on a sandbox's own disk, never on this host."""


@event("SandboxSpoolRecorded", "v1")
class SandboxSpoolRecordedEvent(DomainEvent):
    """The sandbox holding this session's sandbox spool exists (#2161).

    Recorded once, after the sandbox is created and before any agent launches
    in it: the sandbox id does not exist when the session starts. It is the
    durable fact a recovery worker routes from, so it names the sandbox and
    the executor that created it (the ``syn.host_id`` the sandbox is labelled
    with). Execution and phase are copied from the session so the row can be
    projected from this event alone.

    Carries ids only. An operation reattach token is a credential (#1919) and
    has no field here; ``extra="forbid"`` refuses one.

    Absence in a stream says nothing on its own: streams written before this
    event existed, and every Docker session, have none.
    """

    session_id: str
    execution_id: str
    phase_id: str
    backend: RemoteSpoolBackend
    executor_id: str = Field(min_length=1)
    sandbox_id: str = Field(min_length=1)
    recorded_at: datetime
