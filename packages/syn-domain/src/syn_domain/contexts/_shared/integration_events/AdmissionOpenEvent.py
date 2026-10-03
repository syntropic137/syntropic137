"""Execution admission is open - announced in the event stream (#1387).

Maintenance mode itself is NOT event-sourced: it is a durable flag (ADR-060)
read through on every admission, and that is the right shape for a thing a
deploy script flips and every admission path must see immediately.

But a flag going quiet wakes nobody. The trigger-dispatch ProcessManager holds
back triggers that arrive during a deploy as ``paused`` records, and its
processor side runs only when the coordinator hands it a live event it
subscribes to. Clearing the flag is neither, so without this event a trigger
paused by a deploy stays paused until some unrelated GitHub event happens to
arrive - which may be never.

So the wake-up is an event: durable, ordered with everything else, delivered by
the same coordinator that delivers the triggers, and re-delivered to a consumer
that was behind. It announces a STATE - "admission is open" - rather than a
transition, because it is written both when an operator clears maintenance and
when an API starts up with admission already open. The second is what makes the
wake survive a restart: a crash between clearing the flag and draining the
paused records leaves the records, and the next process says so again.

Consumers must therefore treat it as idempotent advice to re-offer parked work,
never as "something changed just now".
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("maintenance.AdmissionOpen", "v1")
class AdmissionOpenEvent(DomainEvent):
    """Announces that new workflow executions are being admitted.

    Attributes:
        announced_at: When this announcement was written.
        reason: The operator's reason, carried from the maintenance state.
        actor: Who cleared maintenance mode, or empty for a restart.
        after_restart: True when an API process announced on startup rather
            than an operator clearing the flag. Both mean the same thing to a
            consumer; the field is here so the stream says which happened.
    """

    announced_at: datetime
    reason: str = ""
    actor: str = ""
    after_restart: bool = False
