"""Pausing admission does not wait for starts queued behind busy slots (#1617).

The #1387 gate leased every ticket from the moment it was granted, so
``set_mode(active=True)`` waited for every QUEUED start to reach its slot and
write its start event. With every slot busy that meant waiting for running
executions to finish: the beta.12 pit stop's ``PUT /maintenance`` timed out
twice behind six queued executions.

The ticket now leases only from :meth:`AdmissionTicket.enter_slot`, the moment
its start holds a slot. These tests pin both halves against the primitive:

* a queued ticket does not hold the pause, and is refused at its slot if the
  pause completed first, so it stays queued instead of starting behind it;
* a ticket that holds its slot still holds the pause until it is visible
  (#1387), but only for ``drain_timeout``; running out raises and leaves the
  flag unwritten, so nothing is lost.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from syn_domain.contexts._shared.maintenance import (
    AdmissionDrainTimeoutError,
    AdmissionGate,
    MaintenanceMode,
    MaintenancePausedError,
)

pytestmark = pytest.mark.unit

_PATIENCE = 5.0


class _Port:
    def __init__(self) -> None:
        self.mode = MaintenanceMode()

    async def current(self) -> MaintenanceMode:
        return self.mode

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        self.mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        return self.mode


class TestAQueuedTicket:
    async def test_does_not_hold_the_pause(self) -> None:
        gate = AdmissionGate(_Port())
        queued = []
        for _ in range(6):
            async with gate.admitting() as ticket:
                queued.append(ticket)

        async with asyncio.timeout(_PATIENCE):
            mode = await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        assert mode.active is True
        assert not any(t.is_settled for t in queued), (
            "the pause settled the queued tickets itself; they must stay queued"
        )

    async def test_is_refused_at_its_slot_once_the_pause_has_returned(self) -> None:
        gate = AdmissionGate(_Port())
        async with gate.admitting() as ticket:
            pass
        await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        with pytest.raises(MaintenancePausedError):
            await ticket.enter_slot()
        assert ticket.is_settled, "a refused ticket must not stay outstanding"

        # It leased nothing, so it holds nothing up: the next pause is prompt.
        await gate.set_mode(active=False, reason="", actor="deploy")
        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="again", actor="deploy")

    async def test_entering_its_slot_while_a_pause_waits_lands_after_it(self) -> None:
        """Linearised like ``admitting()``: a slot reached while a pause is
        waiting for another lease is refused, never started behind it."""
        gate = AdmissionGate(_Port())
        async with gate.admitting() as running:
            pass
        await running.enter_slot()
        async with gate.admitting() as queued:
            pass

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        entering = asyncio.create_task(queued.enter_slot())
        for _ in range(20):
            await asyncio.sleep(0)
        assert not closing.done()
        assert not entering.done()

        running.mark_visible()
        async with asyncio.timeout(_PATIENCE):
            await closing
            with pytest.raises(MaintenancePausedError):
                await entering


class TestAGrantedTicket:
    async def test_holds_the_pause_until_it_is_visible(self) -> None:
        gate = AdmissionGate(_Port())
        async with gate.admitting() as ticket:
            pass
        await ticket.enter_slot()

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not closing.done(), "#1387: a granted, invisible start must hold the pause"

        ticket.mark_visible()
        async with asyncio.timeout(_PATIENCE):
            assert (await closing).active is True

    async def test_holds_it_only_for_the_bound_and_then_the_flag_is_not_written(self) -> None:
        port = _Port()
        gate = AdmissionGate(port, drain_timeout=0.05)
        async with gate.admitting() as ticket:
            pass
        await ticket.enter_slot()

        with pytest.raises(AdmissionDrainTimeoutError) as raised:
            async with asyncio.timeout(_PATIENCE):
                await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        assert raised.value.unsettled == 1
        assert port.mode.active is False, (
            "the pause gave up waiting and wrote the flag anyway: the deploy "
            "would swap over a start that exists nowhere (#1387)"
        )
        # Still open, so the stuck start can finish and a retry succeeds.
        ticket.mark_visible()
        async with asyncio.timeout(_PATIENCE):
            assert (await gate.set_mode(active=True, reason="retry", actor="deploy")).active
