"""Nothing is admitted after ``PUT /maintenance`` returns (#1387).

The first pass at this issue made every admission path consult a durable flag,
and that is necessary but it is not a gate. ``current()`` is a round trip to
Postgres or Redis. An admission can read "open", have the operator's set
complete while that reply is still in flight, and then admit work - after the
deploy script has been told the door is shut and has started counting what is
left inside. The drain that follows is counting a system that is still being
filled, which is the original bug with one more moving part.

So these tests do not set the flag and then admit. They interleave: an
admission is suspended at the exact instant its view of the flag is decided,
the transition completes underneath it, and the question is what the CALLER is
told once it resumes. Two directions, and both matter:

* a stale read must not become an admission (``TestAnAdmissionHoldingAStaleRead``)
* a ticket already taken out must not be abandoned - ``set_mode`` waits for it,
  rather than returning while work is still on its way in
  (``TestATransitionThatStartsMidAdmission``)

Determinism comes from an ``asyncio.Event`` inside the port double, never from
sleeps: the interleaving is constructed, not raced for.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore
from fastapi import BackgroundTasks, HTTPException

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.routes.executions import commands
from syn_api.routes.maintenance import set_maintenance_mode
from syn_api.types import SetMaintenanceModeRequest
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket, MaintenanceMode
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration import WorkflowTemplateAggregate

pytestmark = pytest.mark.unit

_PROJECTION = WorkflowDispatchProjection.PROJECTION_NAME

#: Long enough that a loaded machine never trips it, short enough that a
#: mutation which deadlocks fails here instead of hanging CI forever.
_PATIENCE = 5.0


@dataclass(frozen=True)
class _DispatchRecord:
    """The dispatch record these tests read, as an object rather than a mapping.

    The store hands back a string-keyed mapping; this narrows it once, here.
    A real type rather than a `TypedDict`, because the untyped-dict ratchet
    counts both - and rightly: a `TypedDict` is still read by string key with
    no runtime validation, so it erases the same structure with a nicer name.
    """

    status: str
    status_reason: str | None
    dispatched_at: object | None

    @classmethod
    def from_row(cls, row: object) -> _DispatchRecord:
        read = getattr(row, "get", None)
        assert read is not None, f"dispatch record is not readable: {row!r}"
        return cls(
            status=str(read("status")),
            status_reason=None if read("status_reason") is None else str(read("status_reason")),
            dispatched_at=read("dispatched_at"),
        )


class _SuspendablePort:
    """A durable store whose replies can be held in flight.

    The suspension models the only thing that makes this a race at all: the
    answer to "is the gate open" is decided at the store and then travels, and
    the flag can change while it travels. ``current()`` therefore snapshots
    FIRST and waits afterwards - a double that re-read after waiting would
    hand back the new state and quietly test nothing.
    """

    def __init__(self, *, suspend_read: int) -> None:
        self.mode = MaintenanceMode()
        self.reads = 0
        self.suspend_read = suspend_read
        self.in_flight = asyncio.Event()
        self.release = asyncio.Event()

    async def current(self) -> MaintenanceMode:
        self.reads += 1
        snapshot = self.mode
        if self.reads == self.suspend_read:
            self.in_flight.set()
            await self.release.wait()
        return snapshot

    async def set_mode(self, *, active: bool, reason: str, actor: str) -> MaintenanceMode:
        self.mode = MaintenanceMode(
            active=active,
            reason=reason,
            since=datetime.now(UTC) if active else None,
            actor=actor,
        )
        return self.mode


class _RecordingHandler:
    """Stands in for ExecuteWorkflowHandler. Records what was admitted.

    Keeps the tickets as well as the commands, so a test can ask whether the
    record the projection wrote and the execution that actually ran came from
    the SAME admission - which is the whole of what "one awaited operation
    whose result reaches the projection" buys.
    """

    def __init__(self) -> None:
        self.admitted: list[object] = []
        self.tickets: list[AdmissionTicket | None] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, command: object, *, admitted: AdmissionTicket | None = None) -> None:
        self.admitted.append(command)
        self.tickets.append(admitted)
        # What the real handler reaches through the processor: the start event
        # is durable, so the admission lease ends here (#1387). A double that
        # skipped it would leave every lease outstanding and turn the next
        # `set_mode(active=True)` into a hang rather than an assertion.
        if admitted is not None:
            admitted.mark_visible()


class _Fixture:
    """The real dispatcher and the real projection, over a suspendable store.

    Real on purpose: the defect being prevented lives in the seam between the
    projection awaiting ``run_workflow`` and the fire-and-forget task, and a
    stand-in for either side would have no seam to get wrong.
    """

    def __init__(self, *, suspend_read: int) -> None:
        self.port = _SuspendablePort(suspend_read=suspend_read)
        self.gate = AdmissionGate(self.port)
        self.store = MemoryProjectionStore()
        self.checkpoints = MemoryCheckpointStore()
        self.handler = _RecordingHandler()
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,  # type: ignore[arg-type]
            maintenance=self.gate,
        )
        self.projection = WorkflowDispatchProjection(
            execution_service=self.dispatcher,
            store=self.store,
        )

    async def a_trigger_fires(self, execution_id: str) -> None:
        """A real `github.TriggerFired` envelope - the shape every one of the
        three sources (webhook, Events API poller, Checks API poller) produces
        once normalized, so gating this covers all three."""
        event = TriggerFiredEvent(
            trigger_id="trg-ci-self-healing",
            execution_id=execution_id,
            workflow_id="wf-ci-self-healing",
            workflow_inputs={"repository": "syntropic137/syntropic137"},
            github_event_type="check_run.completed",
        )
        await self.projection.handle_event(
            EventEnvelope(
                event=event,
                metadata=EventMetadata(
                    event_type=TriggerFiredEvent.event_type,
                    aggregate_id="trg-ci-self-healing",
                    aggregate_type="TriggerRule",
                    aggregate_nonce=1,
                    global_nonce=1,
                ),
            ),
            self.checkpoints,
        )

    async def record(self, execution_id: str) -> _DispatchRecord:
        found = await self.store.get(_PROJECTION, execution_id)
        assert found is not None, "the trigger produced no dispatch record at all"
        return _DispatchRecord.from_row(found)

    async def drain_the_dispatcher(self) -> None:
        """Wait for the fire-and-forget tasks rather than cancelling them.

        Cancelling would hide whether the handler was ever reached, which is
        the fact under test.
        """
        async with asyncio.timeout(_PATIENCE):
            for _ in range(100):
                if not self.dispatcher._tasks:
                    return
                await asyncio.gather(*self.dispatcher._tasks, return_exceptions=True)
                await asyncio.sleep(0)


async def _let_the_loop_run() -> None:
    """Give every runnable task a turn, without giving time a vote.

    Used to assert that something has NOT happened. A sleep would make the
    assertion a race; this makes it a fact about scheduling.
    """
    for _ in range(20):
        await asyncio.sleep(0)


class TestAnAdmissionHoldingAStaleRead:
    """The counterexample verification produced against the first pass.

    The dispatcher's early check reads the flag and is suspended. The deploy's
    ``PUT /maintenance`` completes. The read resumes, still saying "open". If
    that answer is allowed to admit, the deploy has been lied to.
    """

    @pytest.fixture
    def fixture(self) -> _Fixture:
        return _Fixture(suspend_read=1)

    async def test_the_stale_read_does_not_admit(self, fixture: _Fixture) -> None:
        await fixture.a_trigger_fires("exec-stale01")
        pending = asyncio.create_task(fixture.projection.process_pending())

        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        await fixture.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        fixture.port.release.set()

        async with asyncio.timeout(_PATIENCE):
            await pending
        await fixture.drain_the_dispatcher()

        assert fixture.handler.admitted == [], (
            "work was admitted after PUT /maintenance had already returned - "
            "the deploy drain is counting a system that is still filling"
        )

    async def test_the_trigger_is_recorded_as_paused(self, fixture: _Fixture) -> None:
        """`dispatched` here is the expensive failure: the record claims a run
        that the background task had already refused, and nothing re-offers
        it."""
        await fixture.a_trigger_fires("exec-stale02")
        pending = asyncio.create_task(fixture.projection.process_pending())

        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        await fixture.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        fixture.port.release.set()

        async with asyncio.timeout(_PATIENCE):
            await pending
        await fixture.drain_the_dispatcher()

        record = await fixture.record("exec-stale02")
        assert record.status == "paused"
        assert record.status_reason == "maintenance_mode"
        assert record.dispatched_at is None


class TestATransitionThatStartsMidAdmission:
    """The other direction: a ticket is already out when the operator asks.

    Suspending the SECOND read suspends the gate's own decisive read - the one
    taken under the transition lock - so the admission is provably part-way
    through deciding. ``set_mode`` must then wait, because returning would tell
    the deploy that nothing more can arrive while something still can.
    """

    @pytest.fixture
    def fixture(self) -> _Fixture:
        return _Fixture(suspend_read=2)

    async def test_the_set_does_not_return_while_an_admission_is_deciding(
        self, fixture: _Fixture
    ) -> None:
        await fixture.a_trigger_fires("exec-midway1")
        pending = asyncio.create_task(fixture.projection.process_pending())

        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        closing = asyncio.create_task(
            fixture.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        )
        await _let_the_loop_run()

        assert not closing.done(), (
            "PUT /maintenance returned while an admission was still deciding - "
            "its caller would believe the door was shut"
        )

        fixture.port.release.set()
        async with asyncio.timeout(_PATIENCE):
            await pending
            await closing
        await fixture.drain_the_dispatcher()

    async def test_the_admission_that_held_the_ticket_is_honoured(self, fixture: _Fixture) -> None:
        """It was admitted before the set returned, so it runs - and the record
        says so truthfully. This gates admission, not execution."""
        await fixture.a_trigger_fires("exec-midway2")
        pending = asyncio.create_task(fixture.projection.process_pending())

        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        closing = asyncio.create_task(
            fixture.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        )
        await _let_the_loop_run()
        fixture.port.release.set()

        async with asyncio.timeout(_PATIENCE):
            await pending
            await closing
        await fixture.drain_the_dispatcher()

        record = await fixture.record("exec-midway2")
        assert record.status == "dispatched"
        assert len(fixture.handler.admitted) == 1

        # The record and the run came from one admission, not from two guesses
        # that happened to agree. `dispatched_at` is the gate's own answer -
        # the moment it granted the ticket the handler then ran under - so a
        # record cannot exist without an admission that produced it.
        ticket = fixture.handler.tickets[0]
        assert ticket is not None
        assert record.dispatched_at == ticket.granted_at.isoformat()

    async def test_the_next_trigger_after_the_set_returns_is_refused(
        self, fixture: _Fixture
    ) -> None:
        """The point of waiting: once the operator has their response, the door
        is shut for everything that comes after it."""
        await fixture.a_trigger_fires("exec-midway3")
        pending = asyncio.create_task(fixture.projection.process_pending())

        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        closing = asyncio.create_task(
            fixture.gate.set_mode(active=True, reason="pit stop", actor="deploy")
        )
        await _let_the_loop_run()
        fixture.port.release.set()
        async with asyncio.timeout(_PATIENCE):
            await pending
            await closing
        await fixture.drain_the_dispatcher()
        admitted_before = len(fixture.handler.admitted)

        await fixture.a_trigger_fires("exec-midway4")
        await fixture.projection.process_pending()
        await fixture.drain_the_dispatcher()

        assert (await fixture.record("exec-midway4")).status == "paused"
        assert len(fixture.handler.admitted) == admitted_before


# -- The manual path ----------------------------------------------------------
#
# Same interleaving, different entrance. The HTTP route has its own decisive
# step - `background_tasks.add_task` - and its own way of getting it wrong: the
# response says 200 and is already on its way back, so a refusal discovered any
# later than that line cannot reach the caller at all.


@dataclass
class _Request:
    """Enough of ExecuteWorkflowRequest for the endpoint's signature."""

    inputs: dict[str, str] = field(default_factory=dict)
    repos: list[str] = field(
        default_factory=lambda: ["https://github.com/syntropic137/syntropic137"]
    )
    task: str | None = None
    provider: str = "claude"


class _WorkflowRepo:
    """A workflow that EXISTS, unlike the one the steady-state tests use.

    Deliberate: with a missing workflow the route 404s in validation and never
    reaches the gate's decisive step, so the interleaving under test here would
    never happen. The whole question is what the gate does once a request has
    earned its way to the point of being admitted.
    """

    def __init__(self) -> None:
        self._workflow = WorkflowTemplateAggregate()

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return self._workflow


class _HttpFixture:
    def __init__(self, *, suspend_read: int) -> None:
        self.port = _SuspendablePort(suspend_read=suspend_read)
        self.gate = AdmissionGate(self.port)
        self.started: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "_admission_gate_singleton", self.gate, raising=False)
        monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
        monkeypatch.setattr(commands, "execute", self._execute)

    async def _execute(
        self,
        *,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[object],
        admitted: AdmissionTicket | None = None,
    ) -> None:
        """Stand in for the background task's run of the execution.

        It ends the admission lease, because that is what the real path does
        at ``journal.open()`` (#1387). Nothing before this point may end it:
        the route only QUEUED this coroutine.
        """
        del workflow_id, inputs, task, repos
        self.started.append(execution_id)
        if admitted is not None:
            admitted.mark_visible()

    async def admit(self) -> BackgroundTasks:
        tasks = BackgroundTasks()
        await commands.execute_workflow_endpoint("wf-ci-self-healing", _Request(), tasks)  # type: ignore[arg-type]
        return tasks


async def _nothing_to_connect() -> None:
    return None


class TestTheHttpRouteHoldingAStaleRead:
    """Its cheap first check is suspended; the deploy's PUT completes; the read
    resumes saying "open". A 200 from here is an execution the drain never
    counted and the swap kills."""

    async def test_answers_409_and_queues_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fixture = _HttpFixture(suspend_read=1)
        fixture.install(monkeypatch)

        tasks = BackgroundTasks()
        call = asyncio.create_task(
            commands.execute_workflow_endpoint("wf-ci-self-healing", _Request(), tasks)  # type: ignore[arg-type]
        )
        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop 0.29.1", actor="deploy")
        )
        fixture.port.release.set()

        with pytest.raises(HTTPException) as exc:
            async with asyncio.timeout(_PATIENCE):
                await call

        assert exc.value.status_code == 409
        assert tasks.tasks == [], (
            "the endpoint refused but still queued the execution - the "
            "BackgroundTask is what actually admits the work"
        )


class TestAnHttpTransitionThatStartsMidAdmission:
    """Suspending the SECOND read suspends the decisive one, taken under the
    transition lock - so the request is provably part-way through being
    admitted when the operator asks."""

    async def test_the_set_waits_and_the_request_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture = _HttpFixture(suspend_read=2)
        fixture.install(monkeypatch)

        tasks = BackgroundTasks()
        call = asyncio.create_task(
            commands.execute_workflow_endpoint("wf-ci-self-healing", _Request(), tasks)  # type: ignore[arg-type]
        )
        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        closing = asyncio.create_task(
            set_maintenance_mode(
                SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
            )
        )
        await _let_the_loop_run()

        assert not closing.done(), (
            "PUT /maintenance returned while a request was still being "
            "admitted - the deploy would drain around it"
        )

        fixture.port.release.set()
        async with asyncio.timeout(_PATIENCE):
            response = await call

        assert response.status == "started"
        assert len(tasks.tasks) == 1
        assert not closing.done(), (
            "PUT /maintenance returned as soon as the route had QUEUED the "
            "execution. Starlette has not run the background task yet, so no "
            "stream exists for the drain to count (#1387, finding A)"
        )

        async with asyncio.timeout(_PATIENCE):
            await tasks()  # Starlette runs the queued task after the response
            await closing

        assert fixture.started == [response.execution_id]

    async def test_the_next_request_after_the_set_returns_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture = _HttpFixture(suspend_read=2)
        fixture.install(monkeypatch)

        tasks = BackgroundTasks()
        call = asyncio.create_task(
            commands.execute_workflow_endpoint("wf-ci-self-healing", _Request(), tasks)  # type: ignore[arg-type]
        )
        async with asyncio.timeout(_PATIENCE):
            await fixture.port.in_flight.wait()
        closing = asyncio.create_task(
            set_maintenance_mode(
                SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
            )
        )
        await _let_the_loop_run()
        fixture.port.release.set()
        async with asyncio.timeout(_PATIENCE):
            await call
            await tasks()  # the lease ends when the execution becomes durable
            await closing

        later = BackgroundTasks()
        with pytest.raises(HTTPException) as exc:
            await commands.execute_workflow_endpoint("wf-ci-self-healing", _Request(), later)  # type: ignore[arg-type]

        assert exc.value.status_code == 409
        assert later.tasks == []
