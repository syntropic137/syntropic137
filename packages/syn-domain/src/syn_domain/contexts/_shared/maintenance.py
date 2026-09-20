"""Maintenance mode: the admission gate for new workflow executions (#1387).

A deploy recreates the API container, which kills whatever is in flight, so the
deploy script drains first. That drain only *observes* - it polls status counts
until they are terminal and then swaps. Nothing stops work arriving in the gap:
``POST /workflows/{id}/execute`` returns before its background task has
persisted anything, and GitHub triggers dispatch on their own schedule with no
operator involved at all.

Maintenance mode is what closes it. While it is active every admission path
refuses; executions already running are untouched, because this gates admission,
not execution.

Two properties make it a gate rather than a second observation, and both belong
to the port, not to any one caller:

* ``set_mode`` persists before it returns, so nothing can be admitted after the
  operator's call comes back.
* ``current`` reads through to the durable store every time and caches nothing,
  so an API container that starts in the middle of a deploy comes back still
  refusing instead of silently re-opening admission (ADR-060).

Lives in the shared kernel because both contexts that admit executions need it:
``orchestration`` (the HTTP path) and ``github`` (trigger dispatch). One
declaration, so the two cannot drift apart on what "paused" means.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

# NOT in a TYPE_CHECKING block, despite TC003: `MaintenanceMode` is a
# Pydantic model and Pydantic resolves `since: datetime | None` against
# this module's real namespace at class-build time.
from datetime import UTC, datetime  # noqa: TC003
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict


class MaintenanceMode(BaseModel):
    """Whether new workflow executions may be admitted, and why not.

    The default is the open state, so a store that has never been written
    reads as "admission open" without anyone having to say so.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active: bool = False
    reason: str = ""
    since: datetime | None = None
    actor: str = ""

    @property
    def refusal_detail(self) -> str:
        """The one sentence every admission path gives back when it refuses.

        Built here rather than at each call site so the 409 body, the trigger
        history record and the log line cannot describe the same refusal
        differently.
        """
        reason = self.reason.strip() or "deployment in progress"
        since = f" since {self.since.isoformat()}" if self.since is not None else ""
        return (
            f"Execution admission is paused{since}: {reason}. "
            "Running executions are unaffected; retry once maintenance mode clears."
        )


class MaintenancePausedError(Exception):
    """Raised instead of admitting an execution while maintenance mode is active.

    Carries the mode so the entry point that catches it can translate the
    refusal into its own protocol's answer - a 409 over HTTP, a ``paused``
    dispatch record for a trigger - rather than reporting a generic failure.
    """

    def __init__(self, mode: MaintenanceMode) -> None:
        super().__init__(mode.refusal_detail)
        self.mode = mode


@runtime_checkable
class MaintenancePort(Protocol):
    """Durable store for maintenance mode.

    Implementations MUST write through to durable storage before returning from
    ``set_mode`` and MUST read through to it on every ``current`` call. An
    implementation that caches, or that keeps the state in process memory,
    re-opens admission on restart and is the failure ADR-060 exists to forbid.
    """

    async def current(self) -> MaintenanceMode:
        """Return the state as durably stored right now."""
        ...

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state and return what was stored. Durable before return."""
        ...


async def refuse_if_paused(port: MaintenancePort) -> None:
    """Raise :class:`MaintenancePausedError` if admission is closed.

    The single predicate. Every admission path calls this and translates the
    exception; none of them re-decides what "paused" means.
    """
    mode = await port.current()
    if mode.active:
        raise MaintenancePausedError(mode)


@dataclass(frozen=True)
class AdmissionTicket:
    """Proof that one execution was admitted while the gate was provably open.

    Issued by :meth:`AdmissionGate.admitting` and carried forward to whatever
    finally starts the work. It exists because the admission decision and the
    start of the execution are separated by a fire-and-forget task, and the two
    must not disagree: a caller that was told "admitted" - a 200 from the HTTP
    route, a ``dispatched`` trigger record - has to be telling the truth.

    So the ticket is the linearization point. Downstream does not re-read the
    flag and re-decide; it consumes the ticket. Re-deciding is what produced a
    trigger record claiming a dispatch that the background task had already
    refused: the record was written from the first answer and the work stopped
    on the second.

    The absence of a ticket is the safe state. Anything reaching the handler
    with ``None`` was never admitted by the gate and is checked against it
    there, so a path written later is refused rather than waved through.
    """

    granted_at: datetime
    mode: MaintenanceMode


class AdmissionGate:
    """Serialises admission against the maintenance transition.

    The durable flag alone is not a gate. ``current()`` is a round trip to
    Postgres or Redis, so an admission can read "open", have the operator's
    ``set_mode`` durably complete while that reply is still in flight, and then
    admit work after ``PUT /maintenance`` has already returned. The drain that
    follows counts a system that is still being filled.

    This closes that by making admission and transition mutually exclusive,
    with the shape of a drain rather than a plain lock:

    * an admission holds :attr:`_transition` only long enough to read the flag
      and take out a ticket, so admissions never queue behind one another;
    * ``set_mode`` holds it for the write AND first waits for every ticket
      already taken out to be spent.

    After ``set_mode`` returns, therefore: the flag is durable, no admission is
    part-way through deciding, and every later admission must take the same
    lock and will read the new state. That is the property the deploy needs -
    "nothing more can be admitted from here" - rather than "nothing had been
    admitted a moment ago", which is all the drain could ever observe.

    In-process only, deliberately. It linearises the API container that owns
    both the HTTP route and the trigger-dispatch projection, which is the
    container a deploy pauses. A second replica is bounded by the durable flag
    instead: it refuses from its next read, so its window is one in-flight read
    rather than an open door. Closing that too needs a lock in the store, and
    is out of scope for #1387.
    """

    def __init__(self, port: MaintenancePort) -> None:
        self._port = port
        self._transition = asyncio.Lock()
        self._unspent = 0
        self._idle = asyncio.Event()
        self._idle.set()

    async def current(self) -> MaintenanceMode:
        """The durable state, read through. No lock: this only reports."""
        return await self._port.current()

    async def refuse_early(self) -> None:
        """Refuse a plainly-shut gate without taking the lock.

        For the cheap check an entry point makes before it does expensive
        preparation - a template read, a repo preflight - so that work is not
        paid for during a deploy, and so the caller gets the gate's answer
        rather than a validation error about something the gate never let it
        reach.

        It decides nothing. Its answer may be stale before it arrives, which is
        the whole defect this class exists to close, so it is never the last
        word: :meth:`admitting` still has to grant the ticket.
        """
        await refuse_if_paused(self._port)

    @asynccontextmanager
    async def admitting(self) -> AsyncIterator[AdmissionTicket]:
        """Hold the gate open for one admission, or refuse.

        Raises :class:`MaintenancePausedError` instead of yielding when the
        gate is shut. The body must be the DECISIVE step and nothing else -
        creating the task, queueing the background work - because ``set_mode``
        waits for it. Validation, template reads and preflight belong outside;
        holding the gate across them would let a slow request stall a deploy.
        """
        async with self._transition:
            mode = await self._port.current()
            if mode.active:
                raise MaintenancePausedError(mode)
            self._unspent += 1
            self._idle.clear()
        try:
            yield AdmissionTicket(granted_at=datetime.now(UTC), mode=mode)
        finally:
            self._unspent -= 1
            if self._unspent == 0:
                self._idle.set()

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state, durable before return and with the door held.

        Every admission path must set the flag through here rather than through
        the port, or the exclusion above is decoration.
        """
        async with self._transition:
            await self._idle.wait()
            return await self._port.set_mode(active=active, reason=reason, actor=actor)
