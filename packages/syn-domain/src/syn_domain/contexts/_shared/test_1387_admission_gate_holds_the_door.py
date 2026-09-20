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
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from syn_domain.contexts._shared.maintenance import (
    AdmissionGate,
    MaintenanceMode,
    MaintenancePausedError,
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


class TestASetThatArrivesWhileATicketIsUnspent:
    """The admission has its ticket and is doing the decisive work. The
    operator asks for maintenance mode. The set must wait for the work to
    exist, not merely for the flag to be written."""

    async def test_the_set_waits_for_the_body_to_finish(self) -> None:
        gate = AdmissionGate(_Port())
        in_the_body = asyncio.Event()
        may_finish = asyncio.Event()
        admitted = False

        async def _admit() -> None:
            nonlocal admitted
            async with gate.admitting():
                in_the_body.set()
                await may_finish.wait()  # the decisive step yields
                admitted = True

        admission = asyncio.create_task(_admit())
        async with asyncio.timeout(_PATIENCE):
            await in_the_body.wait()

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()

        assert not closing.done(), (
            "set_mode returned with an admission ticket still unspent - the "
            "deploy would start draining while work was still being admitted"
        )
        assert admitted is False

        may_finish.set()
        async with asyncio.timeout(_PATIENCE):
            await admission
            await closing
        assert admitted is True

    async def test_an_admission_attempted_after_it_returns_is_refused(self) -> None:
        """The other half of the same promise: waiting would be pointless if
        the door were not shut by the time the wait ends."""
        gate = AdmissionGate(_Port())
        in_the_body = asyncio.Event()
        may_finish = asyncio.Event()

        async def _admit() -> None:
            async with gate.admitting():
                in_the_body.set()
                await may_finish.wait()

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
            async with gate.admitting():
                await both_inside.wait()

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
