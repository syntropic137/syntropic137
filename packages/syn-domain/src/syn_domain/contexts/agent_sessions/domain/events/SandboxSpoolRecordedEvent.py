"""SandboxSpoolRecorded event - where a session's capture spool lives on a remote sandbox."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Annotated, Literal

from event_sourcing import DomainEvent, event
from pydantic import AfterValidator, Field

RemoteSpoolBackend = Literal["e2b"]
"""A spool backend whose bytes live on a sandbox's own disk, never on this host."""


def _route_identifier(value: str) -> str:
    # The spool row's RoutingIdentifier rule, restated: events carry no
    # dependencies (VSA), and a route the row refuses would stall projection.
    if not value.strip() or "\x00" in value:
        raise ValueError("identifier must be non-blank and contain no NUL")
    value.encode("utf-8")
    return value


SandboxRouteIdentifier = Annotated[str, Field(max_length=128), AfterValidator(_route_identifier)]
"""An executor or sandbox id, bounded exactly as ``CaptureSpool`` bounds it."""


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
    #: Validated as the spool row validates them, so a recorded route can
    #: always be projected: a fact the projector refuses would stall it.
    executor_id: SandboxRouteIdentifier
    sandbox_id: SandboxRouteIdentifier
    recorded_at: datetime
