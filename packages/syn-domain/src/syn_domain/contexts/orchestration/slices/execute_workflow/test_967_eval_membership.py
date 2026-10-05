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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import ConcurrencyConflictError, EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration._shared.eval_admission import (
    EvalUnavailableError,
    launch_eval_for,
)
from syn_domain.contexts.orchestration._shared.eval_choice import EvalChoice, LaunchEval
from syn_domain.contexts.orchestration._shared.repository_baseline import BaselineRequest
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_eval import EvalAggregate, EvalId, Goal
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
    EvalMembership,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvalBaselinePin,
    ExecutionStatus,
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
from syn_domain.contexts.orchestration.domain.events.EvalArchivedEvent import (
    EvalArchivedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionAttachedToEvalEvent import (
    ExecutionAttachedToEvalEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionDetachedFromEvalEvent import (
    ExecutionDetachedFromEvalEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
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
from syn_domain.contexts.orchestration.slices.update_eval import UpdateEvalHandler
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_domain.testing.stored_replay import stored_envelopes

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_SHA_MAIN = "a1" * 20
_SHA_DEV = "d2" * 20


def _widgets_at(ref: str) -> BaselineRequest:
    return BaselineRequest(repository=RepositoryRef.from_slug("acme/widgets"), requested_ref=ref)


_WORKFLOW = (
    Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)


class _ExecutionEvent(Protocol):
    @property
    def execution_id(self) -> str: ...


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


@dataclass
class _DefaultBranch:
    """Where each repository's default branch (``main``) is NOW, as ``resolver`` has it."""

    resolver: FakeRevisionResolver

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        return self.resolver.shas.get((repo.slug, "main"))


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
        self.resolver = FakeRevisionResolver(
            shas={("acme/widgets", "main"): _SHA_MAIN, ("acme/widgets", "dev"): _SHA_DEV}
        )
        self.processor = WorkflowExecutionProcessor(
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
            processor=self.processor,
            workflow_repository=self.templates,
            # The run's own commit reader: where each default branch is NOW.
            commit_resolver=_DefaultBranch(self.resolver),
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

    async def create_eval(self, eval_id: str, *refs: str) -> None:
        created = await CreateEvalHandler(self.evals, self.resolver).handle(
            eval_id=EvalId(eval_id),
            name=eval_id,
            goal=Goal("Keep tests green"),
            baseline=[_widgets_at(ref) for ref in refs],
        )
        assert created.success

    async def rebaseline(self, evals: RepositoryAdapter[EvalAggregate], eval_id: str) -> None:
        updated = await UpdateEvalHandler(evals, self.resolver).handle(
            eval_id=EvalId(eval_id), baseline=[_widgets_at("dev")]
        )
        assert updated is not None and updated.success

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

    async def dispatch(
        self,
        execution_id: str,
        choice: EvalChoice | None = None,
        *,
        admitting_through: RepositoryAdapter[EvalAggregate] | None = None,
    ) -> ExecuteWorkflowCommand:
        """The command a dispatcher builds: its eval resolved and admitted once, here."""
        template = await self.templates.get_by_id(self.workflow_id)
        assert template is not None
        launch_eval = await launch_eval_for(
            admitting_through or self.evals, choice or EvalChoice(), template.default_eval_id
        )
        return ExecuteWorkflowCommand(
            aggregate_id=self.workflow_id,
            execution_id=execution_id,
            repos=[RepositoryRef.from_slug("acme/widgets")],
            inputs={"task": "fix it"},
            launch_eval=launch_eval,
        )

    async def run(
        self,
        execution_id: str,
        choice: EvalChoice | None = None,
        *,
        admitting_through: RepositoryAdapter[EvalAggregate] | None = None,
    ) -> None:
        command = await self.dispatch(execution_id, choice, admitting_through=admitting_through)
        await self.execute.handle(command)

    async def stored[E: _ExecutionEvent](self, kind: type[E], execution_id: str) -> list[E]:
        """Events of ``kind`` on the run, as read back from the store's JSON."""
        return [
            envelope.event
            for envelope in await stored_envelopes(self.executions_store)
            if isinstance(envelope.event, kind) and envelope.event.execution_id == execution_id
        ]

    async def started(self, execution_id: str) -> WorkflowExecutionStartedEvent:
        [event] = await self.stored(WorkflowExecutionStartedEvent, execution_id)
        return event

    async def rebuilt(self, execution_id: str) -> WorkflowExecutionAggregate:
        """The run, rebuilt from the stream by a repository that has never seen it."""
        fresh: RepositoryAdapter[WorkflowExecutionAggregate] = _repository(
            self.executions_store, WorkflowExecutionAggregate, "WorkflowExecution"
        )
        execution = await fresh.get_by_id(execution_id)
        assert execution is not None
        return execution

    async def membership(self, execution_id: str) -> EvalMembership:
        return (await self.rebuilt(execution_id)).eval_membership

    async def checked_out(self, execution_id: str) -> dict[str, str]:
        """What the run's first phase clones each repository at - what provisioning reads."""
        execution = await self.rebuilt(execution_id)
        first_phase = execution.start_pins.pinned_phases[0].phase_id
        return execution.start_pins.checkout_for(first_phase).commits


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
    assert started.eval_id is None
    assert await world.membership("exec-1") == EvalMembership()


async def test_a_launch_naming_no_eval_joins_the_workflows_default() -> None:
    world = await _world("eval-default")
    await world.default_to("eval-default")

    await world.run("exec-1")

    started = await world.started("exec-1")
    assert started.eval_id == "eval-default"
    assert started.eval_selection == "workflow_default"
    assert await world.membership("exec-1") == EvalMembership(
        "eval-default", AssociationKind.LAUNCHED, "eval-default"
    )


async def test_an_explicit_eval_wins_over_the_default() -> None:
    world = await _world("eval-default", "eval-explicit")
    await world.default_to("eval-default")

    await world.run("exec-1", _explicit("eval-explicit"))

    started = await world.started("exec-1")
    assert started.eval_id == "eval-explicit"
    assert started.eval_selection == "explicit"


async def test_an_ordinary_run_suppresses_the_default() -> None:
    world = await _world("eval-default")
    await world.default_to("eval-default")

    await world.run("exec-1", EvalChoice(ordinary=True))

    started = await world.started("exec-1")
    assert started.eval_id is None
    assert started.eval_selection == "ordinary"
    assert await world.membership("exec-1") == EvalMembership()


async def test_a_launch_freezes_the_eval_it_joins() -> None:
    world = await _world("eval-1")

    await world.run("exec-1", _explicit("eval-1"))

    stored = await world.evals.get_by_id("eval-1")
    assert stored is not None and stored.is_frozen


# -- the frozen baseline the run starts from (step 4A) ----------------------


async def test_the_start_records_the_baseline_its_eval_froze() -> None:
    world = await _world()
    await world.create_eval("eval-1", "main")

    await world.run("exec-1", _explicit("eval-1"))

    started = await world.started("exec-1")
    assert started.eval_baseline == [
        EvalBaselinePin(repository="acme/widgets", requested_ref="main", commit_sha=_SHA_MAIN)
    ]


async def test_a_run_into_an_eval_with_no_repositories_records_an_empty_baseline() -> None:
    """Empty, not None: "the eval pins nothing" is not "this run is in no eval"."""
    world = await _world("eval-1")

    await world.run("exec-1", _explicit("eval-1"))

    assert (await world.started("exec-1")).eval_baseline == []


async def test_a_run_in_no_eval_writes_no_baseline_key() -> None:
    world = await _world()
    await world.create_eval("eval-1", "main")

    await world.run("exec-1")

    started = await world.started("exec-1")
    assert started.eval_baseline is None
    assert "eval_baseline" not in started.model_dump()


async def test_a_later_run_starts_from_the_frozen_baseline_not_where_the_ref_moved() -> None:
    world = await _world()
    await world.create_eval("eval-1", "main")
    await world.run("exec-1", _explicit("eval-1"))

    world.resolver.shas[("acme/widgets", "main")] = _SHA_DEV
    await world.run("exec-2", _explicit("eval-1"))

    [pin] = (await world.started("exec-2")).eval_baseline or []
    assert pin.commit_sha == _SHA_MAIN


async def test_a_run_in_an_eval_checks_out_the_frozen_sha_after_the_branch_moved() -> None:
    """The baseline is not just recorded: provisioning clones at it.

    The ordinary run launched at the same moment proves the branch really
    moved: it checks out the new head, which the eval run must not.
    """
    world = await _world()
    await world.create_eval("eval-1", "main")
    await world.run("exec-freeze", _explicit("eval-1"))

    world.resolver.shas[("acme/widgets", "main")] = _SHA_DEV
    await world.run("exec-eval", _explicit("eval-1"))
    await world.run("exec-ordinary", EvalChoice(ordinary=True))

    assert await world.checked_out("exec-eval") == {"acme/widgets": _SHA_MAIN}
    assert await world.checked_out("exec-ordinary") == {"acme/widgets": _SHA_DEV}


async def test_a_retried_dispatch_keeps_its_eval_after_the_default_changes() -> None:
    """Resolved once, at the boundary: the retry carries the original eval and SHAs."""
    world = await _world()
    await world.create_eval("eval-a", "main")
    await world.create_eval("eval-b", "dev")
    await world.default_to("eval-a")
    command = await world.dispatch("exec-1")

    await world.default_to("eval-b")
    world.resolver.shas[("acme/widgets", "main")] = _SHA_DEV
    await world.execute.handle(command)

    started = await world.started("exec-1")
    assert (started.eval_id, started.eval_selection) == ("eval-a", "workflow_default")
    assert [pin.commit_sha for pin in started.eval_baseline or []] == [_SHA_MAIN]
    assert await world.checked_out("exec-1") == {"acme/widgets": _SHA_MAIN}


async def test_an_unresolved_launch_of_a_workflow_with_a_default_eval_is_refused() -> None:
    """A dispatcher that made no eval decision must not silently run outside the default."""
    world = await _world("eval-default")
    await world.default_to("eval-default")

    with pytest.raises(ValueError, match="without a resolved eval"):
        await world.execute.handle(
            ExecuteWorkflowCommand(
                aggregate_id=world.workflow_id,
                execution_id="exec-1",
                repos=[RepositoryRef.from_slug("acme/widgets")],
                inputs={"task": "fix it"},
            )
        )

    assert await world.stored(WorkflowExecutionStartedEvent, "exec-1") == []


class _RivalWritesFirst(RepositoryAdapter[EvalAggregate]):
    """Hands out the eval, but first lets ``rival`` write through the real store.

    Only the first read races; the reload after the conflict sees the truth.
    The conflict itself is the real repository's expected-version check.
    """

    def __init__(
        self, inner: RepositoryAdapter[EvalAggregate], rival: Callable[[], Awaitable[None]]
    ) -> None:
        super().__init__(inner.sdk_repository)
        self._rival: Callable[[], Awaitable[None]] | None = rival

    async def get_by_id(self, aggregate_id: str) -> EvalAggregate | None:
        seen = await super().get_by_id(aggregate_id)
        if self._rival is not None:
            rival, self._rival = self._rival, None
            await rival()
        return seen


async def test_a_first_launch_losing_the_freeze_race_records_the_winners_baseline() -> None:
    """Two first launches: the rival re-baselines and launches between our read and our freeze.

    Ours read the eval at ``main``; the stream froze it at ``dev``. The run
    must record ``dev`` - the baseline every other run of the eval starts from
    - never the stale one it read before losing.
    """
    world = await _world()
    await world.create_eval("eval-1", "main")

    async def rebaseline_then_launch() -> None:
        await world.rebaseline(world.evals, "eval-1")
        await world.run("exec-rival", _explicit("eval-1"))

    racing = _RivalWritesFirst(world.evals, rebaseline_then_launch)
    await world.run("exec-1", _explicit("eval-1"), admitting_through=racing)

    for execution_id in ("exec-rival", "exec-1"):
        [pin] = (await world.started(execution_id)).eval_baseline or []
        assert (pin.requested_ref, pin.commit_sha) == ("dev", _SHA_DEV)
    frozen = [
        e for e in await stored_envelopes(world.evals_store) if e.event.event_type == "EvalFrozen"
    ]
    assert len(frozen) == 1


async def test_a_launch_racing_a_baseline_edit_is_refused_and_records_nothing() -> None:
    """The edit won; the eval is not frozen, so the stale read must not start a run."""
    world = await _world()
    await world.create_eval("eval-1", "main")

    async def rebaseline() -> None:
        await world.rebaseline(world.evals, "eval-1")

    racing = _RivalWritesFirst(world.evals, rebaseline)
    with pytest.raises(ConcurrencyConflictError):
        await world.run("exec-1", _explicit("eval-1"), admitting_through=racing)

    assert await world.stored(WorkflowExecutionStartedEvent, "exec-1") == []


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

    assert await world.stored(WorkflowExecutionStartedEvent, "exec-1") == []


async def test_a_launch_into_a_missing_eval_is_refused() -> None:
    world = await _world()

    with pytest.raises(EvalUnavailableError, match="does not exist"):
        await world.run("exec-1", _explicit("eval-missing"))

    assert await world.stored(WorkflowExecutionStartedEvent, "exec-1") == []


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
    [attached] = await world.stored(ExecutionAttachedToEvalEvent, "exec-1")
    assert set(attached.model_dump()) == {"execution_id", "workflow_id", "eval_id", "attached_at"}
    assert attached.eval_id == "eval-1"
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
    assert await world.stored(ExecutionAttachedToEvalEvent, "exec-1") == []
    assert (await world.membership("exec-1")).association_kind is AssociationKind.LAUNCHED


async def test_attaching_to_a_second_eval_is_refused_until_detached() -> None:
    world = await _world("eval-a", "eval-b")
    await world.run("exec-1", _explicit("eval-a"))

    refused = await world.attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-b"))
    )

    assert refused is not None and not refused.success
    assert "detach it" in refused.error
    assert await world.stored(ExecutionAttachedToEvalEvent, "exec-1") == []

    detached = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-a"))
    )
    attached = await world.attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-b"))
    )

    assert detached is not None and detached.success
    assert attached is not None and attached.success
    [detach_event] = await world.stored(ExecutionDetachedFromEvalEvent, "exec-1")
    assert detach_event.association_kind == "launched"
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

    assert await world.stored(ExecutionAttachedToEvalEvent, "exec-1") == []


async def test_a_repeated_attach_after_archive_is_still_a_no_op() -> None:
    """Membership is decided before the eval is asked (Codex review, PR #1562)."""
    world = await _world("eval-1")
    await world.run("exec-1")
    command = AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    first = await world.attach.handle(command)
    assert first is not None and first.success
    stream_before = await stored_envelopes(world.executions_store)

    await world.archive_eval("eval-1")
    again = await world.attach.handle(command)

    assert again is not None and again.success
    assert again.membership == EvalMembership("eval-1", AssociationKind.ATTACHED, None)
    assert await stored_envelopes(world.executions_store) == stream_before
    assert len(await world.stored(ExecutionAttachedToEvalEvent, "exec-1")) == 1


class _ArchiveBeforeWrite:
    """The run's repository, with an archive committed between admission and write.

    Real interleaving, not a stub: the eval is archived through the real
    handler, on the real eval stream, after the attach has read the eval and
    before it writes the run's stream.
    """

    def __init__(self, world: _World, eval_id: str) -> None:
        self._world = world
        self._eval_id = eval_id
        self.saves = 0

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return await self._world.executions.get_by_id(aggregate_id)

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.saves += 1
        await self._world.archive_eval(self._eval_id)
        await self._world.executions.save(aggregate)

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self._world.executions.save_new(aggregate)

    async def exists(self, aggregate_id: str) -> bool:
        return await self._world.executions.exists(aggregate_id)


async def test_an_archive_between_admission_and_write_does_not_undo_the_attach() -> None:
    """Pins the documented admission point (Attach, orchestration ubiquitous language).

    Archive closes admission as of the eval version the attach read. One that
    commits after that read is not seen: the attach lands and is ordered before
    the archive. Every later attach is refused; detach remedies.
    """
    world = await _world("eval-1")
    await world.run("exec-1")
    await world.run("exec-2")
    racing = _ArchiveBeforeWrite(world, "eval-1")
    attach = AttachExecutionToEvalHandler(racing, world.evals)

    late = await attach.handle(
        AttachExecutionToEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    )

    assert racing.saves == 1
    assert late is not None and late.success
    stored_eval = await world.evals.get_by_id("eval-1")
    assert stored_eval is not None and stored_eval.is_archived
    assert [
        envelope.event.eval_id
        for envelope in await stored_envelopes(world.evals_store)
        if isinstance(envelope.event, EvalArchivedEvent)
    ] == ["eval-1"]
    [attached] = await world.stored(ExecutionAttachedToEvalEvent, "exec-1")
    assert attached.eval_id == "eval-1"
    assert await world.membership("exec-1") == EvalMembership(
        "eval-1", AssociationKind.ATTACHED, None
    )

    with pytest.raises(EvalUnavailableError, match="is archived"):
        await world.attach.handle(
            AttachExecutionToEvalCommand(aggregate_id="exec-2", eval_id=EvalId("eval-1"))
        )
    detached = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    )
    assert detached is not None and detached.success
    assert await world.membership("exec-1") == EvalMembership(None, None, None)


async def test_detach_keeps_the_launch_record_and_replay_rebuilds_it() -> None:
    world = await _world("eval-1")
    await world.default_to("eval-1")
    await world.run("exec-1")

    result = await world.detach.handle(
        DetachExecutionFromEvalCommand(aggregate_id="exec-1", eval_id=EvalId("eval-1"))
    )

    assert result is not None and result.success
    started = await world.started("exec-1")
    assert started.eval_id == "eval-1"
    assert started.eval_selection == "workflow_default"
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
    assert await world.stored(ExecutionDetachedFromEvalEvent, "exec-none") == []
    assert await world.stored(ExecutionDetachedFromEvalEvent, "exec-a") == []


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


# -- evolution: eval_baseline is new on WorkflowExecutionStarted ------------


async def test_an_eval_start_written_before_the_baseline_field_still_replays() -> None:
    """A step-3 eval run's start event, stored without `eval_baseline`, reads typed."""
    world = await _world()
    await world.create_eval("eval-1", "main")
    await world.run("exec-1", _explicit("eval-1"))
    payload = (await world.started("exec-1")).model_dump(mode="json")
    del payload["eval_baseline"]

    old = WorkflowExecutionStartedEvent.model_validate(payload)

    assert old.eval_id == "eval-1"
    assert old.eval_baseline is None
    assert "eval_baseline" not in old.model_dump(mode="json")
