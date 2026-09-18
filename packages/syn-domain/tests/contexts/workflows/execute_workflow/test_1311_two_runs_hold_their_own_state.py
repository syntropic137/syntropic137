"""#1311: two concurrent runs of one workflow do not share a phase's state.

WHAT THE HAZARD IS. Every map on ``PhaseRuntime`` was keyed by phase id alone,
and one ``PhaseRuntime`` was built per PROCESSOR - which
``BackgroundWorkflowDispatcher`` shares across up to
``SYN_POLLING_MAX_CONCURRENT_DISPATCHES`` executions. A workflow names its own
phases, so every run of it names them identically: both runs call their phase
"implement". So ``_workspaces["implement"]``, ``_envs["implement"]``,
``_cmds["implement"]``, ``_session_ids["implement"]`` and
``_announced_models["implement"]`` each had two writers and one slot, and
``finalize`` popped the single shared entry for whichever run finished first.

WHAT THAT COSTS, in the order the run hits it: the second run to provision
overwrites the first run's workspace handle, so the first run's agent is
launched in the SECOND run's container, with the second run's command line and
credentials - and then collects its deliverable out of that container too. The
artifact one run stores is the other run's work, stamped with the other run's
model. `_said` cost exactly this once already and it decided an outcome: run A
recovered its deliverable from run B's report, success in place of its own
failure (#1256). This is the same defect with the workspace instead of the
message.

WHY THE INTERLEAVE IS HELD AND NOT RACED. Each defect needs one specific
order, and ``asyncio.gather`` alone produces it only by luck: these fakes do no
I/O, so a run started first can reach its own teardown before the other has
been scheduled at all. A test relying on that luck would pass for scheduling
reasons and stop catching this the day the event loop changed. So both runs are
stopped at two rendezvous, each on a real await the run already makes, and
released only once every run has arrived. Both are legal production
interleaves, held still.

``_HoldEveryRunAtSessionStart`` is the earlier one: a run has recorded the
inputs it was dispatched with and has not yet built a prompt out of them. That
is the window in which a second run's arrival overwrote the first run's inputs.

``_HoldEveryRunAtProvision`` is the later one: a run holds its workspace and
has not yet launched its agent. Nothing inside a single ``run()`` comes between
a phase's own ``attach_workspace`` and its own ``launch``, so this is the only
way to get both writes in before either read.

THE SENTINELS COULD NOT ARISE BY DEFAULT. Each run's command line is built from
its own execution id by the prompt builder below, its announced model is a
string naming its run, and its deliverable says which run wrote it. None of the
three has a default, none is written down twice, and no run can produce the
other's by accident - so an assertion that a run sees its own is an assertion
that nothing crossed over.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    AgentVerdict,
    StreamResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_session_repository import FakeSessionRepository

from .test_processor_smoke import FakeExecutionRepository

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.agent_sessions import AgentSessionAggregate
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        WorkflowExecutionResult,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import Runner

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-1311"

#: The phase id both runs use, which is the whole premise: a workflow names its
#: own phases, so every run of it names them identically.
PHASE_ID = "implement"

ONE = "exec-1311-one"
TWO = "exec-1311-two"

#: What each run's harness announces on its own stream. Two different models,
#: because a cross-model workflow is the case the announced model exists for
#: (#1284) and the case where reading the wrong one is unfalsifiable afterwards.
ANNOUNCED = {ONE: "claude-opus-5-20260115", TWO: "claude-haiku-4-5-20251001"}

#: What each run's agent writes into its OWN workspace. Named for its run,
#: because the artifact is the run's whole output and "which run produced this"
#: is not recoverable from it by any other means.
DELIVERABLE = {ONE: b"# deliverable written by run one", TWO: b"# deliverable written by run two"}

#: What each run was asked to do. Two different issues in two different repos,
#: because that is the shape of the real input - a run is dispatched at one
#: issue - and because a prompt built from the other run's is a valid prompt
#: pointed at the wrong work. Nothing downstream can tell.
INPUTS = {
    ONE: {"issue": "1311", "repo": "syntropic137/syntropic137"},
    TWO: {"issue": "9042", "repo": "syntropic137/event-sourcing-platform"},
}


@dataclass(frozen=True)
class _Launch:
    """One agent start, as the agent itself saw it.

    Recorded at the agent rather than read off the runtime on purpose: the
    runtime is the object under test, so asking it what it holds would only
    ever confirm its own bookkeeping. These four are what the container is
    actually started with, which is where the collision does its damage.
    """

    execution_id: str
    workspace_id: str | None
    claude_cmd: tuple[str, ...]
    session_id: str


class _Rendezvous:
    """Hold every run at one point until all of them have reached it.

    Not `asyncio.Barrier`: each run must be admitted exactly once however many
    times the await it rides on is taken, so arrival is recorded per run id.
    A run that arrives twice passes straight through rather than deadlocking
    the ones still to come.
    """

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._everyone_here = asyncio.Event()
        self._held: set[str] = set()

    async def hold(self, run_id: str) -> None:
        if run_id in self._held:
            return
        self._held.add(run_id)
        self._arrived += 1
        if self._arrived >= self._parties:
            self._everyone_here.set()
        await self._everyone_here.wait()


class _HoldEveryRunAtSessionStart:
    """A session repository that stops each run before it builds a prompt.

    `SessionLifecycleManager.start` persists the phase's session part way
    through `_handle_provision`, after `run()` has recorded the inputs it was
    dispatched with and before `_provision_workspace` reads them back out. So
    holding here puts every run's inputs in place before any run builds a
    prompt - which is exactly the order in which a slot shared by both runs
    hands one of them the other's issue.
    """

    def __init__(self, rendezvous: _Rendezvous) -> None:
        self._inner = FakeSessionRepository()
        self._rendezvous = rendezvous

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        await self._inner.save(aggregate)
        if aggregate.execution_id is not None:
            await self._rendezvous.hold(aggregate.execution_id)

    async def save_new(self, aggregate: AgentSessionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> AgentSessionAggregate | None:
        return await self._inner.get_by_id(aggregate_id)

    async def exists(self, aggregate_id: str) -> bool:
        return await self._inner.exists(aggregate_id)


class _HoldEveryRunAtProvision:
    """An execution repository that stops each run once it holds its workspace.

    Every run is released only when all of them have arrived, so all the
    ``attach_workspace`` calls land before any ``launch`` reads them - the one
    ordering that makes the shared key observable, and one a real event loop can
    produce at any time.

    It waits AFTER the save, on the run's own ``WorkspaceProvisionedForPhaseEvent``:
    that event is committed at the end of ``_handle_provision``, with the
    workspace already attached and the agent not yet dispatched.
    """

    def __init__(self, rendezvous: _Rendezvous) -> None:
        self._inner = FakeExecutionRepository()
        self._rendezvous = rendezvous

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        provisioned = any(
            isinstance(envelope.event, WorkspaceProvisionedForPhaseEvent)
            for envelope in aggregate.get_uncommitted_events()
        )
        await self._inner.save(aggregate)
        if provisioned:
            await self._rendezvous.hold(aggregate.id)

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self._inner.save_new(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return await self._inner.get_by_id(aggregate_id)


@dataclass
class _KeepEveryArtifact:
    """An artifact repository that keeps what each run stored."""

    saved: list[ArtifactAggregate] = field(default_factory=list)

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)

    async def get_by_id(self, artifact_id: str) -> None:
        return None

    def for_execution(self, execution_id: str) -> ArtifactAggregate:
        stored = [a for a in self.saved if a.execution_id == execution_id]
        assert len(stored) == 1, f"fixture: {execution_id} stored {len(stored)} artifacts"
        return stored[0]


class _AnAgentThatSignsItsWork:
    """A harness that writes and announces something only ITS run could have.

    It writes into whichever workspace it is handed - which is the point. A
    double that wrote into the workspace it "should" have had would paper over
    exactly the hop being tested.
    """

    def __init__(self) -> None:
        self.launches: list[_Launch] = []

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
        runner: Runner | None = None,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        execution_id = todo.execution_id
        self.launches.append(
            _Launch(
                execution_id=execution_id,
                workspace_id=getattr(workspace, "workspace_id", None),
                claude_cmd=tuple(claude_cmd),
                session_id=session_id,
            )
        )
        await workspace.inject_files(
            [("artifacts/output/deliverable.md", DELIVERABLE[execution_id])]
        )
        if on_launch is not None:
            await on_launch()
        return AgentExecutionResult(
            stream_result=StreamResult(
                line_count=0,
                interrupt_requested=False,
                interrupt_reason=None,
                announced_model=ANNOUNCED[execution_id],
                verdict=AgentVerdict.from_agent_text(None),
            ),
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            command=AgentExecutionCompletedCommand(
                execution_id=execution_id,
                phase_id=todo.phase_id or "",
                session_id=session_id,
                exit_code=0,
            ),
        )

    def launch_for(self, execution_id: str) -> _Launch:
        found = [launch for launch in self.launches if launch.execution_id == execution_id]
        assert len(found) == 1, f"fixture: {execution_id} launched {len(found)} agents"
        return found[0]


class _APromptNamingItsRun:
    """Builds each run's prompt, and keeps the inputs it was given to build it.

    A recorder rather than a plain function because ``inputs`` is the second
    thing this file is about: it was held as ``self._inputs`` on the processor,
    assigned at the top of ``run()`` and read several awaits later during
    provisioning, so a concurrent run starting in between replaced it. What
    reaches the agent then is a well-formed prompt naming the other run's issue
    and repo - and the only place that is observable is right here, where the
    prompt is built.
    """

    def __init__(self) -> None:
        self.inputs_seen: dict[str, dict[str, str]] = {}

    async def __call__(
        self,
        phase: ExecutablePhase,
        execution_id: str,
        workflow_id: str,
        repo_url: str | None,
        phase_outputs: dict,
        inputs: dict,
    ) -> str:
        """The prompt carries the run's id, so the command line does too.

        That is what makes ``claude_cmd`` a sentinel rather than a constant: in
        production the command line is built per run from that run's prompt,
        and launching a container with another run's is the concrete form of
        the bug.
        """
        self.inputs_seen[execution_id] = dict(inputs)
        return f"prompt for {execution_id}"


def _echo_the_prompt(phase: ExecutablePhase, prompt: str) -> list[str]:
    return ["echo", prompt]


def _the_phase() -> list[ExecutablePhase]:
    """One phase, declaring the markdown output its agent writes."""
    return [
        ExecutablePhase(
            phase_id=PHASE_ID,
            name="implement",
            order=1,
            description="A phase two runs of this workflow both have",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=("markdown",),
            timeout_seconds=1200,
        )
    ]


@dataclass(frozen=True)
class _BothRuns:
    """Two whole runs of one workflow that overlapped, and what they produced."""

    results: dict[str, WorkflowExecutionResult]
    agent: _AnAgentThatSignsItsWork
    artifacts: _KeepEveryArtifact
    prompts: _APromptNamingItsRun


async def _two_concurrent_runs() -> _BothRuns:
    """Drive two full ``run()`` passes of the same workflow through one processor.

    One processor, because that is production: ``get_execution_processor()`` is
    called once and ``BackgroundWorkflowDispatcher`` hands the single instance
    to every dispatch it admits.
    """
    agent = _AnAgentThatSignsItsWork()
    artifacts = _KeepEveryArtifact()
    prompts = _APromptNamingItsRun()
    processor = WorkflowExecutionProcessor(
        execution_repository=_HoldEveryRunAtProvision(_Rendezvous(parties=2)),  # type: ignore[arg-type]
        session_repository=_HoldEveryRunAtSessionStart(_Rendezvous(parties=2)),  # type: ignore[arg-type]
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=artifacts,  # type: ignore[arg-type]
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=prompts,
        command_builder=_echo_the_prompt,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,  # type: ignore[arg-type]
    )

    async def _run(execution_id: str) -> WorkflowExecutionResult:
        return await processor.run(
            workflow_id=WORKFLOW_ID,
            workflow_name="sdlc-implement",
            phases=_the_phase(),
            inputs=dict(INPUTS[execution_id]),
            execution_id=execution_id,
        )

    one, two = await asyncio.wait_for(
        asyncio.gather(_run(ONE), _run(TWO)),
        timeout=30,
    )
    return _BothRuns(
        results={ONE: one, TWO: two}, agent=agent, artifacts=artifacts, prompts=prompts
    )


class TestEachRunLaunchesItsOwnAgent:
    """The first crossing, and the one every later one follows from."""

    async def test_neither_run_launches_its_agent_in_the_other_s_container(self) -> None:
        """Two runs, two workspaces. A shared slot hands both agents the same
        one, which is two agents editing the same checkout and pushing over
        each other - and the second run's secrets in the first run's shell."""
        both = await _two_concurrent_runs()

        one = both.agent.launch_for(ONE)
        two = both.agent.launch_for(TWO)

        assert one.workspace_id is not None, "fixture: the memory backend names its workspaces"
        assert one.workspace_id != two.workspace_id

    async def test_each_agent_is_started_with_its_own_command_line(self) -> None:
        """The command line is built from the run's own prompt. Launching a
        container with the other run's is the phase doing the wrong work, and
        reporting it under this run's id."""
        both = await _two_concurrent_runs()

        assert both.agent.launch_for(ONE).claude_cmd == ("echo", f"prompt for {ONE}")
        assert both.agent.launch_for(TWO).claude_cmd == ("echo", f"prompt for {TWO}")

    async def test_each_agent_runs_under_its_own_session(self) -> None:
        """The session id is what every observability row is keyed by, so a
        shared one merges two runs' traces into one session's."""
        both = await _two_concurrent_runs()

        assert both.agent.launch_for(ONE).session_id != both.agent.launch_for(TWO).session_id


class TestEachRunIsAskedToDoItsOwnWork:
    """The inputs, which were `self._inputs` on the shared processor.

    Not a map keyed by phase id but the same defect one step simpler: one slot
    on an object two runs share, written at the top of `run()` and read several
    awaits later. It is the worst of the group to land in production because
    the result is indistinguishable from correct - a well-formed prompt, a
    clean run, a finished deliverable, for the wrong issue.
    """

    async def test_each_run_builds_its_prompt_from_its_own_inputs(self) -> None:
        both = await _two_concurrent_runs()

        assert both.prompts.inputs_seen[ONE] == INPUTS[ONE]
        assert both.prompts.inputs_seen[TWO] == INPUTS[TWO]

    async def test_neither_run_is_pointed_at_the_other_s_issue(self) -> None:
        """Stated as the harm rather than as equality: the issue number is what
        the agent opens, and the repo is what it pushes to."""
        both = await _two_concurrent_runs()

        assert both.prompts.inputs_seen[ONE]["issue"] != INPUTS[TWO]["issue"]
        assert both.prompts.inputs_seen[TWO]["repo"] != INPUTS[ONE]["repo"]


class TestEachRunStoresItsOwnWork:
    """What survives the run, and the only place anyone looks afterwards."""

    async def test_each_run_stores_the_deliverable_its_own_agent_wrote(self) -> None:
        """The artifact is collected out of the workspace the runtime is still
        holding for this phase. Holding one for two runs collects one run's
        work twice and loses the other's entirely."""
        both = await _two_concurrent_runs()

        assert DELIVERABLE[ONE].decode() in both.artifacts.for_execution(ONE).content
        assert DELIVERABLE[TWO].decode() in both.artifacts.for_execution(TWO).content

    async def test_neither_run_stores_the_other_s_deliverable(self) -> None:
        """Stated in the negative as well, because a run that collected BOTH
        files would satisfy the assertion above while still having read the
        other run's container."""
        both = await _two_concurrent_runs()

        assert DELIVERABLE[TWO].decode() not in both.artifacts.for_execution(ONE).content
        assert DELIVERABLE[ONE].decode() not in both.artifacts.for_execution(TWO).content

    async def test_each_artifact_names_the_model_that_actually_ran_it(self) -> None:
        """The announced model is evidence of WHICH model did the work (#1284).
        Stamped from a shared slot it is not weaker evidence, it is false
        evidence - and unfalsifiable, because the stream is gone."""
        both = await _two_concurrent_runs()

        assert both.artifacts.for_execution(ONE).agent.model == ANNOUNCED[ONE]
        assert both.artifacts.for_execution(TWO).agent.model == ANNOUNCED[TWO]


class TestNeitherRunTearsDownTheOther:
    """Finalisation pops what the phase was holding. Under one shared slot the
    run that finishes first pops the other run's entry with it, leaving a live
    container with no handle to close and a run holding nothing."""

    async def test_both_runs_complete(self) -> None:
        both = await _two_concurrent_runs()

        assert both.results[ONE].status == "completed"
        assert both.results[TWO].status == "completed"

    async def test_each_run_reports_its_own_phase_as_completed(self) -> None:
        both = await _two_concurrent_runs()

        for execution_id in (ONE, TWO):
            phases = both.results[execution_id].phase_results
            assert [p.phase_id for p in phases] == [PHASE_ID]
            assert phases[0].status.value == "completed"
