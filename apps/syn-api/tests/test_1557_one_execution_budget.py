"""#1557: every execution start shares one budget, waits visibly, and starts once.

THE INCIDENT. Six executions orphaned by an API OOM were resumed. One child
started; five sat `dispatched` for an hour each behind a one-slot semaphore
named for polling, while `POST /execute` ran six runs past it unbounded. The
CLI had printed the children's ids and `syn execution show` 404'd on every
one. Every ~5 minutes the resume processor re-offered each `dispatched` record
and queued ANOTHER start task behind the first.

WHAT IS REAL HERE. The route handler for `POST /workflows/{id}/execute`, the
`BackgroundWorkflowDispatcher`, the `ResumeStartProcessManager`, the admission
gate, the `ExecuteWorkflowHandler`, the `StartResumeHandler`, the
`WorkflowExecutionProcessor` they share, the execution aggregates and the
`GET /executions/{id}` handler. Only the workspace (the in-memory backend) and
the agent (a double that holds each run until told to finish) are fakes, i.e.
exactly the Docker and agent execution.

WHY RUNS ARE HELD AND RELEASED ONE AT A TIME. "At most K at once" is only
observable while runs overlap. Each agent waits on its own event, so the test
decides when every run ends and can look at the queue between any two of them.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from event_sourcing import EventStoreRepository, StreamAlreadyExistsError
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from fastapi import BackgroundTasks, HTTPException

os.environ.setdefault("APP_ENVIRONMENT", "test")

import syn_adapters.storage.repositories as repositories
import syn_api._wiring as wiring
import syn_api._wiring_admission as admission
from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.execution_budget import ExecutionBudget, StartPath
from syn_api.routes.executions import commands, queries
from syn_api.routes.executions.commands import ExecuteWorkflowRequest
from syn_domain.contexts._shared import AdmissionGate
from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution_request import (
    ExecutionRequestAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_execution_request import (
    ExecutionRequestStartProcessManager,
)
from syn_domain.contexts.orchestration.slices.start_resume import (
    ResumeStartProcessManager,
    ResumeStartRecord,
    StartResumeHandler,
)
from syn_domain.contexts.orchestration.slices.start_resume.value_objects import DISPATCH_GRACE
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
from syn_domain.testing.fake_session_repository import FakeSessionRepository
from syn_domain.testing.stored_replay import stored_envelopes

if TYPE_CHECKING:
    from collections.abc import Iterator

    from event_sourcing import DomainEvent

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem

pytestmark = pytest.mark.unit

#: The budget. Smaller than the number of starts, so most of them must queue.
LIMIT = 2

WORKFLOW_ID = "wf-1557"
WORKFLOW_YAML = f"""
id: {WORKFLOW_ID}
name: Budgeted Workflow
description: One phase, so one agent call per execution
type: research
classification: simple

phases:
  - id: think
    name: Think
    order: 1
    prompt_template: "Do research."
"""

#: Long enough for a loaded machine, short enough that a hang fails here.
_WITHIN = 10.0


class _Log:
    """Every event the stores accepted, in the order they were written.

    What the subscription coordinator reads: the ProcessManagers below are fed
    from here, never by hand, so a restart can replay it from the start.
    """

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    def append(self, event: DomainEvent, aggregate_id: str, aggregate_type: str) -> None:
        nonce = len(self.envelopes) + 1
        self.envelopes.append(
            EventEnvelope(
                event=event,
                metadata=EventMetadata(
                    event_type=event.event_type,
                    aggregate_id=aggregate_id,
                    aggregate_type=aggregate_type,
                    aggregate_nonce=nonce,
                    global_nonce=nonce,
                ),
            )
        )


class _Executions:
    """Execution streams, keyed by id; a second NoStream write is refused."""

    def __init__(self, log: _Log) -> None:
        self.streams: dict[str, WorkflowExecutionAggregate] = {}
        self._log = log

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        for envelope in aggregate.get_uncommitted_events():
            self._log.append(envelope.event, aggregate.id or "", "WorkflowExecution")
        self.streams[aggregate.id or ""] = aggregate
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.streams:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return self.streams.get(aggregate_id)

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self.streams


class _Requests:
    """The REAL execution request repository over an in-memory event store.

    Real, so a request read after a restart is rehydrated from what was stored
    as JSON, not handed back as the object the route built.
    """

    def __init__(self, log: _Log) -> None:
        self.client = MemoryEventStoreClient()
        self._repo = RepositoryAdapter(
            EventStoreRepository(
                self.client,
                ExecutionRequestAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "ExecutionRequest",
            )
        )
        self._log = log
        self._seen = 0

    async def save_new(self, aggregate: ExecutionRequestAggregate) -> None:
        await self._repo.save_new(aggregate)
        stored = await stored_envelopes(self.client)
        for envelope in stored[self._seen :]:
            self._log.append(
                envelope.event, envelope.metadata.aggregate_id or "", "ExecutionRequest"
            )
        self._seen = len(stored)

    async def get_by_id(self, aggregate_id: str) -> ExecutionRequestAggregate | None:
        return await self._repo.get_by_id(aggregate_id)


class _Templates:
    def __init__(self, template: WorkflowTemplateAggregate) -> None:
        self._template = template

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._template if aggregate_id == WORKFLOW_ID else None


class _NoArtifacts:
    async def save(self, aggregate: object) -> None:
        del aggregate

    async def get_by_id(self, aggregate_id: str) -> None:
        del aggregate_id


class _HeldAgent:
    """The agent: every run waits inside it until the test lets that run finish.

    Records who was inside at once, so the budget is measured where the work
    is, and who entered at all, so a duplicate start is a second entry.
    """

    def __init__(self, *, failing: bool = False) -> None:
        self._finish = (
            FakeAgentExecutionHandler.failed(exit_code=1)
            if failing
            else FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)
        )
        self.held = not failing
        self.inside: list[str] = []
        self.entered: list[str] = []
        self.peak = 0
        self._release: dict[str, asyncio.Event] = {}
        self.changed = asyncio.Event()

    async def handle(
        self, todo: TodoItem, workspace: ManagedWorkspace, *args: object, **kwargs: object
    ) -> AgentExecutionResult:
        execution_id = todo.execution_id
        self.entered.append(execution_id)
        self.inside.append(execution_id)
        self.peak = max(self.peak, len(self.inside))
        self.changed.set()
        try:
            if self.held:
                await self._release.setdefault(execution_id, asyncio.Event()).wait()
        finally:
            self.inside.remove(execution_id)
            self.changed.set()
        return await self._finish.handle(todo, workspace, *args, **kwargs)  # type: ignore[arg-type]

    def release(self, execution_id: str) -> None:
        self._release.setdefault(execution_id, asyncio.Event()).set()

    async def until(self, predicate: object) -> None:
        assert callable(predicate)
        async with asyncio.timeout(_WITHIN):
            while not predicate():
                self.changed.clear()
                await self.changed.wait()


async def _build_prompt(*args: object, **kwargs: object) -> str:
    del args, kwargs
    return "prompt"


def _command(phase: ExecutablePhase, prompt: str) -> list[str]:
    del phase
    return ["echo", prompt]


def _processor(executions: _Executions, agent: _HeldAgent) -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=executions,  # type: ignore[arg-type]
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=_NoArtifacts(),  # type: ignore[arg-type]
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_build_prompt,  # type: ignore[arg-type]
        command_builder=_command,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,  # type: ignore[arg-type]
    )


class _WorkflowDetails:
    async def get_by_id(self, workflow_id: str) -> None:
        del workflow_id


class _ProjectionManager:
    """What the two route handlers read: nothing is projected yet."""

    def __init__(self) -> None:
        self.store = InMemoryProjectionStore()
        self.workflow_detail = _WorkflowDetails()


class _World:
    """The stores, which survive a restart, and ONE API process over them.

    The process - budget, gate, handlers, dispatcher, ProcessManagers - is
    rebuilt by `restart()`, as a new API container would build it.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.log = _Log()
        self.executions = _Executions(self.log)
        self.requests = _Requests(self.log)
        self.projections = _ProjectionManager()
        self.resume_store = self.projections.store
        self.agent = _HeldAgent()
        definition = WorkflowDefinition.from_yaml(WORKFLOW_YAML)
        self.template = WorkflowTemplateAggregate()
        self.template.create_workflow(build_command_from_definition(definition))
        self._direct: list[asyncio.Task[None]] = []
        self._delivered = 0
        self._checkpoints = MemoryCheckpointStore()
        self._start_process()

        monkeypatch.setattr(wiring, "get_projection_mgr", lambda: self.projections)
        monkeypatch.setattr(commands, "get_projection_mgr", lambda: self.projections)
        monkeypatch.setattr(commands, "ensure_connected", _nothing)
        monkeypatch.setattr(wiring, "get_execute_workflow_handler", self._handler)
        monkeypatch.setattr(repositories, "get_execution_request_repository", lambda: self.requests)

        async def _validated(
            workflow_id: str, request: ExecuteWorkflowRequest
        ) -> tuple[None, dict[str, str], list[object]]:
            del workflow_id
            return None, dict(request.inputs), []

        monkeypatch.setattr(commands, "_validate_execution_request", _validated)

        async def _no_eval(workflow: object, request: ExecuteWorkflowRequest) -> EvalChoice:
            del workflow, request
            return EvalChoice()

        monkeypatch.setattr(commands, "_check_eval_choice", _no_eval)

    def _start_process(self) -> None:
        self.budget = ExecutionBudget(LIMIT)
        self.gate = AdmissionGate(InMemoryMaintenanceAdapter())
        processor = _processor(self.executions, self.agent)
        self.handler = ExecuteWorkflowHandler(
            processor=processor,
            workflow_repository=_Templates(self.template),  # type: ignore[arg-type]
            maintenance=self.gate,  # type: ignore[arg-type]
        )
        self.dispatcher = BackgroundWorkflowDispatcher(
            self.handler,
            budget=self.budget,
            maintenance=self.gate,
            resume_handler=StartResumeHandler(processor, self.executions),  # type: ignore[arg-type]
            requests=self.requests,  # type: ignore[arg-type]
        )
        self.manager = ResumeStartProcessManager(
            resume_starter=self.dispatcher,
            store=self.projections.store,  # type: ignore[arg-type]
        )
        self.request_manager = ExecutionRequestStartProcessManager(
            starter=self.dispatcher,
            store=self.projections.store,  # type: ignore[arg-type]
        )
        # The process-wide singletons the route handlers reach for.
        self._monkeypatch.setattr(admission, "_execution_budget_singleton", self.budget)
        self._monkeypatch.setattr(admission, "_admission_gate_singleton", self.gate)

    async def coordinate(self) -> tuple[int, int]:
        """One coordinator pass: deliver what is new, then process live.

        Returns how many resume and request starts were offered.
        """
        for envelope in self.log.envelopes[self._delivered :]:
            for manager in (self.manager, self.request_manager):
                if envelope.metadata.event_type in (manager.get_subscribed_event_types() or ()):
                    await manager.handle_event(envelope, self._checkpoints)
        self._delivered = len(self.log.envelopes)
        return await self.manager.process_pending(), await self.request_manager.process_pending()

    async def restart(self) -> None:
        """The API process dies with whatever it held, and a new one starts.

        Every task it was running or queueing is gone. The new process replays
        the event log from the start, as a coordinator catching up does.
        """
        for task in [*self._direct, *self.dispatcher._tasks]:  # pyright: ignore[reportPrivateUsage]
            task.cancel()
        await asyncio.gather(
            *self._direct,
            *self.dispatcher._tasks,  # pyright: ignore[reportPrivateUsage]
            return_exceptions=True,
        )
        self._direct = []
        self._start_process()
        self._delivered = 0

    async def _handler(self) -> ExecuteWorkflowHandler:
        return self.handler

    # -- the three entrances ---------------------------------------------

    async def post_execute(self) -> str:
        """`POST /workflows/{id}/execute`, then Starlette running its task."""
        tasks = BackgroundTasks()
        response = await commands.execute_workflow_endpoint(
            WORKFLOW_ID, ExecuteWorkflowRequest(), tasks
        )
        self._direct.append(asyncio.create_task(tasks()))
        return response.execution_id

    async def trigger(self, execution_id: str) -> None:
        await self.dispatcher.run_workflow(WORKFLOW_ID, {}, execution_id)

    async def a_failed_parent_is_resumed(self, parent_id: str) -> str:
        """Run a parent that fails and resume it. The next `coordinate()` records it."""
        failing = _HeldAgent(failing=True)
        result = await _processor(self.executions, failing).run(
            workflow_id=WORKFLOW_ID,
            workflow_name="Budgeted Workflow",
            phases=[
                ExecutablePhase(
                    phase_id="think",
                    name="Think",
                    order=1,
                    agent_config=AgentConfiguration(),
                    prompt_template="Do research.",
                    output_artifact_types=(),
                    timeout_seconds=1800,
                )
            ],
            inputs={},
            execution_id=parent_id,
        )
        assert result.status == "failed", result
        parent = self.executions.streams[parent_id]
        child_id = f"{parent_id}-child"
        parent.resume_execution(
            ResumeExecutionCommand(
                execution_id=parent_id,
                resume_execution_id=child_id,
                acknowledge_external_effects=True,
            )
        )
        await self.executions.save(parent)
        return child_id

    # -- observing -----------------------------------------------------------

    async def shown(self, execution_id: str) -> queries.ExecutionDetailResponse:
        """`GET /executions/{id}`, as `syn execution show` calls it."""
        return await queries.get_execution_endpoint(execution_id)

    async def resume_record(self, parent_id: str) -> ResumeStartRecord:
        row = await self.resume_store.get(ResumeStartProcessManager.PROJECTION_NAME, parent_id)
        assert row is not None
        return ResumeStartRecord.model_validate(row)

    async def age_dispatches_past_the_grace(self, parents: Iterator[str]) -> None:
        """Make every `dispatched` record due for re-offer, as an hour's wait would."""
        for parent_id in parents:
            record = await self.resume_record(parent_id)
            if record.status != "dispatched":  # its child already started
                continue
            await self.resume_store.save(
                ResumeStartProcessManager.PROJECTION_NAME,
                parent_id,
                record.model_copy(
                    update={"dispatched_at": datetime.now(UTC) - DISPATCH_GRACE - timedelta(1)}
                ).model_dump(mode="json"),
            )

    async def drain(self) -> None:
        async with asyncio.timeout(_WITHIN):
            await asyncio.gather(*self._direct)
            while self.dispatcher._tasks:  # pyright: ignore[reportPrivateUsage]
                await asyncio.gather(*self.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
                # Let the done callbacks that remove finished tasks run: an
                # await on finished tasks does not yield to the loop.
                await asyncio.sleep(0)


async def _nothing() -> None:
    return None


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    return _World(monkeypatch)


PARENTS = ("exec-parent-a", "exec-parent-b", "exec-parent-c")


async def _everything_offered(world: _World) -> tuple[list[str], list[str]]:
    """Three resumes, two direct starts and one trigger start: six against two slots."""
    children = [await world.a_failed_parent_is_resumed(p) for p in PARENTS]
    assert await world.coordinate() == (len(PARENTS), 0)
    direct = [await world.post_execute(), await world.post_execute()]
    await world.trigger("exec-trigger-1557")
    await world.agent.until(lambda: len(world.agent.inside) == LIMIT)
    # The direct starts are durable now, and the route's own tasks hold them:
    # the request ProcessManager records them and offers neither.
    assert await world.coordinate() == (0, 0)
    return children, [*direct, "exec-trigger-1557"]


class TestOneBudgetForEveryStartPath:
    async def test_at_most_the_limit_run_and_every_start_eventually_runs_once(
        self, world: _World
    ) -> None:
        children, others = await _everything_offered(world)
        everyone = [*children, *others]
        for _ in range(20):  # every task that could slip in has had its turn
            await asyncio.sleep(0)
        assert len(world.agent.inside) == LIMIT
        assert world.budget.position(everyone[0]) is not None

        # Release one run at a time, in whatever order they are running.
        finished: list[str] = []
        while len(finished) < len(everyone):
            await world.agent.until(
                lambda: len(world.agent.inside) == min(LIMIT, len(everyone) - len(finished))
            )
            running = world.agent.inside[0]
            world.agent.release(running)
            finished.append(running)
            await world.agent.until(lambda r=running: r not in world.agent.inside)

        await world.drain()

        assert world.agent.peak == LIMIT, "the budget was exceeded, or never filled"
        assert sorted(world.agent.entered) == sorted(everyone), "a start ran twice or never"
        for execution_id in everyone:
            stream = world.executions.streams[execution_id]
            assert stream.status.value == "completed", (execution_id, stream.status)
        assert world.budget.matching("exec-") == []


class TestAQueuedStartIsVisible:
    async def test_a_queued_execution_shows_queued_with_its_position_not_404(
        self, world: _World
    ) -> None:
        children, others = await _everything_offered(world)
        queued = [e for e in [*children, *others] if e not in world.agent.inside]
        assert len(queued) == 6 - LIMIT

        shown = [await world.shown(e) for e in queued]

        assert {s.status for s in shown} == {"queued"}
        positions = []
        for detail in shown:
            assert detail.start_queue is not None
            assert detail.start_queue.limit == LIMIT
            assert detail.start_queue.running == LIMIT
            assert detail.start_queue.waiting == len(queued)
            positions.append(detail.start_queue.position)
        assert sorted(positions) == list(range(1, len(queued) + 1))
        paths = {s.workflow_execution_id: s.start_queue.path for s in shown if s.start_queue}
        assert set(paths.values()) <= {StartPath.RESUME, StartPath.DIRECT, StartPath.TRIGGER}

        await _release_everything(world)

    async def test_a_queued_resume_shows_on_its_parent(self, world: _World) -> None:
        children, _ = await _everything_offered(world)
        waiting = [p for p, c in zip(PARENTS, children, strict=True) if c not in world.agent.inside]
        assert waiting, "with two slots and six starts, some resume must be waiting"

        info = await queries._resume_start_of(world.resume_store, waiting[0])  # pyright: ignore[reportPrivateUsage]

        assert info is not None
        assert info.status == "dispatched"
        assert info.start_queue is not None
        assert info.start_queue.position is not None
        assert info.start_queue.path is StartPath.RESUME

        await _release_everything(world)

    async def test_an_unknown_id_is_still_404(self, world: _World) -> None:
        with pytest.raises(HTTPException) as refused:
            await world.shown("exec-nobody-1557")
        assert refused.value.status_code == 404


async def _release_everything(world: _World) -> None:
    """Let every run, present or future, finish, and wait for all of them."""
    world.agent.held = False
    for execution_id in list(world.agent.inside):
        world.agent.release(execution_id)
    await world.drain()


class TestAReOfferWhileQueuedStartsNothingTwice:
    async def test_the_processor_does_not_offer_a_start_it_holds(self, world: _World) -> None:
        """The #1557 duplicate: `dispatched`, past the grace, but only queued."""
        await _everything_offered(world)
        tasks_before = len(world.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]
        await world.age_dispatches_past_the_grace(iter(PARENTS))

        offered = await world.manager.process_pending()

        assert offered == 0
        assert len(world.dispatcher._tasks) == tasks_before  # pyright: ignore[reportPrivateUsage]
        statuses = [(await world.resume_record(p)).status for p in PARENTS]
        assert "dispatched" in statuses, "a queued resume must still be owed its start"
        assert set(statuses) <= {"dispatched", "started"}

        await _release_everything(world)
        assert sorted(world.agent.entered) == sorted(set(world.agent.entered))

    async def test_a_second_start_resume_for_a_queued_child_is_rejected(
        self, world: _World
    ) -> None:
        """The starter refuses it too, for a caller that does not ask first."""
        children, _ = await _everything_offered(world)
        tasks_before = len(world.dispatcher._tasks)  # pyright: ignore[reportPrivateUsage]

        for parent_id in PARENTS:

            async def _unexpected(exc: Exception) -> None:
                raise AssertionError(f"a duplicate start failed: {exc}")

            assert await world.dispatcher.start_resume(parent_id, on_failure=_unexpected) is None

        assert len(world.dispatcher._tasks) == tasks_before  # pyright: ignore[reportPrivateUsage]
        await _release_everything(world)
        for child in children:
            assert world.agent.entered.count(child) == 1

    async def test_a_restarted_process_that_has_no_claim_starts_nothing_twice(
        self, world: _World
    ) -> None:
        """The other half: a re-offer this process does NOT hold - a new process
        after a restart - is refused by the handler once the child exists."""
        children, _ = await _everything_offered(world)
        await _release_everything(world)

        restarted = BackgroundWorkflowDispatcher(
            world.handler,
            budget=ExecutionBudget(LIMIT),
            maintenance=world.gate,
            resume_handler=StartResumeHandler(
                _processor(world.executions, world.agent), world.executions
            ),  # type: ignore[arg-type]
        )
        for parent_id in PARENTS:

            async def _unexpected(exc: Exception) -> None:
                raise AssertionError(f"a duplicate start failed: {exc}")

            await restarted.start_resume(parent_id, on_failure=_unexpected)
        async with asyncio.timeout(_WITHIN):
            await asyncio.gather(*restarted._tasks)  # pyright: ignore[reportPrivateUsage]

        for child in children:
            assert world.agent.entered.count(child) == 1


class TestADirectStartSurvivesARestart:
    """Codex pass 2 on #1574: a queued direct start lived only in memory.

    The 200 had already handed out its id, so a restart during the wait lost
    the run silently - the "200, then the run vanishes" class (#998, #1545).
    The request is now durable before the 200, and a new process starts it.
    """

    async def test_a_queued_direct_start_starts_exactly_once_after_a_restart(
        self, world: _World
    ) -> None:
        running = [await world.post_execute(), await world.post_execute()]
        queued = await world.post_execute()
        await world.agent.until(lambda: len(world.agent.inside) == LIMIT)
        assert queued not in world.agent.inside
        assert await world.coordinate() == (0, 0), "held starts must not be offered"

        await world.restart()

        # Before any process holds it again, the durable record answers.
        shown = await world.shown(queued)
        assert shown.status == "queued"
        assert shown.start_queue is not None
        assert shown.start_queue.held is False

        # The new process replays the log and starts what is still owed.
        assert await world.coordinate() == (0, 1)
        await world.agent.until(lambda: queued in world.agent.inside)
        await _release_everything(world)

        assert await world.coordinate() == (0, 0), "a settled request was offered again"
        assert world.agent.entered.count(queued) == 1
        for execution_id in running:
            assert world.agent.entered.count(execution_id) == 1, "a started run restarted"
        assert world.executions.streams[queued].status.value == "completed"

    async def test_a_request_the_coordinator_has_not_delivered_is_still_found(
        self, world: _World
    ) -> None:
        """Restarted before the to-do list projected the request: the stream answers."""
        await world.post_execute()
        await world.post_execute()
        queued = await world.post_execute()
        await world.agent.until(lambda: len(world.agent.inside) == LIMIT)

        await world.restart()  # no coordinate(): the record was never projected

        shown = await world.shown(queued)
        assert shown.status == "queued"
        assert shown.start_queue is not None
        assert shown.start_queue.held is False

        assert (await world.coordinate())[1] == 1
        await _release_everything(world)
        assert world.agent.entered.count(queued) == 1

    async def test_a_request_recorded_before_a_crash_is_started_exactly_once(
        self, world: _World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Durable, then the process died before it could reply or queue."""

        def _crash(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("the API died before it replied")

        monkeypatch.setattr(commands, "queue_direct_start", _crash)
        with pytest.raises(RuntimeError, match="died"):
            await world.post_execute()
        (requested,) = [
            e.metadata.aggregate_id
            for e in world.log.envelopes
            if e.metadata.event_type == "ExecutionRequested"
        ]
        assert requested is not None

        await world.restart()
        assert await world.coordinate() == (0, 1)
        await world.agent.until(lambda: requested in world.agent.inside)
        await _release_everything(world)

        assert await world.coordinate() == (0, 0)
        assert world.agent.entered.count(requested) == 1
        assert world.executions.streams[requested].status.value == "completed"


class TestTheProcessManagerAndTheRouteRaceForOneRequest:
    async def test_the_route_does_not_fail_when_the_manager_queued_it_first(
        self, world: _World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The coordinator can deliver the durable request and offer it before
        the route claims it: the route must still answer 200, start nothing
        twice, and leave no lease behind."""
        recorded = commands.record_execution_request

        async def _manager_wins_the_race(*args: object, **kwargs: object) -> None:
            await recorded(*args, **kwargs)  # type: ignore[arg-type]
            assert await world.coordinate() == (0, 1)

        monkeypatch.setattr(commands, "record_execution_request", _manager_wins_the_race)

        execution_id = await world.post_execute()

        await world.agent.until(lambda: execution_id in world.agent.inside)
        await _release_everything(world)
        assert world.agent.entered.count(execution_id) == 1
        assert await world.coordinate() == (0, 0)
