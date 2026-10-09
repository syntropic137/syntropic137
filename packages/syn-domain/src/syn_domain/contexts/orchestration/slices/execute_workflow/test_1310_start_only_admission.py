"""Start-only admission, and the drain from a claim (#1310 1.3, ADR-072 V5).

Driven through the REAL `ExecuteWorkflowHandler` and `WorkflowExecutionProcessor`
over real event-store repositories; only the stores are in memory and only the
workspace is a double. Provisioning fails on purpose, which gives a scripted,
deterministic run: start, provision attempt, failure, terminal events.

V5 is the claim that matters: a run admitted by one processor and drained by a
FRESH one - sharing nothing but the durable stores - writes the same events as
today's single-call run. A field the drain needs that only lived in `run()`'s
arguments would make the two sequences differ here.
"""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH, DuplicateExecutionError
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
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
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.ports import ExecutorHost
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.stored_replay import stored_envelopes

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOW = (
    Path(__file__).resolve().parents[8] / "workflows" / "sdlc" / "quickfix" / "workflow.yaml"
)
_HOST = ExecutorHost(
    host_id="host-1", container_id="c-1", generation="g1", epoch=ORCHESTRATION_EVENT_EPOCH
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


class _World:
    """Durable stores shared by every processor built over them."""

    def __init__(self) -> None:
        self.definition = WorkflowDefinition.from_file(_WORKFLOW)
        self.store = MemoryEventStoreClient()
        self.todos = InMemoryProjectionStore()
        self.queue = InMemoryExecutionRunQueue()
        self.workspace = _failing_workspace()
        self.templates = RepositoryAdapter(
            EventStoreRepository(
                MemoryEventStoreClient(),
                WorkflowTemplateAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "WorkflowTemplate",
            )
        )

    async def install(self) -> None:
        template = WorkflowTemplateAggregate()
        template.create_workflow(build_command_from_definition(self.definition))
        await self.templates.save_new(template)

    def processor(self, *, queued: bool) -> WorkflowExecutionProcessor:
        """A fresh processor: nothing in it survives from any other."""
        return WorkflowExecutionProcessor(
            execution_repository=RepositoryAdapter(
                EventStoreRepository(
                    self.store,
                    WorkflowExecutionAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                    "WorkflowExecution",
                )
            ),
            session_repository=AsyncMock(),
            workspace_service=self.workspace,
            artifact_repository=AsyncMock(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=AsyncMock(return_value="test prompt"),
            command_builder=MagicMock(return_value=["claude"]),
            todo_projection=ExecutionTodoProjection(store=self.todos),
            run_queue=self.queue if queued else None,
        )

    async def handle(self, processor: WorkflowExecutionProcessor, execution_id: str) -> str:
        handler = ExecuteWorkflowHandler(processor=processor, workflow_repository=self.templates)
        result = await handler.handle(
            ExecuteWorkflowCommand(
                aggregate_id=self.definition.id,
                execution_id=execution_id,
                repos=[RepositoryRef.from_slug("acme/widgets")],
                inputs={"task": "fix it"},
            )
        )
        return result.status

    async def event_types(self, execution_id: str) -> list[str]:
        return [
            e.event.event_type
            for e in await stored_envelopes(self.store)
            if e.metadata.aggregate_id == execution_id
        ]


async def test_a_queued_start_returns_admitted_with_the_start_durable_and_nothing_run() -> None:
    world = _World()
    await world.install()

    status = await world.handle(world.processor(queued=True), "exec-admitted")

    assert status == "admitted"
    assert await world.event_types("exec-admitted") == ["WorkflowExecutionStarted"]
    assert (await world.queue.in_use()).admitted == 1
    world.workspace.create_workspace.assert_not_called()


async def test_a_second_start_of_an_admitted_execution_is_a_duplicate() -> None:
    world = _World()
    await world.install()
    await world.handle(world.processor(queued=True), "exec-twice")

    with pytest.raises(DuplicateExecutionError):
        await world.handle(world.processor(queued=True), "exec-twice")

    assert await world.event_types("exec-twice") == ["WorkflowExecutionStarted"]


async def test_v5_start_then_run_claimed_in_a_fresh_processor_matches_todays_run() -> None:
    world = _World()
    await world.install()
    await world.handle(world.processor(queued=False), "exec-golden")
    golden = await world.event_types("exec-golden")

    await world.handle(world.processor(queued=True), "exec-claimed")
    await world.queue.register(_HOST, capacity=1)
    await world.queue.heartbeat(_HOST.host_id)
    claimed = await world.queue.claim(_HOST.host_id)
    assert claimed is not None
    assert claimed.execution_id == "exec-claimed"
    result = await world.processor(queued=True).run_claimed(claimed)

    assert len(golden) > 2, golden
    assert await world.event_types("exec-claimed") == golden
    assert result.status == "failed"
    world.workspace.create_workspace.assert_called()


async def test_a_reservation_whose_stream_write_failed_is_not_a_duplicate() -> None:
    """reserve -> failed open -> re-offer. The row exists but no start does:
    calling that a duplicate would confirm a start that never happened, so
    the re-offer must admit it for real."""
    world = _World()
    await world.install()
    first = world.processor(queued=True)
    first._journal.open = AsyncMock(side_effect=RuntimeError("event store down"))  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="event store down"):
        await world.handle(first, "exec-reoffered")
    assert await world.event_types("exec-reoffered") == []
    assert (await world.queue.in_use()).opening == 1

    status = await world.handle(world.processor(queued=True), "exec-reoffered")

    assert status == "admitted"
    assert await world.event_types("exec-reoffered") == ["WorkflowExecutionStarted"]
    counts = await world.queue.in_use()
    assert (counts.opening, counts.admitted) == (0, 1)


async def test_a_duplicate_whose_start_died_before_mark_admitted_is_promoted() -> None:
    """The stream exists but the row is still ``opening``: a duplicate, and
    the re-offer finishes the promotion the first start never reached (D2)."""
    world = _World()
    await world.install()
    first = world.processor(queued=True)
    first._run_queue = MagicMock(wraps=world.queue)
    first._run_queue.mark_admitted = AsyncMock(side_effect=RuntimeError("died"))
    with pytest.raises(RuntimeError, match="died"):
        await world.handle(first, "exec-half")
    assert (await world.queue.in_use()).opening == 1

    with pytest.raises(DuplicateExecutionError):
        await world.handle(world.processor(queued=True), "exec-half")

    assert await world.event_types("exec-half") == ["WorkflowExecutionStarted"]
    counts = await world.queue.in_use()
    assert (counts.opening, counts.admitted) == (0, 1)


class _Heads:
    """One repository resolves to a head, the other does not (unknown SHA)."""

    async def head_sha(self, repo: RepositoryRef) -> str | None:
        return {"acme/widgets": "a" * 40}.get(repo.slug)


class _Consumed:
    """What a drain handed the workspace and the prompt, per execution."""

    def __init__(self) -> None:
        #: The execution whose workspace is being provisioned right now.
        self.current = ""
        self.secrets: dict[str, tuple[list[str], dict[str, str]]] = {}
        self.prompts: dict[str, tuple[str | None, dict[str, str]]] = {}


_REPOS = [RepositoryRef.from_slug("acme/widgets"), RepositoryRef.from_slug("acme/gadgets")]
_INPUTS = {"task": "fix {{issue}}", "issue": "#42"}


@pytest.fixture
def consumed(monkeypatch: pytest.MonkeyPatch) -> _Consumed:
    """Let provisioning reach the agent's prompt, recording what it consumed.

    Setup succeeds, the steps between setup and the prompt are no-ops, and the
    prompt builder records its arguments and then fails the phase - so the run
    is still deterministic, but only after every input and repository the
    agent would be launched with has been handed over.
    """
    from syn_adapters.workspace_backends import service

    provisioning = importlib.import_module(
        "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler"
    )

    seen = _Consumed()

    async def create(**kwargs: object) -> object:
        repos = kwargs["repositories"]
        pins = kwargs["pinned_commits"]
        assert isinstance(repos, list) and isinstance(pins, dict)
        seen.secrets[seen.current] = (list(repos), dict(pins))
        return MagicMock()

    async def nothing(*_args: object, **_kwargs: object) -> object:
        return ()

    monkeypatch.setattr(service.SetupPhaseSecrets, "create", staticmethod(create))
    monkeypatch.setattr(provisioning, "verify_provisioned_checkout", nothing)
    monkeypatch.setattr(provisioning, "require_codex_sandbox", nothing)
    for step in (
        "_materialize_claude_plugins",
        "_materialize_and_install_skills",
        "_install_baked_delegation_skill",
        "_install_attribution_hook",
        "_inject_phase_artifacts",
    ):
        monkeypatch.setattr(provisioning.WorkspaceProvisionHandler, step, nothing)
    return seen


def _agent_reaching_world(seen: _Consumed) -> _World:
    world = _World()
    world.workspace.create_workspace.return_value.__aenter__.return_value.run_setup_phase = (
        AsyncMock(return_value=ExecutionResult(exit_code=0, success=True, duration_ms=0.0))
    )

    def create_workspace(**kwargs: object) -> object:
        seen.current = str(kwargs["execution_id"])
        return world.workspace.create_workspace.return_value

    world.workspace.create_workspace.side_effect = create_workspace
    return world


def _prompt_recorder(seen: _Consumed) -> AsyncMock:
    async def build(
        _phase: object,
        execution_id: str,
        _workflow_id: str,
        repo_url: str | None,
        _outputs: object,
        inputs: dict[str, str],
    ) -> str:
        seen.prompts[execution_id] = (repo_url, dict(inputs))
        msg = "stop at the prompt"
        raise RuntimeError(msg)

    return AsyncMock(side_effect=build)


async def _start(world: _World, processor: WorkflowExecutionProcessor, execution_id: str) -> str:
    handler = ExecuteWorkflowHandler(
        processor=processor, workflow_repository=world.templates, commit_resolver=_Heads()
    )
    result = await handler.handle(
        ExecuteWorkflowCommand(
            aggregate_id=world.definition.id,
            execution_id=execution_id,
            repos=list(_REPOS),
            inputs=dict(_INPUTS),
        )
    )
    return result.status


def _normalized(payloads: list[object], execution_id: str) -> list[object]:
    """Event payloads with what legitimately differs between two runs removed."""
    volatile = {"execution_id", "session_id", "workspace_id"}

    def scrub(value: object) -> object:
        if isinstance(value, dict):
            return {
                k: scrub(v)
                for k, v in value.items()
                if k not in volatile and not str(k).endswith("_at") and "duration" not in str(k)
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            return value.replace(execution_id, "<exec>")
        return value

    return [scrub(p) for p in payloads]


async def _payloads(world: _World, execution_id: str) -> list[object]:
    return [
        e.event.model_dump(mode="json")
        for e in await stored_envelopes(world.store)
        if e.metadata.aggregate_id == execution_id
    ]


async def test_v5_a_fresh_processor_consumes_every_input_and_repository_identically(
    consumed: _Consumed,
) -> None:
    """Every input and repository the producer recorded survives admission and
    is handed to the workspace and the prompt identically by a fresh processor:
    both repositories, in order, the unresolved SHA included, and the inputs."""
    world = _agent_reaching_world(consumed)
    await world.install()

    def processor(*, queued: bool) -> WorkflowExecutionProcessor:
        built = world.processor(queued=queued)
        built._prompt_builder = _prompt_recorder(consumed)
        return built

    await _start(world, processor(queued=False), "exec-golden")
    assert await _start(world, processor(queued=True), "exec-claimed") == "admitted"
    assert "exec-claimed" not in consumed.prompts, "admission must not run the agent"
    await world.queue.register(_HOST, capacity=1)
    await world.queue.heartbeat(_HOST.host_id)
    claimed = await world.queue.claim(_HOST.host_id)
    assert claimed is not None
    await processor(queued=True).run_claimed(claimed)

    golden_repos, golden_pins = consumed.secrets["exec-golden"]
    assert golden_repos == [r.https_url for r in _REPOS], "the golden run is the reference"
    assert golden_pins == {"acme/widgets": "a" * 40}
    assert consumed.secrets["exec-claimed"] == consumed.secrets["exec-golden"]
    golden_url, golden_inputs = consumed.prompts["exec-golden"]
    assert golden_inputs["issue"] == "#42"
    assert consumed.prompts["exec-claimed"] == (golden_url, golden_inputs)
    assert _normalized(await _payloads(world, "exec-claimed"), "exec-claimed") == _normalized(
        await _payloads(world, "exec-golden"), "exec-golden"
    )
