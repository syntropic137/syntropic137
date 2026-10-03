"""The gate primitive, on its own terms (#1387).

``AdmissionGate`` promises one thing to everything built on it: once
``set_mode`` returns, no admission is still on its way in. The wiring tests
exercise that through the dispatcher and the projection, where today's two
admission bodies happen to be synchronous - so the part of the promise that
covers an admission body which AWAITS is not reached from there.

That part is not decoration. ``admitting()`` is documented as safe to wrap
around a decisive step, and a decisive step that persists something is the
obvious next one to be written. If the guarantee only held for bodies that
never yield, the first caller to await inside it would reopen the exact hole
this class exists to close, silently and with the gate apparently in use.

So it is pinned here, against the primitive, with no dispatcher in the way.

The same file now pins the lease (#1387, finding A). The promise is not "the
admission body finished" but "the execution it admitted is durably written, or
it definitively is not happening" - because at both real entrances the body
only queues a task, and a ticket spent there lets ``PUT /maintenance`` return
over an execution that exists nowhere yet.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from syn_domain.contexts._shared.maintenance import (
    AdmissionGate,
    AdmissionTicket,
    MaintenanceMode,
    MaintenancePausedError,
    carrying,
)

pytestmark = pytest.mark.unit

#: Long enough that a loaded machine never trips it, short enough that a
#: mutation which deadlocks fails here rather than hanging CI.
_PATIENCE = 5.0


class _Port:
    """A minimal durable store. Records reads so "read through, never cached"
    stays observable."""

    def __init__(self) -> None:
        self.mode = MaintenanceMode()
        self.reads = 0

    async def current(self) -> MaintenanceMode:
        self.reads += 1
        return self.mode

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        self.mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        return self.mode


async def _let_the_loop_run() -> None:
    """Give every runnable task a turn, without giving time a vote."""
    for _ in range(20):
        await asyncio.sleep(0)


class TestASetThatArrivesWhileALeaseIsOutstanding:
    """The admission has its ticket and the work it stands for has not become
    visible yet. The operator asks for maintenance mode. The set must wait for
    the work to EXIST, not merely for the flag to be written, and not merely
    for whoever queued the work to finish queueing it."""

    async def test_the_set_waits_for_the_body_to_finish(self) -> None:
        gate = AdmissionGate(_Port())
        in_the_body = asyncio.Event()
        may_finish = asyncio.Event()
        admitted = False

        async def _admit() -> None:
            nonlocal admitted
            async with gate.admitting() as ticket:
                in_the_body.set()
                await may_finish.wait()  # the decisive step yields
                admitted = True
                ticket.mark_visible()

        admission = asyncio.create_task(_admit())
        async with asyncio.timeout(_PATIENCE):
            await in_the_body.wait()

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()

        assert not closing.done(), (
            "set_mode returned with an admission lease still outstanding - the "
            "deploy would start draining while work was still being admitted"
        )
        assert admitted is False

        may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            await admission
            await closing
        assert admitted is True

    async def test_the_set_waits_past_the_body_until_the_work_is_visible(self) -> None:
        """The lease, and the whole of finding A: at both real entrances the
        body only QUEUES the execution, so a set that returned when the body
        returned would return over work that has not started."""
        gate = AdmissionGate(_Port())
        queued = asyncio.Event()
        may_open_the_stream = asyncio.Event()
        carried: list[AdmissionTicket] = []

        async def _admit() -> None:
            async with gate.admitting() as ticket:
                carried.append(ticket)  # "hand the work to a background task"
            queued.set()

        async def _the_background_task() -> None:
            await may_open_the_stream.wait()
            carried[0].mark_visible()

        admission = asyncio.create_task(_admit())
        worker = asyncio.create_task(_the_background_task())
        async with asyncio.timeout(_PATIENCE):
            await queued.wait()
            await admission

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()

        assert not closing.done(), (
            "set_mode returned once the admission body had merely queued the "
            "work; the execution has no stream yet, so the drain that follows "
            "counts a quiet system and the swap kills it"
        )

        may_open_the_stream.set()
        async with asyncio.timeout(_PATIENCE):
            await worker
            await closing

    async def test_an_abandoned_admission_does_not_hold_the_set_forever(self) -> None:
        """The other end of a lease. Work that definitively will not start has
        nothing for the drain to wait for, so it must not block the deploy."""
        gate = AdmissionGate(_Port())
        carried: list[AdmissionTicket] = []

        async with gate.admitting() as ticket:
            carried.append(ticket)

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()
        assert not closing.done()

        carried[0].abort()
        async with asyncio.timeout(_PATIENCE):
            await closing

    async def test_a_body_that_raises_ends_its_own_lease(self) -> None:
        """Nothing was queued, so there is nobody to end it later."""
        gate = AdmissionGate(_Port())

        with pytest.raises(RuntimeError):
            async with gate.admitting():
                raise RuntimeError("the decisive step failed")

        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

    async def test_an_admission_attempted_after_it_returns_is_refused(self) -> None:
        """The other half of the same promise: waiting would be pointless if
        the door were not shut by the time the wait ends."""
        gate = AdmissionGate(_Port())
        in_the_body = asyncio.Event()
        may_finish = asyncio.Event()

        async def _admit() -> None:
            async with gate.admitting() as ticket:
                in_the_body.set()
                await may_finish.wait()
                ticket.mark_visible()

        admission = asyncio.create_task(_admit())
        async with asyncio.timeout(_PATIENCE):
            await in_the_body.wait()
        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()
        may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            await admission
            await closing

        with pytest.raises(MaintenancePausedError):
            async with gate.admitting():
                pytest.fail("the gate admitted work after set_mode had returned")


class TestConcurrentAdmissions:
    """The negative control for the test above. If admissions excluded each
    other too, the wait would be trivially satisfied and would prove nothing
    about tickets - it would just be a queue."""

    async def test_do_not_block_each_other(self) -> None:
        gate = AdmissionGate(_Port())
        both_inside = asyncio.Barrier(2)

        async def _admit() -> None:
            async with gate.admitting() as ticket:
                await both_inside.wait()
                ticket.mark_visible()

        async with asyncio.timeout(_PATIENCE):
            await asyncio.gather(_admit(), _admit())


class TestTheGateShut:
    async def test_admitting_refuses_and_yields_nothing(self) -> None:
        port = _Port()
        gate = AdmissionGate(port)
        await gate.set_mode(active=True, reason="pit stop 0.29.1", actor="deploy")

        with pytest.raises(MaintenancePausedError) as exc:
            async with gate.admitting():
                pytest.fail("admitting() yielded a ticket while the gate was shut")

        assert "pit stop 0.29.1" in str(exc.value)

    async def test_refuse_early_refuses_too(self) -> None:
        gate = AdmissionGate(_Port())
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        with pytest.raises(MaintenancePausedError):
            await gate.refuse_early()


class TestTheGateOpen:
    async def test_admitting_yields_a_ticket_naming_the_state_it_read(self) -> None:
        gate = AdmissionGate(_Port())

        async with gate.admitting() as ticket:
            assert ticket.mode.active is False
            assert ticket.granted_at is not None

    async def test_every_call_reads_the_store_again(self) -> None:
        """No caching, ever (ADR-060): a gate that remembered "open" would
        come back permissive after the container swap that closed it."""
        port = _Port()
        gate = AdmissionGate(port)

        async with gate.admitting():
            pass
        await gate.current()
        await gate.refuse_early()

        assert port.reads == 3


class TestTheLeaseItself:
    """``carrying()`` is the rule every background worker owes the gate. It is
    tested here rather than only through the two entrances because the cost of
    getting it wrong is paid by the third entrance somebody writes later."""

    async def test_carrying_ends_a_lease_the_work_never_settled(self) -> None:
        gate = AdmissionGate(_Port())

        async with gate.admitting() as ticket:
            pass
        with carrying(ticket):
            pass

        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

    async def test_carrying_ends_a_lease_when_the_work_raises(self) -> None:
        gate = AdmissionGate(_Port())

        async with gate.admitting() as ticket:
            pass
        with pytest.raises(RuntimeError), carrying(ticket):
            raise RuntimeError("the execution blew up before it opened a stream")

        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

    async def test_carrying_tolerates_no_ticket_at_all(self) -> None:
        """A dispatcher built without a gate leases nothing."""
        with carrying(None):
            pass

    async def test_a_lease_ends_once(self) -> None:
        """`abort()` in a worker's `finally` runs after a successful
        `mark_visible()` every single time. If that double-settled, the gate's
        count would go negative and the NEXT admission's lease would be
        invisible to `set_mode` - a silent re-opening of this exact hole."""
        gate = AdmissionGate(_Port())

        async with gate.admitting() as first:
            pass
        first.mark_visible()
        first.abort()
        first.abort()
        assert first.is_settled is True

        async with gate.admitting() as second:
            pass

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()
        assert not closing.done(), (
            "the first ticket was settled more than once, so the gate lost "
            "count and stopped waiting for a lease that is still outstanding"
        )

        second.mark_visible()
        async with asyncio.timeout(_PATIENCE):
            await closing

    async def test_a_ticket_with_no_gate_behind_it_settles_quietly(self) -> None:
        """The shape a fixture builds to say "this was admitted"."""
        ticket = AdmissionTicket(granted_at=datetime.now(UTC), mode=MaintenanceMode())

        ticket.mark_visible()

        assert ticket.is_settled is True


class TestReopeningTheGate:
    async def test_does_not_wait_for_outstanding_leases(self) -> None:
        """Waiting is what makes CLOSING a gate. Re-opening overtakes nothing,
        and blocking it behind queued executions would hold the last step of a
        deploy for as long as the work it just released."""
        gate = AdmissionGate(_Port())
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")
        await gate.set_mode(active=False, reason="", actor="deploy")

        async with gate.admitting():
            pass  # queued, not visible: a lease is outstanding

        async with asyncio.timeout(_PATIENCE):
            mode = await gate.set_mode(active=False, reason="", actor="deploy")

        assert mode.active is False
