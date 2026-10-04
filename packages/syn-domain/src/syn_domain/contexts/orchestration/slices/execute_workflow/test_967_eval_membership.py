"""Which eval a run belongs to, and how it got there (evals plan step 3, #967).

Driven through the REAL handlers - `ExecuteWorkflowHandler` and its processor,
`SetWorkflowDefaultEvalHandler`, `AttachExecutionToEvalHandler`,
`DetachExecutionFromEvalHandler`, and the eval slices that create and archive
an eval - each over a real event-store repository. Only the store is in memory
and only the workspace (IO) is a double. Every assertion is on what the store
holds, because a field dropped between handler and event passes any test that
stops at a double (#955).

Provisioning fails on purpose: the start event is written before any workspace
is asked for, and the failed run is terminal, which is exactly the run a
retroactive attach is for.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_admission import EvalUnavailableError
from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
    EvalMembership,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.domain.commands.AttachExecutionToEvalCommand import (
    AttachExecutionToEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.DetachExecutionFromEvalCommand import (
    DetachExecutionFromEvalCommand,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.domain.commands.SetWorkflowDefaultEvalCommand import (
    SetWorkflowDefaultEvalCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.slices.archive_eval import ArchiveEvalHandler
from syn_domain.contexts.orchestration.slices.attach_execution_to_eval import (
    AttachExecutionToEvalHandler,
)
from syn_domain.contexts.orchestration.slices.create_eval import CreateEvalHandler
from syn_domain.contexts.orchestration.slices.detach_execution_from_eval import (
    DetachExecutionFromEvalHandler,
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
from syn_domain.contexts.orchestration.slices.set_workflow_default_eval import (
    SetWorkflowDefaultEvalHandler,
)
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_domain.testing.stored_replay import stored_envelopes

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOW = (
    Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)


def _failing_workspace() -> MagicMock:
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value.__aenter__.return_value.run_setup_phase = (
        AsyncMock(
            return_value=ExecutionResult(
                exit_code=1, success=False, duration_ms=0.0, stderr="setup failed"
            )
        )
    )
    return workspace_service


def _repository[A](client: MemoryEventStoreClient, aggregate: type[A], name: str) -> A:
    return RepositoryAdapter(EventStoreRepository(client, aggregate, name))  # type: ignore[arg-type,return-value]  # ESP SDK TEvent invariance


class _World:
    """Real repositories over in-memory stores, and the real handlers."""

    def __init__(self) -> None:
        self.definition = WorkflowDefinition.from_file(_WORKFLOW)
        self.executions_store = MemoryEventStoreClient()
        self.evals_store = MemoryEventStoreClient()
        self.templates: RepositoryAdapter[WorkflowTemplateAggregate] = _repository(
            MemoryEventStoreClient(), WorkflowTemplateAggregate, "WorkflowTemplate"
        )
        self.executions: RepositoryAdapter[WorkflowExecutionAggregate] = _repository(
            self.executions_store, WorkflowExecutionAggregate, "WorkflowExecution"
        )
        self.evals: RepositoryAdapter[EvalAggregate] = _repository(
            self.evals_store, EvalAggregate, "Eval"
        )
        processor = WorkflowExecutionProcessor(
            execution_repository=self.executions,
            session_repository=AsyncMock(),
            workspace_service=_failing_workspace(),
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="test prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        )
        self.execute = ExecuteWorkflowHandler(
            processor=processor,
            workflow_repository=self.templates,
            eval_repository=self.evals,
        )
        self.attach = AttachExecutionToEvalHandler(self.executions, self.evals)
        self.detach = DetachExecutionFromEvalHandler(self.executions)
        self.set_default = SetWorkflowDefaultEvalHandler(self.templates, self.evals)

    @property
    def workflow_id(self) -> str:
        return self.definition.id

    async def install(self) -> None:
        template = WorkflowTemplateAggregate()
        template.create_workflow(build_command_from_definition(self.definition))
        await self.templates.save_new(template)

    async def create_eval(self, eval_id: str) -> None:
        created = await CreateEvalHandler(self.evals, FakeRevisionResolver()).handle(
            eval_id=EvalId(eval_id), name=eval_id, goal=Goal("Keep tests green")
        )
        assert created.success

    async def archive_eval(self, eval_id: str) -> None:
        archived = await ArchiveEvalHandler(self.evals).handle(eval_id=EvalId(eval_id))
        assert archived is not None and archived.success

    async def default_to(self, eval_id: str | None) -> None:
        result = await self.set_default.handle(
            SetWorkflowDefaultEvalCommand(
                aggregate_id=self.workflow_id,
                eval_id=EvalId(eval_id) if eval_id is not None else None,
            )
        )
        assert result is not None and result.success

    async def run(self, execution_id: str, choice: EvalChoice | None = None) -> None:
        await self.execute.handle(
            ExecuteWorkflowCommand(
                aggregate_id=self.workflow_id,
                execution_id=execution_id,
                repos=[RepositoryRef.from_slug("acme/widgets")],
                inputs={"task": "fix it"},
                eval_choice=choice or EvalChoice(),
            )
        )

    async def stored(self, event_type: str, execution_id: str) -> list[dict[str, object]]:
        return [
            envelope.event.model_dump()
            for envelope in await stored_envelopes(self.executions_store)
            if envelope.event.event_type == event_type
            and envelope.event.model_dump()["execution_id"] == execution_id
        ]

    async def started(self, execution_id: str) -> dict[str, object]:
        [event] = await self.stored("WorkflowExecutionStarted", execution_id)
        return event

    async def membership(self, execution_id: str) -> EvalMembership:
        """Rebuilt from the stream by a repository that has never seen the run."""
        fresh: RepositoryAdapter[WorkflowExecutionAggregate] = _repository(
            self.executions_store, WorkflowExecutionAggregate, "WorkflowExecution"
        )
        execution = await fresh.get_by_id(execution_id)
        assert execution is not None
        return execution.eval_membership


def _explicit(eval_id: str) -> EvalChoice:
    return EvalChoice(eval_id=EvalId(eval_id))


async def _world(*evals: str) -> _World:
    world = _World()
    await world.install()
    for eval_id in evals:
        await world.create_eval(eval_id)
    return world


# -- launch -----------------------------------------------------------------


async def test_a_launch_with_no_eval_and_no_default_joins_none() -> None:
    world = await _world()

    await world.run("exec-1")

    started = await world.started("exec-1")
    assert "eval_id" not in started or started["eval_id"] is None
    assert await world.membership("exec-1") == EvalMembership()


async def test_a_launch_naming_no_eval_joins_the_workflows_default() -> None:
    world = await _world("eval-default")
    await world.default_to("eval-default")

    await world.run("exec-1")

    started = await world.started("exec-1")
    assert started["eval_id"] == "eval-default"
    assert started["eval_selection"] == "workflow_default"
    assert await world.membership("exec-1") == EvalMembership(
        "eval-default", AssociationKind.LAUNCHED, "eval-default"
    )


async def test_an_explicit_eval_wins_over_the_default() -> None:
    world = await _world("eval-default", "eval-explicit")
    await world.default_to("eval-default")

    await world.run("exec-1", _explicit("eval-explicit"))

    started = await world.started("exec-1")
    assert started["eval_id"] == "eval-explicit"
    assert started["eval_selection"] == "explicit"


async def test_an_ordinary_run_suppresses_the_default() -> None:
    world = await _world("eval-default")
    await world.default_to("eval-default")

    await world.run("exec-1", EvalChoice(ordinary=True))

    started = await world.started("exec-1")
    assert started.get("eval_id") is None
    assert started["eval_selection"] == "ordinary"
    assert await world.membership("exec-1") == EvalMembership()


async def test_a_launch_freezes_the_eval_it_joins() -> None:
    world = await _world("eval-1")

    await world.run("exec-1", _explicit("eval-1"))

    stored = await world.evals.get_by_id("eval-1")
    assert stored is not None and stored.is_frozen


@pytest.mark.parametrize("archived_default", [False, True])
async def test_a_launch_into_an_archived_eval_is_refused_before_it_starts(
    archived_default: bool,
) -> None:
    world = await _world("eval-1")
    if archived_default:
        await world.default_to("eval-1")
    await world.archive_eval("eval-1")

    with pytest.raises(EvalUnavailableError, match="is archived"):
        await world.run("exec-1", None if archived_default else _explicit("eval-1"))

    assert await world.stored("WorkflowExecutionStarted", "exec-1") == []


async def test_a_launch_into_a_missing_eval_is_refused() -> None:
    world = await _world()

    with pytest.raises(EvalUnavailableError, match="does not exist"):
        await world.run("exec-1", _explicit("eval-missing"))

    assert await world.stored("WorkflowExecutionStarted", "exec-1") == []


async def test_changing_the_default_never_reclassifies_a_started_run() -> None:
    world = await _world("eval-a", "eval-b")
    await world.default_to("eval-a")
    await world.run("exec-before")

    await world.default_to("eval-b")
    await world.run("exec-after")

    assert (await world.membership("exec-before")).eval_id == "eval-a"
    assert (await world.membership("exec-after")).eval_id == "eval-b"


def test_a_launch_cannot_name_an_eval_and_ask_for_an_ordinary_run() -> None:
    with pytest.raises(ValueError, match="ordinary run"):
        EvalChoice(eval_id=EvalId("eval-1"), ordinary=True)


# -- workflow default -------------------------------------------------------


async def test_a_default_must_name_a_live_eval_and_can_be_cleared() -> None:
    world = await _world("eval-1")
    await world.archive_eval("eval-1")

    with pytest.raises(EvalUnavailableError):
        await world.default_to("eval-1")
    with pytest.raises(EvalUnavailableError):
        await world.default_to("eval-missing")

    await world.default_to(None)
    workflow = await world.templates.get_by_id(world.workflow_id)
    assert workflow is not None and workflow.default_eval_id is None


# -- attach and detach ------------------------------------------------------


async def test_a_terminal_run_attaches_retroactively_without_the_baseline() -> None:
    world = await _world("eval-1")
    await world.run("exec-1")
    execution = await world.executions.get_by_id("exec-1")
    assert execution is not None and execution.status == ExecutionStatus.FAILED
    started_before = await world.started("exec-1")

    result = await world.attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    )

    assert result is not None and result.success
    [attached] = await world.stored("ExecutionAttachedToEval", "exec-1")
    assert set(attached) == {"execution_id", "workflow_id", "eval_id", "attached_at"}
    assert attached["eval_id"] == "eval-1"
    # The launch record is not rewritten: the run never started from the eval.
    assert await world.started("exec-1") == started_before
    assert await world.membership("exec-1") == EvalMembership(
        "eval-1", AssociationKind.ATTACHED, None
    )
    # Attaching does not freeze the eval; only a launch does.
    stored_eval = await world.evals.get_by_id("eval-1")
    assert stored_eval is not None and not stored_eval.is_frozen


async def test_a_duplicate_attach_succeeds_and_records_nothing() -> None:
    world = await _world("eval-1")
    await world.run("exec-1", _explicit("eval-1"))
    command = AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))

    first = await world.attach.handle(command)
    second = await world.attach.handle(command)

    assert first is not None and first.success
    assert second is not None and second.success
    assert await world.stored("ExecutionAttachedToEval", "exec-1") == []
    assert (await world.membership("exec-1")).association_kind is AssociationKind.LAUNCHED


async def test_attaching_to_a_second_eval_is_refused_until_detached() -> None:
    world = await _world("eval-a", "eval-b")
    await world.run("exec-1", _explicit("eval-a"))

    refused = await world.attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-b"))
    )

    assert refused is not None and not refused.success
    assert "detach it" in refused.error
    assert await world.stored("ExecutionAttachedToEval", "exec-1") == []

    detached = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-a"))
    )
    attached = await world.attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-b"))
    )

    assert detached is not None and detached.success
    assert attached is not None and attached.success
    [detach_event] = await world.stored("ExecutionDetachedFromEval", "exec-1")
    assert detach_event["association_kind"] == "launched"
    assert await world.membership("exec-1") == EvalMembership(
        "eval-b", AssociationKind.ATTACHED, "eval-a"
    )


async def test_attach_to_an_archived_eval_is_refused_and_writes_nothing() -> None:
    world = await _world("eval-1")
    await world.run("exec-1")
    await world.archive_eval("eval-1")

    with pytest.raises(EvalUnavailableError, match="is archived"):
        await world.attach.handle(
            AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
        )
    with pytest.raises(EvalUnavailableError, match="does not exist"):
        await world.attach.handle(
            AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-nope"))
        )

    assert await world.stored("ExecutionAttachedToEval", "exec-1") == []


async def test_detach_keeps_the_launch_record_and_replay_rebuilds_it() -> None:
    world = await _world("eval-1")
    await world.default_to("eval-1")
    await world.run("exec-1")

    result = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    )

    assert result is not None and result.success
    started = await world.started("exec-1")
    assert started["eval_id"] == "eval-1"
    assert started["eval_selection"] == "workflow_default"
    assert await world.membership("exec-1") == EvalMembership(None, None, "eval-1")


async def test_detach_from_no_eval_succeeds_and_from_the_wrong_one_is_refused() -> None:
    world = await _world("eval-a")
    await world.run("exec-none")
    await world.run("exec-a", _explicit("eval-a"))

    none = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-none", eval_id=EvalId("eval-a"))
    )
    wrong = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-a", eval_id=EvalId("eval-b"))
    )

    assert none is not None and none.success
    assert wrong is not None and not wrong.success
    assert await world.stored("ExecutionDetachedFromEval", "exec-none") == []
    assert await world.stored("ExecutionDetachedFromEval", "exec-a") == []


async def test_an_unknown_run_is_not_a_result() -> None:
    world = await _world("eval-1")

    assert (
        await world.attach.handle(
            AttachExecutionToEvalCommand(aggregate_id="exec-nope", eval_id=EvalId("eval-1"))
        )
        is None
    )
    assert (
        await world.detach.handle(
            DetachExecutionFromEvalCommand(aggregate_id="exec-nope", eval_id=EvalId("eval-1"))
        )
        is None
    )
