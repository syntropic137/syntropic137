"""A fork's resumed phase is handed its predecessors' FILES (#1462, #1465).

`test_start_fork` pins which phases run and what their prompts were given. This
pins what forking exists for: the resumed phase's workspace holds the files its
inherited predecessors produced, byte for byte, at their recorded paths.

Nothing between the agent and the workspace is a double. The parent's agent
writes files, the real collector stores them as artifacts, the real
`ArtifactListProjection` files them under the execution that produced them, and
the real `ArtifactQueryService` reads them back by artifact id - so a lookup
that asks the wrong execution finds nothing, exactly as it does in production.
The only doubles are the agents, and the resumed one is there to read its own
workspace before it does anything.

Two failures these exist to catch, both of which left every other fork test
green:

* injection switched off at `phase_workspace.provision` (#1465) - the resumed
  phase provisions without its inheritance and nothing else notices;
* a fork of a fork (#1462) - the grandchild's inheritance names artifacts the
  ORIGINAL parent stored, and asking the child for them finds none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from event_sourcing import StreamAlreadyExistsError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import ArtifactCreatedEvent
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
    ForkOrigin,
    InheritedPhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ForkExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.fork_handoff import (
    InheritanceUnavailableError,
    inherited_outputs,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_fork import StartForkHandler
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_domain.testing.fake_session_repository import FakeSessionRepository
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.artifacts import ArtifactAggregate
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import Runner

pytestmark = pytest.mark.unit

PARENT = "exec-files-parent"
CHILD = "exec-files-child"
GRANDCHILD = "exec-files-grandchild"
WORKFLOW = "wf-files"
PHASE_IDS = ("research", "plan", "implement")

#: What the parent's research phase writes. The nested file is the one that
#: matters most: `PhaseOutputFile.source_path` carries directories, and a
#: regression that flattened them would still deliver a `nonce.txt` somewhere.
#: The nonce is a value no other run in this module writes, so reading it back
#: in a later workspace can only mean it travelled from the parent.
NONCE = b"nonce 7f3a91c2 - written once, by the parent's research"
PRIMARY = b"# Findings\n\nwhat the parent's research found\n"
RESEARCH_WRITES = (
    ("artifacts/output/findings.md", PRIMARY),
    ("artifacts/output/notes/deep/nonce.txt", NONCE),
)

#: Where those files must land in the workspace of any phase that follows
#: research, and what each must hold. The tree is namespaced by the producing
#: phase, keeps every directory, and the primary deliverable is also aliased at
#: `<phase-id>.md` (ArtifactCollector, #988 / #1149).
EXPECTED_INPUT_TREE = {
    "artifacts/input/research/findings.md": PRIMARY,
    "artifacts/input/research/notes/deep/nonce.txt": NONCE,
    "artifacts/input/research.md": PRIMARY,
}


def _phase(phase_id: str, order: int) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id=phase_id,
        name=phase_id.title(),
        order=order,
        agent_config=AgentConfiguration(),
        prompt_template=f"{phase_id} as pinned",
        output_artifact_types=(),
        timeout_seconds=1800,
    )


class _Executions:
    """Every execution stream in the test, parent and descendants alike."""

    def __init__(self) -> None:
        self.streams: dict[str, WorkflowExecutionAggregate] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.streams[aggregate.id or ""] = aggregate
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.streams:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return self.streams.get(aggregate_id)


class _ProjectedArtifacts:
    """The artifact repository, with the real list projection subscribed to it.

    Saving an artifact applies its `ArtifactCreated` to `ArtifactListProjection`
    as the subscription would, so the query service reads rows filed under the
    execution that actually stored them - which is the ownership #1462 is about.
    """

    def __init__(self) -> None:
        self.projection = ArtifactListProjection(InMemoryProjectionStore())

    async def save(self, aggregate: ArtifactAggregate) -> None:
        for envelope in aggregate.get_uncommitted_events():
            if isinstance(envelope.event, ArtifactCreatedEvent):
                await self.projection.on_artifact_created(envelope.event.model_dump(mode="json"))
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> None:
        del aggregate_id


@dataclass
class _ReadsItsInputs:
    """An agent that first lists what its workspace was provisioned with.

    Records `artifacts/input/**` per phase and then behaves as ``then`` does,
    so a phase's inheritance is read from the WORKSPACE the processor built
    rather than from anything the processor was asked to put there.
    """

    then: FakeAgentExecutionHandler
    inputs: dict[str, dict[str, bytes]] = field(default_factory=dict)

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        self.inputs[todo.phase_id or ""] = dict(
            await workspace.collect_files(["artifacts/input/**"])
        )
        return await self.then.handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            runner,
            on_launch,
        )


async def _prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: dict[str, object],
) -> str:
    del execution_id, workflow_id, repo_url, phase_outputs, inputs
    return phase.prompt_template


def _command(phase: ExecutablePhase, prompt: str) -> list[str]:
    del phase
    return ["echo", prompt]


def _processor(
    executions: _Executions,
    artifacts: _ProjectedArtifacts,
    agent: _ReadsItsInputs | FakeAgentExecutionHandler,
) -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=executions,
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=artifacts,
        artifact_content_storage=None,
        artifact_query=ArtifactQueryService(artifacts.projection),
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_prompt,
        command_builder=_command,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,
    )


async def _parent_failed_in_plan(executions: _Executions, artifacts: _ProjectedArtifacts) -> None:
    """Research writes its files and completes; plan fails; implement never runs."""
    agent = FakeAgentExecutionHandler.scripted(
        FakeAgentExecutionHandler.success(produces=list(RESEARCH_WRITES)),
        FakeAgentExecutionHandler.failed(exit_code=1),
    )
    result = await _processor(executions, artifacts, agent).run(
        workflow_id=WORKFLOW,
        workflow_name="Hand me my files",
        phases=[_phase(p, i + 1) for i, p in enumerate(PHASE_IDS)],
        inputs={"task": "fork me"},
        execution_id=PARENT,
    )
    assert result.status == "failed", result


async def _fork(executions: _Executions, parent_id: str, fork_id: str) -> None:
    parent = executions.streams[parent_id]
    parent.fork_execution(
        ForkExecutionCommand(
            execution_id=parent_id, fork_execution_id=fork_id, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)


async def _start(
    executions: _Executions,
    artifacts: _ProjectedArtifacts,
    parent_id: str,
    agent: _ReadsItsInputs,
) -> str:
    """Start the fork ``parent_id`` admitted, the way the dispatcher does.

    `validate` first, because that is the synchronous check the dispatcher
    makes before it spawns the start - and the one place a refusal is still
    visible to the to-do list. Returns the child's final status.
    """
    handler = StartForkHandler(_processor(executions, artifacts, agent), executions)
    await handler.validate(parent_id)
    result = await handler.handle(parent_id)
    assert result is not None
    return result.status


class TestTheResumedPhaseReceivesTheInheritedFiles:
    async def test_every_file_arrives_with_its_bytes_and_its_directories(self) -> None:
        """RED if `phase_workspace.provision` passes `artifacts=None` (#1465)."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await _parent_failed_in_plan(executions, artifacts)
        await _fork(executions, PARENT, CHILD)

        child = _ReadsItsInputs(FakeAgentExecutionHandler.success())
        assert await _start(executions, artifacts, PARENT, child) == "completed"

        assert list(child.inputs) == ["plan", "implement"]
        assert child.inputs["plan"] == EXPECTED_INPUT_TREE


class TestAForkOfAForkReceivesTheOriginalParentsFiles:
    """The child inherited research from the parent and failed in plan again.

    Forking the CHILD must hand the grandchild research's files - which were
    only ever stored under the PARENT's execution, because the child never ran
    research.
    """

    async def _child_failed_in_plan_too(
        self, executions: _Executions, artifacts: _ProjectedArtifacts
    ) -> None:
        await _parent_failed_in_plan(executions, artifacts)
        await _fork(executions, PARENT, CHILD)
        child = _ReadsItsInputs(FakeAgentExecutionHandler.failed(exit_code=1))
        assert await _start(executions, artifacts, PARENT, child) == "failed"
        assert executions.streams[CHILD].status is ExecutionStatus.FAILED
        await _fork(executions, CHILD, GRANDCHILD)

    async def test_the_grandchild_starts(self) -> None:
        """RED before #1462: refused as 'resolved to no files', for ever."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success())

        assert await _start(executions, artifacts, CHILD, grandchild) == "completed"

    async def test_its_resumed_phase_holds_the_original_parents_files(self) -> None:
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success())
        await _start(executions, artifacts, CHILD, grandchild)

        assert grandchild.inputs["plan"] == EXPECTED_INPUT_TREE

    async def test_the_grandchild_names_the_parent_as_the_owner_of_research(self) -> None:
        """Provenance is kept on the stream, not reconstructed by a wider query."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)
        await _start(
            executions, artifacts, CHILD, _ReadsItsInputs(FakeAgentExecutionHandler.success())
        )

        origin = executions.streams[GRANDCHILD].start_pins.forked_from
        assert origin is not None
        assert origin.parent_execution_id == CHILD
        (research,) = origin.inherited_phases
        assert origin.owner_of(research) == PARENT


class TestStreamsWrittenBeforeTheOwnerWasRecorded:
    """`origin_execution_id` is an event field, so old streams have none."""

    def test_an_inherited_phase_without_one_is_owned_by_the_parent_named(self) -> None:
        origin = ForkOrigin(
            parent_execution_id=PARENT,
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
            resume_phase_id="plan",
        )
        assert origin.owners() == {"research": PARENT}

    async def test_a_fork_its_child_admitted_before_the_fix_still_starts(self) -> None:
        """The admission #1462 stranded: recorded on the CHILD, naming no owner.

        The child's own `forked_from` knows research came from the parent, so
        the start names it rather than asking the child, which holds nothing.
        """
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await TestAForkOfAForkReceivesTheOriginalParentsFiles()._child_failed_in_plan_too(
            executions, artifacts
        )
        child = executions.streams[CHILD]
        admitted = child._admitted_fork
        child._admitted_fork = admitted.model_copy(
            update={
                "inherited_phases": [
                    InheritedPhase(phase_id=p.phase_id, artifact_ids=p.artifact_ids)
                    for p in admitted.inherited_phases
                ]
            }
        )

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success())

        assert await _start(executions, artifacts, CHILD, grandchild) == "completed"
        assert grandchild.inputs["plan"] == EXPECTED_INPUT_TREE


class TestARefusalNamesTheExecutionItAsked:
    async def test_the_owner_is_named_not_the_parent(self) -> None:
        """'Resolved to no files' sent operators to check artifacts that existed.

        The refusal now says WHICH execution was asked, so a wrong owner is
        visible on its face.
        """
        origin = ForkOrigin(
            parent_execution_id=CHILD,
            inherited_phases=[
                InheritedPhase(
                    phase_id="research", artifact_ids=["art-1"], origin_execution_id=PARENT
                )
            ],
            resume_phase_id="plan",
        )
        empty = ArtifactQueryService(ArtifactListProjection(InMemoryProjectionStore()))

        with pytest.raises(InheritanceUnavailableError) as refused:
            await inherited_outputs(empty, origin)

        assert f"execution {PARENT}, which ran phase(s) ['research']" in str(refused.value)
        assert "resolved to no files" not in str(refused.value)
