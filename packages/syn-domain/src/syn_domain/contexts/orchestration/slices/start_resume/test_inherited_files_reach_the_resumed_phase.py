"""A resume's resumed phase is handed its predecessors' FILES (#1462, #1465).

`test_start_resume` pins which phases run and what their prompts were given. This
pins what resuming exists for: the resumed phase's workspace holds the files its
inherited predecessors produced, byte for byte, at their recorded paths.

Nothing between the agent and the workspace is a double. The parent's agent
writes files, the real collector stores them as artifacts, the real
`ArtifactListProjection` files them under the execution that produced them, and
the real `ArtifactQueryService` reads them back by artifact id - so a lookup
that asks the wrong execution finds nothing, exactly as it does in production.
The only doubles are the agents, and the resumed one is there to read its own
workspace before it does anything.

Two failures these exist to catch, both of which left every other resume test
green:

* injection switched off at `phase_workspace.provision` (#1465) - the resumed
  phase provisions without its inheritance and nothing else notices;
* a resume of a resume (#1462) - the grandchild's inheritance names artifacts the
  ORIGINAL parent stored, and asking the child for them finds none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import TYPE_CHECKING

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    StreamAlreadyExistsError,
    resolve_event_type,
)
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import ArtifactCreatedEvent
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.replay import evt
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    read_admitted_resume,
    read_start_pins,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    ExecutionStatus,
    InheritedPhase,
    ResumeOrigin,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    InheritanceUnavailableError,
    inherited_outputs,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
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
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
        PhaseCostLimit,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_push import (
        PushObserver,
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


#: What the CHILD's plan writes, in a child that inherited research and ran plan
#: itself. A second nonce, so a plan file in a later workspace can only have come
#: from the child - the parent never completed plan.
PLAN_NONCE = b"nonce 2c9e04b1 - written once, by the child's plan"
PLAN_PRIMARY = b"# Plan\n\nwhat the child planned\n"
PLAN_WRITES = (
    ("artifacts/output/outline.md", PLAN_PRIMARY),
    ("artifacts/output/steps/nonce.txt", PLAN_NONCE),
)
EXPECTED_PLAN_TREE = {
    "artifacts/input/plan/outline.md": PLAN_PRIMARY,
    "artifacts/input/plan/steps/nonce.txt": PLAN_NONCE,
    "artifacts/input/plan.md": PLAN_PRIMARY,
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
    """Every execution stream in the test, parent and descendants alike.

    Every event is also kept as the JSON it would be stored as. With ``wire``,
    a stream is READ back from that JSON, the way the event store hands it
    back: typed where the payload validates, `GenericDomainEvent` where it does
    not (ADR-023). That is the hop an owner can be dropped at while every
    in-memory aggregate still holds it.
    """

    def __init__(self, *, wire: bool = False) -> None:
        self.streams: dict[str, WorkflowExecutionAggregate] = {}
        self.written: dict[str, list[tuple[EventMetadata, str]]] = {}
        self._wire = wire

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        # The type goes in the metadata on append, as the repository puts it.
        self.written.setdefault(aggregate.id or "", []).extend(
            (
                e.metadata.model_copy(update={"event_type": e.event.event_type}),
                json.dumps(e.event.model_dump(mode="json")),
            )
            for e in aggregate.get_uncommitted_events()
        )
        self.streams[aggregate.id or ""] = aggregate
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.streams:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if not self._wire or aggregate_id not in self.streams:
            return self.streams.get(aggregate_id)
        return self.replayed(aggregate_id)

    def replayed(self, aggregate_id: str) -> WorkflowExecutionAggregate:
        """The stream as rehydrated from what was written, never the live object."""
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(
            [
                EventEnvelope(event=_as_stored(metadata, payload), metadata=metadata)
                for metadata, payload in self.written[aggregate_id]
            ]
        )
        return fresh

    def payload(self, aggregate_id: str, event_type: str) -> str:
        """The one ``event_type`` payload written to ``aggregate_id``, as JSON."""
        (found,) = [p for m, p in self.written[aggregate_id] if m.event_type == event_type]
        return found


def _as_stored(metadata: EventMetadata, payload: str) -> DomainEvent:
    """An event as the gRPC store deserialises it (`_proto_to_envelope`)."""
    event_type = metadata.event_type or ""
    concrete = resolve_event_type(event_type)
    if concrete is not None:
        try:
            return concrete.model_validate_json(payload)
        except ValidationError:
            pass
    return GenericDomainEvent(event_type=event_type, **json.loads(payload))


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
        cost_limit: PhaseCostLimit | None = None,
        on_push: PushObserver | None = None,
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
        inputs={"task": "resume me"},
        execution_id=PARENT,
    )
    assert result.status == "failed", result


async def _resume(executions: _Executions, parent_id: str, resume_id: str) -> None:
    parent = await executions.get_by_id(parent_id)
    assert parent is not None
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=parent_id, resume_execution_id=resume_id, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)


async def _start(
    executions: _Executions,
    artifacts: _ProjectedArtifacts,
    parent_id: str,
    agent: _ReadsItsInputs,
) -> str:
    """Start the resume ``parent_id`` admitted, the way the dispatcher does.

    `validate` first, because that is the synchronous check the dispatcher
    makes before it spawns the start - and the one place a refusal is still
    visible to the to-do list. Returns the child's final status.
    """
    handler = StartResumeHandler(_processor(executions, artifacts, agent), executions)
    await handler.validate(parent_id)
    result = await handler.handle(parent_id)
    assert result is not None
    return result.status


class TestTheResumedPhaseReceivesTheInheritedFiles:
    async def test_every_file_arrives_with_its_bytes_and_its_directories(self) -> None:
        """RED if `phase_workspace.provision` passes `artifacts=None` (#1465)."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await _parent_failed_in_plan(executions, artifacts)
        await _resume(executions, PARENT, CHILD)

        child = _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))
        assert await _start(executions, artifacts, PARENT, child) == "completed"

        assert list(child.inputs) == ["plan", "implement"]
        assert child.inputs["plan"] == EXPECTED_INPUT_TREE


class TestAResumeOfAResumeReceivesTheOriginalParentsFiles:
    """The child inherited research from the parent and failed in plan again.

    Resuming the CHILD must hand the grandchild research's files - which were
    only ever stored under the PARENT's execution, because the child never ran
    research.
    """

    async def _child_failed_in_plan_too(
        self, executions: _Executions, artifacts: _ProjectedArtifacts
    ) -> None:
        await _parent_failed_in_plan(executions, artifacts)
        await _resume(executions, PARENT, CHILD)
        child = _ReadsItsInputs(FakeAgentExecutionHandler.failed(exit_code=1))
        assert await _start(executions, artifacts, PARENT, child) == "failed"
        assert executions.streams[CHILD].status is ExecutionStatus.FAILED
        await _resume(executions, CHILD, GRANDCHILD)

    async def test_the_grandchild_starts(self) -> None:
        """RED before #1462: refused as 'resolved to no files', for ever."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))

        assert await _start(executions, artifacts, CHILD, grandchild) == "completed"

    async def test_its_resumed_phase_holds_the_original_parents_files(self) -> None:
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))
        await _start(executions, artifacts, CHILD, grandchild)

        assert grandchild.inputs["plan"] == EXPECTED_INPUT_TREE

    async def test_the_grandchild_names_the_parent_as_the_owner_of_research(self) -> None:
        """Provenance is kept on the stream, not reconstructed by a wider query."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await self._child_failed_in_plan_too(executions, artifacts)
        await _start(
            executions,
            artifacts,
            CHILD,
            _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)),
        )

        origin = executions.streams[GRANDCHILD].start_pins.resumed_from
        assert origin is not None
        assert origin.parent_execution_id == CHILD
        (research,) = origin.inherited_phases
        assert origin.owner_of(research) == PARENT


class TestAResumeOfAChildThatRanAPhaseItself:
    """Mixed ownership: the child INHERITED research and RAN plan, then failed.

    Resuming that child hands the grandchild two phases held by two different
    executions - research by the parent, plan by the child - so an inheritance
    read from any ONE execution is short a phase. Read back from the stored
    JSON (``wire``), since the owners are what a serializer could drop.
    """

    @staticmethod
    async def _child_ran_plan_and_failed_in_implement(
        executions: _Executions, artifacts: _ProjectedArtifacts
    ) -> None:
        await _parent_failed_in_plan(executions, artifacts)
        await _resume(executions, PARENT, CHILD)
        child = _ReadsItsInputs(
            FakeAgentExecutionHandler.scripted(
                FakeAgentExecutionHandler.success(produces=list(PLAN_WRITES)),
                FakeAgentExecutionHandler.failed(exit_code=1),
            )
        )
        assert await _start(executions, artifacts, PARENT, child) == "failed"
        assert list(child.inputs) == ["plan", "implement"]
        await _resume(executions, CHILD, GRANDCHILD)

    async def _grandchild(self) -> tuple[_Executions, _ReadsItsInputs, str]:
        executions, artifacts = _Executions(wire=True), _ProjectedArtifacts()
        await self._child_ran_plan_and_failed_in_implement(executions, artifacts)
        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))
        status = await _start(executions, artifacts, CHILD, grandchild)
        return executions, grandchild, status

    async def test_each_phase_is_read_from_the_execution_that_produced_it(self) -> None:
        _, grandchild, status = await self._grandchild()

        assert status == "completed"
        assert list(grandchild.inputs) == ["implement"]
        assert grandchild.inputs["implement"] == EXPECTED_INPUT_TREE | EXPECTED_PLAN_TREE

    async def test_the_stored_stream_names_each_owner(self) -> None:
        executions, _, _ = await self._grandchild()

        origin = executions.replayed(GRANDCHILD).start_pins.resumed_from
        assert origin is not None
        assert origin.parent_execution_id == CHILD
        assert origin.owners() == {"research": PARENT, "plan": CHILD}

    async def test_the_childs_stored_admission_names_each_owner(self) -> None:
        """The other event carrying owners, read back as the start reads it."""
        executions, _, _ = await self._grandchild()

        admitted = executions.replayed(CHILD).resume_start_command().resumed_from
        assert admitted.owners() == {"research": PARENT, "plan": CHILD}


class TestThisReleaseReadsTheCarriedOwnersBack:
    """Both ways this release loads what it wrote, each keeping the owners.

    Typed is the normal path, and the key carried beside the phases must not
    cost it: an event that stopped validating typed would silently replay
    generically for ever. Generic (ADR-023) is what any OTHER validation
    failure falls back to, and the owners must survive that too.
    """

    @staticmethod
    async def _written() -> _Executions:
        executions, artifacts = _Executions(wire=True), _ProjectedArtifacts()
        await TestAResumeOfAChildThatRanAPhaseItself._child_ran_plan_and_failed_in_implement(
            executions, artifacts
        )
        await _start(
            executions,
            artifacts,
            CHILD,
            _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)),
        )
        return executions

    async def test_typed(self) -> None:
        executions = await self._written()

        resumed = ExecutionResumedEvent.model_validate_json(
            executions.payload(CHILD, "ExecutionResumed")
        )
        started = WorkflowExecutionStartedEvent.model_validate_json(
            executions.payload(GRANDCHILD, "WorkflowExecutionStarted")
        )

        assert {p.phase_id: p.origin_execution_id for p in resumed.inherited_phases} == {
            "research": PARENT,
            "plan": None,  # the child ran it: the execution the event names
        }
        assert started.resumed_from is not None
        assert started.resumed_from.owners() == {"research": PARENT, "plan": CHILD}

    async def test_generic(self) -> None:
        executions = await self._written()

        resumed = GenericDomainEvent(
            event_type="ExecutionResumed",
            **json.loads(executions.payload(CHILD, "ExecutionResumed")),
        )
        started = GenericDomainEvent(
            event_type="WorkflowExecutionStarted",
            **json.loads(executions.payload(GRANDCHILD, "WorkflowExecutionStarted")),
        )

        admitted = read_admitted_resume(resumed).inherited_phases
        assert {p.phase_id: p.origin_execution_id for p in admitted} == {
            "research": PARENT,
            "plan": None,
        }
        origin = read_start_pins(started).resumed_from
        assert origin is not None
        assert origin.owners() == {"research": PARENT, "plan": CHILD}


# --- what a release from BEFORE the owner reads -----------------------------
#
# The shapes below are frozen copies of these models as every release up to
# v0.31 declared them, before `origin_execution_id` existed. They are what a
# ROLLBACK reads with, so they must not be updated to match the current models:
# the point is to keep reading with the old ones. `extra="forbid"` on all of
# them, as it was.


class _V031InheritedPhase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    artifact_ids: list[str]


class _V031ResumeOrigin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_execution_id: str
    inherited_phases: list[_V031InheritedPhase]
    resume_phase_id: str


class _V031ExecutionResumed(DomainEvent):
    workflow_id: str
    execution_id: str
    resume_execution_id: str
    inherited_phases: list[_V031InheritedPhase]
    resume_phase_id: str
    resumed_at: datetime
    cancellation_overridden: bool = False
    external_effects_acknowledged: bool = False


class _V031WorkflowExecutionStarted(DomainEvent):
    workflow_id: str
    execution_id: str
    workflow_name: str
    started_at: datetime
    total_phases: int
    inputs: dict[str, str]
    expected_completion_at: datetime | None = None
    phase_definitions: list[object] | None = None
    pinned_phases: list[ExecutablePhase] | None = None
    source_commits: list[SourceCommit] | None = None
    resumed_from: _V031ResumeOrigin | None = None


def _v031_load(event_class: type[DomainEvent], event_type: str, payload: str) -> DomainEvent:
    """How v0.31's store loads a payload: typed if it validates, else generic."""
    try:
        return event_class.model_validate_json(payload)
    except ValidationError:
        return GenericDomainEvent(event_type=event_type, **json.loads(payload))


def _v031_read_origin(payload: str) -> _V031ResumeOrigin:
    """v0.31's `read_resume_origin`, on v0.31's load of a start event."""
    event = _v031_load(_V031WorkflowExecutionStarted, "WorkflowExecutionStarted", payload)
    return _V031ResumeOrigin.model_validate(evt(event, "resumed_from"))


def _v031_read_admitted(payload: str) -> list[_V031InheritedPhase]:
    """v0.31's `read_inherited_phases`, on v0.31's load of an `ExecutionResumed`."""
    event = _v031_load(_V031ExecutionResumed, "ExecutionResumed", payload)
    return TypeAdapter(list[_V031InheritedPhase]).validate_python(evt(event, "inherited_phases"))


class TestAReleaseBeforeTheOwnerReadsWhatThisOneWrites:
    """The codex review of #1466: a ROLLBACK must still replay these streams.

    The owner first went INSIDE `InheritedPhase`, and every model that nests it
    forbids extra fields - so v0.31 could not read any resume this release wrote,
    and a resume's origin that fails to read is deliberately fatal. It is carried
    beside the phases instead. These read what the real flow wrote with the
    frozen v0.31 shapes above.
    """

    async def test_a_first_resume_is_written_exactly_as_v031_wrote_it(self) -> None:
        """Nothing new at all: v0.31 validates both events TYPED."""
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await _parent_failed_in_plan(executions, artifacts)
        await _resume(executions, PARENT, CHILD)
        await _start(
            executions,
            artifacts,
            PARENT,
            _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)),
        )

        resumed = executions.payload(PARENT, "ExecutionResumed")
        started = executions.payload(CHILD, "WorkflowExecutionStarted")

        assert isinstance(_V031ExecutionResumed.model_validate_json(resumed), _V031ExecutionResumed)
        assert isinstance(
            _V031WorkflowExecutionStarted.model_validate_json(started),
            _V031WorkflowExecutionStarted,
        )

    async def test_v031_replays_a_mixed_resume_and_loses_only_the_owner(self) -> None:
        executions, artifacts = _Executions(wire=True), _ProjectedArtifacts()
        await TestAResumeOfAChildThatRanAPhaseItself._child_ran_plan_and_failed_in_implement(
            executions, artifacts
        )
        await _start(
            executions,
            artifacts,
            CHILD,
            _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE)),
        )

        admitted = _v031_read_admitted(executions.payload(CHILD, "ExecutionResumed"))
        origin = _v031_read_origin(executions.payload(GRANDCHILD, "WorkflowExecutionStarted"))

        assert [p.phase_id for p in admitted] == ["research", "plan"]
        assert origin.parent_execution_id == CHILD
        assert [p.phase_id for p in origin.inherited_phases] == ["research", "plan"]
        assert origin.resume_phase_id == "implement"


class TestStreamsWrittenBeforeTheOwnerWasRecorded:
    """`origin_execution_id` is an event field, so old streams have none."""

    def test_an_inherited_phase_without_one_is_owned_by_the_parent_named(self) -> None:
        origin = ResumeOrigin(
            parent_execution_id=PARENT,
            inherited_phases=[InheritedPhase(phase_id="research", artifact_ids=["art-1"])],
            resume_phase_id="plan",
        )
        assert origin.owners() == {"research": PARENT}

    async def test_a_resume_its_child_admitted_before_the_fix_still_starts(self) -> None:
        """The admission #1462 stranded: recorded on the CHILD, naming no owner.

        The child's own `resumed_from` knows research came from the parent, so
        the start names it rather than asking the child, which holds nothing.
        """
        executions, artifacts = _Executions(), _ProjectedArtifacts()
        await TestAResumeOfAResumeReceivesTheOriginalParentsFiles()._child_failed_in_plan_too(
            executions, artifacts
        )
        child = executions.streams[CHILD]
        admitted = child._admitted_resume
        child._admitted_resume = admitted.model_copy(
            update={
                "inherited_phases": [
                    InheritedPhase(phase_id=p.phase_id, artifact_ids=p.artifact_ids)
                    for p in admitted.inherited_phases
                ]
            }
        )

        grandchild = _ReadsItsInputs(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))

        assert await _start(executions, artifacts, CHILD, grandchild) == "completed"
        assert grandchild.inputs["plan"] == EXPECTED_INPUT_TREE


class TestARefusalNamesTheExecutionItAsked:
    async def test_the_owner_is_named_not_the_parent(self) -> None:
        """'Resolved to no files' sent operators to check artifacts that existed.

        The refusal now says WHICH execution was asked, so a wrong owner is
        visible on its face.
        """
        origin = ResumeOrigin(
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
