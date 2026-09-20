"""A queued execution keeps the deploy waiting until it is visible (#1387).

The gate's first shape spent an admission ticket when the ``admitting()`` body
returned. At both entrances that body only QUEUES the work:

* the HTTP route registers a Starlette background task, which runs after the
  response has been sent;
* the trigger dispatcher creates an ``asyncio`` task which then waits behind
  the dispatcher semaphore - for as long as the execution ahead of it runs.

Either way the execution is not durable until ``journal.open()``. So a ticket
released at the hand-off let this happen: B is admitted and queued, the count
of unspent tickets hits zero, ``PUT /maintenance`` persists and returns, the
drain sees only terminal executions because B has no stream, and the swap
cancels B. That is the whole loss this issue exists to prevent, one layer down.

The invariant these tests pin: an admission stays OUTSTANDING until its start
event is durably written, or it definitively aborts. Nothing in between - and
certainly not spawning a task - may release it.

Determinism comes from occupying the real semaphore and from ``asyncio.Event``,
never from sleeps. Both entrances are exercised against their REAL machinery:
``BackgroundWorkflowDispatcher`` with its real semaphore for the trigger path,
and the real route function with a real ``BackgroundTasks`` for the HTTP path.
"""

from __future__ import annotations

import asyncio
import gc
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from event_sourcing import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore
from fastapi import BackgroundTasks

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_api.routes.executions import commands
from syn_api.routes.maintenance import set_maintenance_mode
from syn_api.types import SetMaintenanceModeRequest
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.orchestration import WorkflowTemplateAggregate
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

#: Long enough that a loaded machine never trips it, short enough that a
#: mutation which deadlocks fails here instead of hanging CI forever.
_PATIENCE = 5.0


async def _let_the_loop_run() -> None:
    """Give every runnable task a turn, without giving time a vote.

    Used to assert something has NOT happened. A sleep would make that a race;
    this makes it a fact about scheduling.
    """
    for _ in range(20):
        await asyncio.sleep(0)


def _a_start_event(execution_id: str) -> EventEnvelope[WorkflowExecutionStartedEvent]:
    """What `journal.open()` appends, in the shape the coordinator delivers."""
    return EventEnvelope(
        event=WorkflowExecutionStartedEvent(
            workflow_id="wf-ci-self-healing",
            execution_id=execution_id,
            workflow_name="CI self-healing",
            started_at=datetime.now(UTC),
            total_phases=1,
            inputs={},
        ),
        metadata=EventMetadata(
            event_type=WorkflowExecutionStartedEvent.event_type,
            aggregate_id=execution_id,
            aggregate_type="WorkflowExecution",
            aggregate_nonce=1,
            global_nonce=1,
        ),
    )


class _TheDrainsReadModel:
    """The real `workflow_executions` projection, read the way the deploy
    drain reads it.

    `GET /executions/active` -> `list_active()` keeps exactly the statuses
    below, so a deploy waits on this set and swaps when it empties. Asserting
    against the real projection is the point: the thing the transition must not
    overtake is not the lease counter, it is this list becoming honest.
    """

    #: `queries.list_active` — non-terminal is what holds a deploy open.
    _NON_TERMINAL = ("running", "paused", "pending")

    def __init__(self) -> None:
        self.projection = WorkflowExecutionListProjection(MemoryProjectionStore())
        self._checkpoints = MemoryCheckpointStore()

    async def catch_up(self, envelopes: list[EventEnvelope[WorkflowExecutionStartedEvent]]) -> None:
        for envelope in envelopes:
            await self.projection.handle_event(envelope, self._checkpoints)

    async def active_execution_ids(self) -> list[str]:
        page = await self.projection.get_all(limit=50, status_filter=None)
        return [s.workflow_execution_id for s in page if s.status in self._NON_TERMINAL]


class _StreamOpeningHandler:
    """Stands in for ExecuteWorkflowHandler, at the one hop that matters.

    The real chain is handler -> processor -> ``journal.open()`` -> the lease
    ends. This double keeps the chain's SHAPE - the execution is not visible
    until it says so, and the test decides when - while leaving the dispatcher,
    its semaphore and the gate entirely real, because those are what the defect
    lived in.
    """

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.may_open_the_stream = asyncio.Event()
        self.opened: list[str] = []
        self.appended: list[EventEnvelope[WorkflowExecutionStartedEvent]] = []

    async def validate_stored_declarations(self, _workflow_id: str) -> None:
        return None

    async def handle(self, command: object, *, admitted: AdmissionTicket | None = None) -> None:
        self.reached.set()
        await self.may_open_the_stream.wait()
        execution_id = getattr(command, "execution_id", "") or ""
        self.opened.append(execution_id)
        # `journal.open()`: the start event is in the store, so the drain's
        # read model can see this execution - and only now.
        self.appended.append(_a_start_event(execution_id))
        if admitted is not None:
            admitted.mark_visible()


class TestATriggeredExecutionQueuedBehindTheSemaphore:
    """A is running and holds the dispatcher's only permit. B is admitted and
    queued behind it, with no stream of its own. The operator's transition must
    not return over B."""

    async def test_the_transition_cannot_return_until_b_opens_its_stream(self) -> None:
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _StreamOpeningHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            max_concurrent=1,
            maintenance=gate,
        )

        # A takes the only permit and sits inside the handler, so anything
        # admitted after it is queued rather than running.
        await dispatcher.run_workflow("wf-a", {}, "exec-a")
        async with asyncio.timeout(_PATIENCE):
            await handler.reached.wait()

        await dispatcher.run_workflow("wf-b", {}, "exec-b")
        await _let_the_loop_run()
        assert handler.opened == [], "B started; it was supposed to be queued"

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()

        assert not closing.done(), (
            "PUT /maintenance returned while an admitted execution was still "
            "queued behind the semaphore with no stream. The drain would see "
            "only terminal executions and the swap would kill it (#1387)"
        )

        handler.may_open_the_stream.set()
        async with asyncio.timeout(_PATIENCE):
            await closing
            await asyncio.gather(*list(dispatcher._tasks), return_exceptions=True)

        assert "exec-b" in handler.opened, (
            "the transition returned, but B never became durable - the wait "
            "ended for a reason other than the execution existing"
        )

        # The deploy's next step. The transition waited for B to be visible,
        # so once the projection has caught up the drain counts B and the
        # deploy holds instead of swapping the container out from under it.
        drain = _TheDrainsReadModel()
        await drain.catch_up(handler.appended)
        assert "exec-b" in await drain.active_execution_ids(), (
            "the drain cannot see the execution the transition waited for; "
            "the wait protected nothing"
        )

    async def test_the_transition_returns_once_the_queued_work_is_abandoned(self) -> None:
        """The other end of the lease. An execution that definitively will not
        start has nothing for the drain to count, so it must not hold a deploy
        open for the life of the process."""
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _StreamOpeningHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            max_concurrent=1,
            maintenance=gate,
        )

        await dispatcher.run_workflow("wf-a", {}, "exec-a")
        async with asyncio.timeout(_PATIENCE):
            await handler.reached.wait()
        await dispatcher.run_workflow("wf-b", {}, "exec-b")
        await _let_the_loop_run()

        closing = asyncio.create_task(gate.set_mode(active=True, reason="pit stop", actor="deploy"))
        await _let_the_loop_run()
        assert not closing.done()

        # Shutdown: A is cancelled mid-flight and B is cancelled still queued.
        # Neither produced an execution, so neither leases anything.
        await dispatcher.shutdown()

        async with asyncio.timeout(_PATIENCE):
            mode = await closing
        assert mode.active is True
        assert handler.opened == []


class TestATaskCancelledBeforeItEverRan:
    """The lease has to end on the path where the coroutine body never runs.

    `carrying()` lives inside `_run_with_semaphore`, so it settles on every
    path that coroutine TAKES. A task cancelled between `create_task` and its
    first turn takes none of them: the loop throws `CancelledError` in at the
    very start, the body never executes, and no `finally` of its own is
    reached. The lease then stays outstanding for the life of the process and
    the next `PUT /maintenance` waits on it forever.

    Which way that fails is the point. It does not lose an execution - it
    deadlocks the gate, so the deploy stalls instead of swapping over work it
    cannot see. Safe, and still wrong: a gate that can hang is a gate an
    operator has to sit and watch, and unattended deploys are what this is for.
    """

    async def test_shutdown_before_the_first_turn_releases_the_deploy(self) -> None:
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _StreamOpeningHandler()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            max_concurrent=1,
            maintenance=gate,
        )

        # No loop turn between these two lines, deliberately: the task is
        # created and cancelled without ever being scheduled, which is exactly
        # what a shutdown racing a trigger dispatch does.
        ticket = await dispatcher.run_workflow("wf-a", {}, "exec-a")
        await dispatcher.shutdown()
        await _let_the_loop_run()

        assert ticket is not None
        assert not handler.reached.is_set(), (
            "the execution coroutine ran, so this is no longer the case the "
            "test is about - it must be cancelled before its first turn"
        )
        assert ticket.is_settled, (
            "a lease granted for a task that was cancelled before it ever ran "
            "was never returned; nothing else will ever return it (#1387)"
        )

        async with asyncio.timeout(_PATIENCE):
            mode = await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        assert mode.active is True
        assert handler.opened == []

    async def test_the_lease_is_settled_exactly_once(self) -> None:
        """The backstop must not double-count. `_lease_ended` decrements, so a
        second settlement would take the gate's outstanding count negative and
        let a LATER admission's lease be overtaken by a transition."""
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        handler = _StreamOpeningHandler()
        handler.may_open_the_stream.set()
        dispatcher = BackgroundWorkflowDispatcher(
            handler,  # type: ignore[arg-type]
            max_concurrent=1,
            maintenance=gate,
        )

        # This one runs to completion and opens its stream, so `mark_visible()`
        # ends the lease and the task's done callback aborts afterwards.
        await dispatcher.run_workflow("wf-a", {}, "exec-a")
        async with asyncio.timeout(_PATIENCE):
            await asyncio.gather(*dispatcher._tasks)
        await _let_the_loop_run()

        assert handler.opened == ["exec-a"]
        assert gate._outstanding == 0, (
            f"the gate has {gate._outstanding} outstanding leases after one "
            "admission settled once; a second settlement per ticket would let "
            "a transition return over a lease that is still held"
        )


# -- The manual path ----------------------------------------------------------


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
    """A workflow that exists, so the route reaches the gate at all."""

    def __init__(self) -> None:
        self._workflow = WorkflowTemplateAggregate()

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return self._workflow


async def _nothing_to_connect() -> None:
    return None


class _DelayedExecution:
    """The background task, held before it opens the execution's stream."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.may_open_the_stream = asyncio.Event()
        self.opened: list[str] = []

    async def __call__(
        self,
        *,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[object],
        admitted: AdmissionTicket | None = None,
    ) -> None:
        del workflow_id, inputs, task, repos
        self.reached.set()
        await self.may_open_the_stream.wait()
        self.opened.append(execution_id)
        if admitted is not None:
            admitted.mark_visible()


class TestAnHttpExecutionStillInsideItsBackgroundTask:
    """``POST /workflows/{id}/execute`` returns 200 as soon as the task is
    queued. Until Starlette runs that task and it opens a stream, the drain
    cannot see the execution - and the ticket must still be outstanding."""

    async def test_the_transition_cannot_return_until_the_task_opens_its_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import syn_api._wiring as wiring

        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        execution = _DelayedExecution()
        monkeypatch.setattr(wiring, "_admission_gate_singleton", gate, raising=False)
        monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
        monkeypatch.setattr(commands, "execute", execution)

        tasks = BackgroundTasks()
        response = await commands.execute_workflow_endpoint(
            "wf-ci-self-healing",
            _Request(),  # type: ignore[arg-type]
            tasks,
        )
        assert response.status == "started"

        closing = asyncio.create_task(
            set_maintenance_mode(
                SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
            )
        )
        await _let_the_loop_run()

        assert not closing.done(), (
            "PUT /maintenance returned after the route had merely queued the "
            "background task. The caller holds a 200 for an execution with no "
            "stream, and the drain that follows would not count it (#1387)"
        )

        # Starlette runs the queued task, but it is held before journal.open().
        running = asyncio.create_task(tasks())
        async with asyncio.timeout(_PATIENCE):
            await execution.reached.wait()
        await _let_the_loop_run()

        assert not closing.done(), (
            "the transition returned once the background task had STARTED. "
            "Starting is not being visible: the stream is not open yet"
        )

        execution.may_open_the_stream.set()
        async with asyncio.timeout(_PATIENCE):
            await running
            await closing

        assert execution.opened == [response.execution_id]

    async def test_a_task_that_never_starts_an_execution_releases_the_deploy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The negative control, and the anti-hang. If the lease only ever
        ended at ``mark_visible()``, a failed background task would stall every
        later deploy for the life of the process."""
        import syn_api._wiring as wiring

        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        monkeypatch.setattr(wiring, "_admission_gate_singleton", gate, raising=False)
        monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)

        async def _explodes(**_kwargs: object) -> None:
            raise RuntimeError("the workflow could not be loaded")

        monkeypatch.setattr(commands, "execute", _explodes)

        tasks = BackgroundTasks()
        await commands.execute_workflow_endpoint(
            "wf-ci-self-healing",
            _Request(),  # type: ignore[arg-type]
            tasks,
        )

        closing = asyncio.create_task(
            set_maintenance_mode(
                SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
            )
        )
        await _let_the_loop_run()
        assert not closing.done()

        async with asyncio.timeout(_PATIENCE):
            await tasks()
            mode = await closing

        assert mode.active is True
        assert mode.since is not None
        assert mode.since <= datetime.now(UTC)

    async def test_a_queued_task_starlette_never_runs_releases_the_deploy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The HTTP twin of a task cancelled before its first turn.

        Starlette runs background tasks after the response has been sent, and
        promises nothing about a response that is never sent - a client that
        disappears mid-send, a middleware that swaps the response out. The
        queued coroutine is then never entered, so the `carrying()` inside it
        never settles, and every later deploy waits on that lease forever.

        Expressed here as the framework dropping the queued task without
        calling it, which is the only observable difference between "Starlette
        will run this" and "Starlette never will".
        """
        import syn_api._wiring as wiring

        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        execution = _DelayedExecution()
        monkeypatch.setattr(wiring, "_admission_gate_singleton", gate, raising=False)
        monkeypatch.setattr(commands, "ensure_connected", _nothing_to_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
        monkeypatch.setattr(commands, "execute", execution)

        tasks = BackgroundTasks()
        await commands.execute_workflow_endpoint(
            "wf-ci-self-healing",
            _Request(),  # type: ignore[arg-type]
            tasks,
        )

        closing = asyncio.create_task(
            set_maintenance_mode(
                SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
            )
        )
        await _let_the_loop_run()
        assert not closing.done(), (
            "the transition returned while the queued task might still run and "
            "open a stream; the lease was released at the hand-off (#1387)"
        )

        # The response was never sent, so the queued task is discarded unrun.
        del tasks
        gc.collect()
        await _let_the_loop_run()

        async with asyncio.timeout(_PATIENCE):
            mode = await closing

        assert mode.active is True
        assert execution.opened == [], (
            "the background task ran after all, so this test no longer covers "
            "the case where Starlette never invokes it"
        )
