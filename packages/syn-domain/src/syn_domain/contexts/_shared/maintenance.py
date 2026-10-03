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
import weakref
from contextlib import asynccontextmanager, contextmanager

# NOT in a TYPE_CHECKING block: `MaintenanceMode` is a Pydantic model and
# Pydantic resolves `since: datetime | None` against this module's real
# namespace at class-build time.
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator


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


class AdmissionAnnouncementFailedError(Exception):
    """The flag was cleared durably, but the wake-up was not written.

    The half-done clear, named so a caller can tell it apart from a failure to
    clear at all: admission IS open again, and work parked by the deploy has
    NOT been told. Nothing else re-offers that work - a flag that stops being
    true wakes no consumer - so the operator's clear has not finished doing
    what it is for, and reporting success here would hide a trigger that never
    runs behind a green deploy step.

    Retryable, and retrying is the repair: another ``set_mode(active=False)``
    re-announces, and so does the next startup. Carries the mode so the entry
    point can say which state the system is actually in while it asks for that
    retry.
    """

    def __init__(self, mode: MaintenanceMode) -> None:
        super().__init__(
            "Execution admission was re-opened, but announcing it failed, so work "
            "paused during maintenance has not been woken. Admission is open; "
            "repeat the clear to re-announce (#1387)."
        )
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


@runtime_checkable
class AdmissionAnnouncer(Protocol):
    """Publishes "admission is open" somewhere a consumer can be woken by.

    Separate from :class:`MaintenancePort` on purpose. The port stores the
    answer to "may I admit?"; this tells work that was parked while the answer
    was no that it may try again. A store cannot do the second - nothing reads
    a flag it is not already reading - and a gate must not know that the answer
    is an event store append.

    Implementations MUST be durable before returning: the whole value of the
    announcement is that it survives the process that made it (#1387).
    """

    async def announce_open(self, mode: MaintenanceMode, *, after_restart: bool) -> None:
        """Announce that new executions are being admitted."""
        ...


async def refuse_if_paused(port: MaintenancePort) -> None:
    """Raise :class:`MaintenancePausedError` if admission is closed.

    The single predicate. Every admission path calls this and translates the
    exception; none of them re-decides what "paused" means.
    """
    mode = await port.current()
    if mode.active:
        raise MaintenancePausedError(mode)


class AdmissionTicket:
    """A LEASE on one admission, held until the execution exists or is abandoned.

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

    A lease and not a receipt, because queueing work is not doing it. Both
    entrances hand the execution to something asynchronous - a Starlette
    background task, an ``asyncio`` task that then waits behind the dispatcher
    semaphore - and until that work writes its start event the drain cannot see
    it. A ticket released at the hand-off therefore lets ``PUT /maintenance``
    return over an execution that exists nowhere yet, and the swap that follows
    kills it. That is the loss this whole module exists to prevent, one layer
    down, so the lease outlives the hand-off:

    * :meth:`mark_visible` - the start event is durably written. The drain can
      see this execution now and will wait for it.
    * :meth:`abort` - it definitively will not start. There is nothing for the
      drain to see and nothing to wait for.

    Exactly one of those two is the end of the lease, whichever arrives first;
    both are idempotent, so the worker can call :meth:`abort` unconditionally
    in a ``finally`` and it is a no-op once the stream is open. Nothing else
    releases it - in particular, leaving the ``admitting()`` block does not.

    The absence of a ticket is the safe state. Anything reaching the handler
    with ``None`` was never admitted by the gate and is checked against it
    there, so a path written later is refused rather than waved through.
    """

    def __init__(
        self,
        *,
        granted_at: datetime,
        mode: MaintenanceMode,
        on_settled: Callable[[], None] | None = None,
    ) -> None:
        """``on_settled`` is how the gate learns the lease ended.

        Optional so a test can build a ticket to stand for "this was admitted"
        without a gate behind it. A ticket built that way leases nothing and
        blocks nothing, which is the right meaning for one that no gate issued.
        """
        self.granted_at = granted_at
        self.mode = mode
        self._on_settled = on_settled
        self._settled = False

    @property
    def is_settled(self) -> bool:
        """Whether the lease has ended, either way."""
        return self._settled

    def mark_visible(self) -> None:
        """The start event is durably written; the drain can see this work.

        Called at the write itself, not by the caller that queued the work, so
        the lease ends where the guarantee actually becomes true.
        """
        self._settle()

    def abort(self) -> None:
        """This admission produced no execution and never will.

        The other honest end of a lease: refused downstream, failed before the
        stream was opened, or cancelled at shutdown. Safe to call after
        :meth:`mark_visible` - the first settlement wins - so a worker can put
        it in a ``finally`` and not reason about which path it took.
        """
        self._settle()

    def _settle(self) -> None:
        if self._settled:
            return
        self._settled = True
        if self._on_settled is not None:
            self._on_settled()


@contextmanager
def carrying(ticket: AdmissionTicket | None) -> Iterator[None]:
    """Run admitted work under its lease, and end the lease whatever happens.

    The one rule every background worker owes the gate, written once: a lease
    that is never settled stalls the next ``set_mode(active=True)`` for as long
    as the process lives, and settling it correctly on each of return, raise and
    cancellation is not something two entrances should be re-deriving. Wrapping
    is a no-op once the work has called :meth:`AdmissionTicket.mark_visible`.

    ``None`` is accepted and does nothing, for the fixtures that build a
    dispatcher with no gate at all.
    """
    try:
        yield
    finally:
        if ticket is not None:
            ticket.abort()


def guarantee_settled(ticket: AdmissionTicket | None, work: object) -> None:
    """End the lease when ``work`` ends, INCLUDING when its body never runs.

    :func:`carrying` settles on every path the work's own body takes, and a
    body that never executes takes none of them. A task cancelled before its
    first turn is torn down without running a line, and a callable queued with
    a framework that never invokes it runs no line either; both leave a granted
    lease outstanding for the life of the process, and the next
    ``set_mode(active=True)`` then waits for it forever. That fails safe - the
    deploy stalls rather than losing an execution - but a gate that can hang is
    not a gate that lets a deploy proceed unattended, which is the point of
    having one.

    So this is the backstop, and it belongs here rather than at the entrances:
    both of them queue admitted work onto something they do not control, and
    neither should be re-deriving what "the lease always ends" means.

    The caller passes whatever the scheduler is holding; how settlement is
    guaranteed is this function's decision, not theirs:

    * an ``asyncio`` future or task settles from its DONE callback, which the
      loop invokes for every outcome - returned, raised, or cancelled before
      the coroutine ever ran;
    * anything else settles when it becomes unreachable. A queued callable is
      reachable for exactly as long as it may still be called, so collecting it
      is the framework saying it never will be.

    Idempotent with the work itself: :meth:`AdmissionTicket.abort` after
    :meth:`AdmissionTicket.mark_visible` is a no-op, so the normal path still
    ends its lease promptly, at the durable write, and this only ever catches
    what that path missed.

    ``None`` is accepted and does nothing, for the fixtures that build a
    dispatcher with no gate at all.
    """
    if ticket is None:
        return
    if isinstance(work, asyncio.Future):
        finished: asyncio.Future[object] = work
        finished.add_done_callback(lambda _finished: ticket.abort())
        return
    weakref.finalize(work, ticket.abort)


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
    * closing the gate holds it for the write AND first waits for every ticket
      already taken out to reach its execution or abandon it.

    After ``set_mode(active=True)`` returns, therefore: the flag is durable, no
    admission is part-way through deciding, every admission granted before it
    has a durably-written start event the drain can see or has definitively
    produced nothing, and every later admission must take the same lock and
    will read the new state. That is the property the deploy needs - "nothing
    more can be admitted from here, and everything already admitted is
    countable" - rather than "nothing had been admitted a moment ago", which is
    all the drain could ever observe.

    The wait is on the work becoming VISIBLE, not on it finishing: a lease ends
    at ``journal.open()``, so the execution the deploy must not lose is one the
    drain then counts and waits out. It is unbounded by design. An execution
    queued behind the dispatcher semaphore holds its lease until the one ahead
    of it finishes, and that is the honest answer - the alternative is
    returning from ``PUT /maintenance`` over work that exists nowhere, which is
    the bug. The drain that follows would have waited for it anyway.

    In-process only, deliberately. It linearises the API container that owns
    both the HTTP route and the trigger-dispatch projection, which is the
    container a deploy pauses. A second replica is bounded by the durable flag
    instead: it refuses from its next read, so its window is one in-flight read
    rather than an open door. Closing that too needs a lock in the store, and
    is out of scope for #1387.
    """

    def __init__(self, port: MaintenancePort, announcer: AdmissionAnnouncer | None = None) -> None:
        self._port = port
        self._announcer = announcer
        self._transition = asyncio.Lock()
        self._outstanding = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def _lease_ended(self) -> None:
        """One ticket reached its execution, or abandoned it. Never public:
        the ticket is what decides a lease has ended, and it decides once."""
        self._outstanding -= 1
        if self._outstanding == 0:
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
        creating the task, queueing the background work. Validation, template
        reads and preflight belong outside; holding the gate across them would
        let a slow request stall a deploy.

        Leaving the body does NOT end the lease, and that asymmetry is the
        point: the body only queues the work, so releasing there would let a
        deploy declare the system quiet over an execution that has not started.
        The ticket is handed to whoever runs the work, and the lease ends when
        that work calls :meth:`AdmissionTicket.mark_visible` or
        :meth:`AdmissionTicket.abort` - see :func:`carrying`, which is how both
        entrances guarantee one of the two. A body that RAISES has queued
        nothing, so the lease is ended here.
        """
        async with self._transition:
            mode = await self._port.current()
            if mode.active:
                raise MaintenancePausedError(mode)
            self._outstanding += 1
            self._idle.clear()
        ticket = AdmissionTicket(
            granted_at=datetime.now(UTC), mode=mode, on_settled=self._lease_ended
        )
        try:
            yield ticket
        except BaseException:
            ticket.abort()
            raise

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        """Persist the state, durable before return and with the door held.

        Every admission path must set the flag through here rather than through
        the port, or the exclusion above is decoration.

        Closing waits for the outstanding leases; re-opening does not. Waiting
        is what makes closing a gate rather than an observation - there is
        something the deploy must not overtake. Re-opening overtakes nothing,
        and blocking it behind executions that are merely queued would hold a
        deploy's final step for as long as the work it just released.

        Re-opening announces (#1387). Work refused during the deploy is parked,
        not discarded, and nothing re-offers it on its own: a flag that stops
        being true is not an event and wakes no consumer. The announcement is
        what turns "admission is open again" into something that arrives.

        Raises:
            AdmissionAnnouncementFailedError: re-opening stored the flag but
                could not announce it. The clear did not finish, so it does not
                return a value the caller can read as success; the flag is open
                and the parked work is still asleep until this is retried.
        """
        async with self._transition:
            if active:
                await self._idle.wait()
            mode = await self._port.set_mode(active=active, reason=reason, actor=actor)

        if not active:
            # After the flag is durable, never before: a consumer woken while
            # the gate still refused would re-park everything it retried, and
            # the wake would have been spent on nothing.
            #
            # Outside the transition lock, because this is a round trip to the
            # event store and admission must not queue behind it.
            await self.announce_open(mode)
        return mode

    async def announce_open(self, mode: MaintenanceMode, *, after_restart: bool = False) -> None:
        """Tell parked work it may try again. Safe to repeat.

        Called on every re-open, and once at startup when admission is already
        open - that second call is what carries the wake across a restart, so
        a crash between clearing the flag and draining the parked work does not
        strand it.

        A failure here RAISES, and the operator path lets it out (#1387). The
        announcement is the half of the clear that does the work: the flag
        going false wakes nobody, so a swallowed failure is a deploy whose last
        step reports success over triggers that will never run. The gate does
        not get to decide that logging is enough - that is a delivery policy
        and it belongs to the caller. The clear path asks for a retry; startup
        logs and carries on, because there the next start is the retry.

        Raises:
            AdmissionAnnouncementFailedError: the announcer failed. Retryable:
                another re-open, or the next startup, announces again.
        """
        if self._announcer is None:
            return
        try:
            await self._announcer.announce_open(mode, after_restart=after_restart)
        except Exception as exc:
            raise AdmissionAnnouncementFailedError(mode) from exc
