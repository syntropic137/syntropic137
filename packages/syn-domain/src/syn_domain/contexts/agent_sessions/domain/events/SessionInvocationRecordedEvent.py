"""Invocation lifecycle fact. Primitive wire fields keep historical replay portable."""

from typing import Literal

from event_sourcing import DomainEvent, event


@event("SessionInvocationRecorded", "v1")
class SessionInvocationRecordedEvent(DomainEvent):
    session_id: str
    execution_id: str
    phase_id: str
    invocation_id: str
    attempt_id: str
    harness: str
    status: Literal["registered", "launched", "completed", "failed", "cancelled"]
    native_session_id: str | None = None
