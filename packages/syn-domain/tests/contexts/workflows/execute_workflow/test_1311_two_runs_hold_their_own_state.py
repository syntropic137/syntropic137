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

AND THEN THE TERMINAL PATHS, which is the half of this that the classes at the
bottom of the file are about. Everything above drives two runs that both
SUCCEED, and a run that succeeds gives up its state one phase at a time through
`finalize`. The two ways a run ends early do not: `_cancel_execution` and
`_fail_execution` each close every session the runtime holds and tear down
every workspace it holds, in one loop, over everything, with no phase id and no
execution id to narrow it by.

So the terminal paths are where this class of defect outlives a partial fix.
Keying every map by `(execution_id, phase_id)` would have made provisioning
safe and left `abandon_all` iterating both runs' entries exactly as before -
one run's cleanup closing a healthy run's session and destroying the container
its agent was still working in. That they are correct now is a consequence of
there being one runtime per run rather than of any key, and a consequence is
the kind of thing that quietly stops holding.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.agent_sessions import SessionStatus
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

    def content_for(self, execution_id: str) -> str:
        """Everything this run stored, as one string; empty when it stored none.

        Deliberately tolerant of the count where ``for_execution`` is not,
        because a run that stored NOTHING is one of the outcomes under test and
        it should read as a missing deliverable rather than as a broken fixture.
        """
        return "".join(a.content for a in self.saved if a.execution_id == execution_id)


class _RunIsNotProgressingError(BaseException):
    """A run that has stopped making progress, raised so nothing can catch it.

    A ``BaseException`` deliberately. ``run()`` catches ``Exception`` and turns
    it into a failed execution, which would file this under "the run failed"
    alongside every ordinary failure and lose the one thing it is reporting.
    Nothing in production may absorb it, because it is not a fact about the
    workflow - it is the fixture saying the test would otherwise hang.
    """


@dataclass
class _WhatTheListKeepsHandingOut:
    """The to-do item one run was last given, and how many times running."""

    item: str | None = None
    times: int = 0


class _ATodoListThatCannotSpin(ExecutionTodoProjection):
    """The real to-do projection, which stops when a run stops progressing.

    WHY A TEST OF THIS DEFECT NEEDS ONE. A run whose workspace was torn down
    out from under it does not crash. ``_handle_collect_artifacts`` finds no
    workspace, logs "Skipping stale COLLECT_ARTIFACTS", and returns WITHOUT
    advancing the item - so ``_drain_todo_list`` asks for it again, gets the
    same one, and goes round. There is nothing in that loop that yields, so the
    event loop never gets control back: the ``asyncio.wait_for`` below cannot
    fire, and neither can any other timeout. The run does not fail, it spins,
    and it takes the CI job with it.

    That is exactly what the surviving run does when the other run's teardown
    reaches its state, which is the thing these tests exist to catch. A test
    that expresses its own subject as a hang is not a test that failed - it is
    a test that cannot report. So the loop is bounded here: the same to-do item
    handed out this many times running means the run has stopped progressing,
    and that is said out loud.

    The non-advancing skip branch is a defect of its own and not this file's to
    fix; it is reachable in-process only once a runtime has lost a workspace it
    should still be holding, which is the state #1311 produced.
    """

    #: Generous by two orders of magnitude: a healthy run is handed each of its
    #: four to-do items once and never sees the same one twice running.
    _PATIENCE = 50

    def __init__(self, store: InMemoryProjectionStore) -> None:
        super().__init__(store=store)
        self._handed_out: dict[str, _WhatTheListKeepsHandingOut] = {}

    async def get_pending(self, execution_id: str) -> list[TodoItem]:
        pending = await super().get_pending(execution_id)
        head = f"{pending[0].action}:{pending[0].phase_id}" if pending else None
        seen = self._handed_out.setdefault(execution_id, _WhatTheListKeepsHandingOut())
        seen.times = seen.times + 1 if head == seen.item else 1
        seen.item = head
        if seen.times > self._PATIENCE:
            msg = (
                f"{execution_id} was handed the same to-do item ({head}) "
                f"{seen.times} times running without progressing. Its run is "
                "livelocked - which is what a run looks like once another run's "
                "teardown has taken the workspace it was still working in."
            )
            raise _RunIsNotProgressingError(msg)
        return pending


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
        todo_projection=_ATodoListThatCannotSpin(store=InMemoryProjectionStore()),
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


# ══════════════════════════════════════════════════════════════════════════
# The terminal paths: what one run's ending does to the run beside it.
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _HowARunEnds:
    """One of the two ways a run can leave early, as its harness reports it.

    There are exactly two, they leave through two different methods, and both
    of those methods tear down by clearing EVERYTHING the runtime can reach -
    they are handed no phase id and no execution id to narrow it with. That is
    why the terminal paths are the place this defect outlives a fix to the
    provisioning path: keying a map more finely does nothing for a loop that
    iterates the whole map.

    ``interrupt`` is the cancel signal. ``_handle_run_agent`` turns it into a
    ``CancelExecutionCommand``, the aggregate goes to CANCELLED, the to-do list
    empties and ``run()`` leaves through ``_cancel_execution`` →
    ``report_cancelled`` → ``abandon_all``.

    A non-zero ``exit_code`` raises out of ``_handle_run_agent`` instead, and
    ``run()`` leaves through ``_fail_execution`` → ``report_failed`` →
    ``abandon_all``.
    """

    label: str
    interrupt: bool
    exit_code: int
    execution_status: str
    session_status: SessionStatus


#: Cancelled by an operator, which is what `syn control cancel` sends.
BY_CANCEL = _HowARunEnds(
    label="cancel",
    interrupt=True,
    exit_code=0,
    execution_status="cancelled",
    session_status=SessionStatus.CANCELLED,
)

#: Killed by its own agent's exit status. 42 rather than 1 so that a status
#: read off the wrong run would have to have invented this number.
BY_FAILURE = _HowARunEnds(
    label="fail",
    interrupt=False,
    exit_code=42,
    execution_status="failed",
    session_status=SessionStatus.FAILED,
)

#: Why run one was cancelled, in words no other run has any way to produce.
CANCEL_REASON = "cancelled by the operator watching run one"


class _EverySessionKept(FakeSessionRepository):
    """The session repository, with a way to ask what became of a run's session.

    The session is where a teardown is legible from outside: closing it is the
    FIRST thing both terminal paths do, before any workspace is touched, and it
    is recorded on the session's own event stream. So "did the other run's
    cancel reach this run" is answerable without asking the runtime anything
    about its own bookkeeping.
    """

    async def for_execution(self, execution_id: str) -> AgentSessionAggregate:
        rehydrated = [await self.get_by_id(session_id) for session_id in self.streams]
        found = [s for s in rehydrated if s is not None and s.execution_id == execution_id]
        assert len(found) == 1, f"fixture: {execution_id} opened {len(found)} sessions"
        return found[0]


class _OneRunGoesDownWhileTheOtherWorks:
    """Two agents in one double: the run that ends, and the run that does not.

    THE INTERLEAVE, and why each half of it is load-bearing.

    Every run is held until all of them have reached their agent. That is the
    state the terminal paths have to be safe in and the only one in which the
    question means anything: both runs provisioned, both holding a workspace,
    both with an open session. A cancel arriving when the other run happens to
    be between phases cannot observe this defect at all.

    The surviving run is then held FURTHER, until the doomed run's ``run()``
    has returned - so its teardown is complete, not merely started, before the
    survivor does anything else. What the survivor does next is write its
    deliverable. That file therefore cannot have been written before the
    teardown, and the workspace it is written into must still be open after it:
    a run whose container was closed by the other run's cleanup has nothing to
    write to and nothing left to collect.
    """

    def __init__(
        self,
        *,
        doomed: str,
        ending: _HowARunEnds,
        everyone_launched: _Rendezvous,
        doomed_run_returned: asyncio.Event,
    ) -> None:
        self._doomed = doomed
        self._ending = ending
        self._everyone_launched = everyone_launched
        self._doomed_run_returned = doomed_run_returned
        #: The session each run's agent was actually launched under, recorded
        #: at the agent for the reason `_Launch` above is: it is what the
        #: container ran as, not what the runtime believes it handed out.
        self.sessions: dict[str, str] = {}

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
        self.sessions[execution_id] = session_id
        if on_launch is not None:
            await on_launch()
        await self._everyone_launched.hold(execution_id)

        if execution_id == self._doomed:
            return self._the_end_of_run_one(todo, session_id)

        await self._doomed_run_returned.wait()
        await workspace.inject_files(
            [("artifacts/output/deliverable.md", DELIVERABLE[execution_id])]
        )
        return self._a_finished_phase(todo, session_id, exit_code=0, interrupt=False)

    def _the_end_of_run_one(self, todo: TodoItem, session_id: str) -> AgentExecutionResult:
        return self._a_finished_phase(
            todo,
            session_id,
            exit_code=self._ending.exit_code,
            interrupt=self._ending.interrupt,
        )

    def _a_finished_phase(
        self, todo: TodoItem, session_id: str, *, exit_code: int, interrupt: bool
    ) -> AgentExecutionResult:
        return AgentExecutionResult(
            stream_result=StreamResult(
                line_count=0,
                interrupt_requested=interrupt,
                interrupt_reason=CANCEL_REASON if interrupt else None,
                announced_model=ANNOUNCED[todo.execution_id],
                verdict=AgentVerdict.from_agent_text(None),
            ),
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            command=AgentExecutionCompletedCommand(
                execution_id=todo.execution_id,
                phase_id=todo.phase_id or "",
                session_id=session_id,
                exit_code=exit_code,
            ),
        )


@dataclass(frozen=True)
class _OneRunEndedBesideOneThatDidNot:
    """Two overlapping runs, one of which left through a terminal path."""

    ending: _HowARunEnds
    results: dict[str, WorkflowExecutionResult]
    sessions: _EverySessionKept
    artifacts: _KeepEveryArtifact
    agent: _OneRunGoesDownWhileTheOtherWorks


async def _run_one_ends_while_run_two_works(
    ending: _HowARunEnds,
) -> _OneRunEndedBesideOneThatDidNot:
    """Drive two concurrent runs of one workflow, and end ONE of them.

    One processor, as production has: ``BackgroundWorkflowDispatcher`` hands
    the single instance to every dispatch it admits, so run one's cleanup and
    run two's live state meet on the same object or they do not meet at all.
    """
    doomed_run_returned = asyncio.Event()
    agent = _OneRunGoesDownWhileTheOtherWorks(
        doomed=ONE,
        ending=ending,
        everyone_launched=_Rendezvous(parties=2),
        doomed_run_returned=doomed_run_returned,
    )
    artifacts = _KeepEveryArtifact()
    sessions = _EverySessionKept()
    processor = WorkflowExecutionProcessor(
        execution_repository=FakeExecutionRepository(),  # type: ignore[arg-type]
        session_repository=sessions,  # type: ignore[arg-type]
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=artifacts,  # type: ignore[arg-type]
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_APromptNamingItsRun(),
        command_builder=_echo_the_prompt,
        todo_projection=_ATodoListThatCannotSpin(store=InMemoryProjectionStore()),
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

    async def _run_and_announce_the_end(execution_id: str) -> WorkflowExecutionResult:
        """Run one, and say when it is all the way out.

        In a ``finally`` so that a run which ends by raising still releases the
        other one: a doomed run that deadlocked the survivor would fail this
        file on a timeout, which says nothing about isolation.
        """
        try:
            return await _run(execution_id)
        finally:
            doomed_run_returned.set()

    one, two = await asyncio.wait_for(
        asyncio.gather(_run_and_announce_the_end(ONE), _run(TWO)),
        timeout=30,
    )
    return _OneRunEndedBesideOneThatDidNot(
        ending=ending,
        results={ONE: one, TWO: two},
        sessions=sessions,
        artifacts=artifacts,
        agent=agent,
    )


_BOTH_TERMINAL_PATHS = pytest.mark.parametrize(
    "ending", [BY_CANCEL, BY_FAILURE], ids=lambda e: e.label
)


class TestTheRunThatEndsActuallyEnds:
    """The positive control, without which everything below is vacuous.

    Every assertion in the next class is that something did NOT happen to run
    two. Those all pass just as well against a run one that never reached a
    terminal path at all - so what run one did has to be pinned first, in the
    same scenario and from the same fixture.
    """

    @_BOTH_TERMINAL_PATHS
    async def test_run_one_leaves_through_the_terminal_path_it_was_given(
        self, ending: _HowARunEnds
    ) -> None:
        both = await _run_one_ends_while_run_two_works(ending)

        assert both.results[ONE].status == ending.execution_status

    @_BOTH_TERMINAL_PATHS
    async def test_run_one_closes_its_own_session_on_the_way_out(
        self, ending: _HowARunEnds
    ) -> None:
        """`report_cancelled`/`report_failed` ran and reached a live session
        manager. That is the loop the next class is about; a scenario where it
        found nothing to close would prove nothing by leaving run two alone."""
        both = await _run_one_ends_while_run_two_works(ending)

        session = await both.sessions.for_execution(ONE)
        assert session.status == ending.session_status


class TestTheRunBesideItIsUntouched:
    """One run ending must not end the run next to it.

    Both terminal paths close every session the runtime is holding and tear
    down every workspace it is holding - each in one loop, over everything,
    with nothing to narrow it by. While those loops ran over a runtime shared
    by both dispatches, run one's cancel closed run two's session and destroyed
    run two's container out from under a live agent. Run two then finished into
    an empty runtime: nothing to collect from, nothing to complete, and a
    session already recorded as cancelled by a cancel nobody had issued
    against it.
    """

    @_BOTH_TERMINAL_PATHS
    async def test_run_two_s_session_is_not_closed_by_run_one_s_teardown(
        self, ending: _HowARunEnds
    ) -> None:
        """The session is the record of what happened to a run, and it is
        closed once. Closed as cancelled by the run next door, a healthy run's
        own completion is refused - and the operator reads the cancellation of
        a run nobody cancelled."""
        both = await _run_one_ends_while_run_two_works(ending)

        session = await both.sessions.for_execution(TWO)
        assert session.status == SessionStatus.COMPLETED

    @_BOTH_TERMINAL_PATHS
    async def test_run_two_keeps_the_workspace_it_is_still_working_in(
        self, ending: _HowARunEnds
    ) -> None:
        """Run two writes its deliverable only AFTER run one has finished going
        down, so this file exists only if the container survived the other
        run's cleanup and the runtime still had the handle to collect it."""
        both = await _run_one_ends_while_run_two_works(ending)

        assert DELIVERABLE[TWO].decode() in both.artifacts.content_for(TWO)

    @_BOTH_TERMINAL_PATHS
    async def test_run_two_reaches_its_own_completion(self, ending: _HowARunEnds) -> None:
        """Stated on the result as well as on the session, because they fail
        apart: a run whose state was cleared mid-flight can still return
        `completed` having silently collected and finalised nothing."""
        both = await _run_one_ends_while_run_two_works(ending)

        assert both.results[TWO].status == "completed"
        assert [p.phase_id for p in both.results[TWO].phase_results] == [PHASE_ID]

    async def test_a_failing_run_reports_its_own_session_and_not_the_other_s(self) -> None:
        """The failure path reads the session id back out of the runtime to
        name the phase that died (#1036). Read from a slot both runs wrote,
        that names the HEALTHY run's session - so the failure is filed against
        a session that did not fail, and the one that did looks clean.

        Only the failure path builds a phase result this way; a cancel reports
        the phases that had already completed, and run one has none.
        """
        both = await _run_one_ends_while_run_two_works(BY_FAILURE)

        failed = both.results[ONE].phase_results
        assert [p.phase_id for p in failed] == [PHASE_ID]
        assert failed[0].session_id == both.agent.sessions[ONE]
        assert failed[0].session_id != both.agent.sessions[TWO]
