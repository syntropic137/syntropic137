"""The lease ends at the durable write, in the processor that does it (#1387).

The admission ticket is a lease on work that does not exist yet. Both
entrances hand the execution to something asynchronous, so the lease has to
outlive the hand-off and end at the one moment the guarantee becomes true:
``journal.open()`` returning, after which the drain can see this execution and
``set_mode(active=True)`` may proceed over it.

The entrance tests prove the gate and the hand-off. They cannot prove THIS,
because their processors are doubles that settle the ticket themselves - the
production hop from the durable write to :meth:`AdmissionTicket.mark_visible`
is not in them at all, and deleting that call leaves them all green. So these
run the REAL :class:`WorkflowExecutionProcessor` over a repository double and
suspend it just past the write, where the answer to "is this lease still
outstanding?" is the whole question.

The failing half matters as much: a write that RAISED started nothing, so
marking it visible would tell a deploy to drain over an execution that does
not exist and never will. The lease must end as an abort instead, and it is
the worker's ``carrying()`` that ends it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from event_sourcing import StreamAlreadyExistsError

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket, carrying
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

pytestmark = pytest.mark.unit

_EXECUTION_ID = "exec-1387-durable-write"
_WORKFLOW_ID = "wf-1387"

#: Long enough that a loaded machine never trips it, short enough that a lease
#: released at the wrong place fails here instead of hanging CI.
_PATIENCE = 5.0


class _Recorded:
    """One execution stream, and whether the processor got as far as opening it."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.fail_with: Exception | None = None

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.opened.append(aggregate.id)
        aggregate._uncommitted_events.clear()  # pyright: ignore[reportPrivateUsage]

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        aggregate._uncommitted_events.clear()  # pyright: ignore[reportPrivateUsage]

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        del aggregate_id
        return None


class _SuspendedTodoList:
    """The to-do list, read by the processor immediately AFTER the write.

    Suspending here is what puts the test inside the window the invariant is
    about: the start event is durable, the execution is visible to the drain,
    and the run is nowhere near finishing. A lease still outstanding at this
    point is one that will not be released until the whole run returns, which
    is the behaviour the entrance doubles cannot distinguish.
    """

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.may_continue = asyncio.Event()

    async def get_pending(self, execution_id: str) -> list[TodoItem]:
        del execution_id
        self.reached.set()
        await self.may_continue.wait()
        return []


async def _noop_prompt_builder(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: dict[str, str],
) -> str:
    del phase, execution_id, workflow_id, repo_url, phase_outputs, inputs
    return "never reached"


def _noop_command_builder(phase: ExecutablePhase, prompt: str) -> list[str]:
    del phase, prompt
    return ["true"]


def _processor(repository: _Recorded, todos: _SuspendedTodoList) -> WorkflowExecutionProcessor:
    """The real processor. Only the two collaborators this is about are doubles."""
    return WorkflowExecutionProcessor(
        execution_repository=repository,
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=_NoArtifacts(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_noop_prompt_builder,
        command_builder=_noop_command_builder,
        todo_projection=todos,
    )


class _NoArtifacts:
    async def save(self, aggregate: object) -> None:
        return None

    async def get_by_id(self, aggregate_id: str) -> None:
        del aggregate_id
        return None


def _one_phase() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id="phase-001",
            name="Never dispatched",
            order=1,
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=(),
            timeout_seconds=1800,
        )
    ]


async def _run(processor: WorkflowExecutionProcessor, ticket: AdmissionTicket) -> None:
    """What both entrances do with an admitted execution, minus the entrance."""
    with carrying(ticket):
        await processor.run(
            workflow_id=_WORKFLOW_ID,
            workflow_name="A workflow",
            phases=_one_phase(),
            inputs={},
            execution_id=_EXECUTION_ID,
            admitted=ticket,
        )


class TestTheLeaseEndsWhenTheStreamIsOpen:
    async def test_the_ticket_is_settled_by_the_time_the_run_continues(self) -> None:
        """The processor itself ends the lease, at the write and not at return."""
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        repository = _Recorded()
        todos = _SuspendedTodoList()
        processor = _processor(repository, todos)

        async with gate.admitting() as ticket:
            run = asyncio.create_task(_run(processor, ticket))

        async with asyncio.timeout(_PATIENCE):
            await todos.reached.wait()

        assert repository.opened == [_EXECUTION_ID], (
            "the run had not reached the durable write, so this proves nothing"
        )
        assert ticket.is_settled, (
            "the start event is durable and the lease is still outstanding - "
            "nothing after this point releases it except the run finishing, so "
            "a deploy would wait out the whole execution it only had to SEE "
            "(#1387, verification finding 3)"
        )

        todos.may_continue.set()
        async with asyncio.timeout(_PATIENCE):
            await run

    async def test_the_transition_may_proceed_while_the_run_is_mid_flight(self) -> None:
        """The consequence, through the real gate: a deploy waits for the write
        and not for the work. Under a lease that ends at worker return this
        hangs until the execution finishes."""
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        repository = _Recorded()
        todos = _SuspendedTodoList()
        processor = _processor(repository, todos)

        async with gate.admitting() as ticket:
            run = asyncio.create_task(_run(processor, ticket))

        async with asyncio.timeout(_PATIENCE):
            await todos.reached.wait()
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

        todos.may_continue.set()
        async with asyncio.timeout(_PATIENCE):
            await run


class TestAWriteThatFailedMarksNothingVisible:
    """`open()` raising started nothing, so the honest end is an abort."""

    async def _the_write_fails_with(self, failure: Exception) -> None:
        gate = AdmissionGate(InMemoryMaintenanceAdapter())
        repository = _Recorded()
        repository.fail_with = failure
        processor = _processor(repository, _SuspendedTodoList())

        async with gate.admitting() as ticket:
            pass

        with carrying(ticket):
            with pytest.raises(type(failure)):
                await processor.run(
                    workflow_id=_WORKFLOW_ID,
                    workflow_name="A workflow",
                    phases=_one_phase(),
                    inputs={},
                    execution_id=_EXECUTION_ID,
                    admitted=ticket,
                )
            assert not ticket.is_settled, (
                "the durable write failed and the processor settled the lease "
                "anyway - a drain told this execution is visible will look for "
                "a stream that was never opened (#1387)"
            )

        assert ticket.is_settled, (
            "the worker left the lease outstanding after a failed write, which "
            "stalls the next set_mode(active=True) for the life of the process"
        )
        async with asyncio.timeout(_PATIENCE):
            await gate.set_mode(active=True, reason="pit stop", actor="deploy")

    async def test_a_store_that_is_down(self) -> None:
        await self._the_write_fails_with(OSError("event store unavailable"))

    async def test_a_re_dispatch_of_an_execution_that_already_exists(self) -> None:
        """The production shape of a refused write: the stream is already there,
        so this run is a duplicate and there is nothing new to be seen."""
        await self._the_write_fails_with(StreamAlreadyExistsError(_EXECUTION_ID, 0))
