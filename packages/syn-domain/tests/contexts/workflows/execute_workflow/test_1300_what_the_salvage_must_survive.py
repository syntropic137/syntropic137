"""#1300 review: the three ways the salvage was still failing on its own terms.

The suite next door proves the salvage WORKS. It was all written against one
process, one aggregate object and one happy shape of message, and every one of
those hid a defect:

1. THE INPUT DID NOT SURVIVE A RESTART. What the agent said was popped out of a
   dict in the processor's memory. A restart between the agent finishing and
   its artifacts being collected - which is most of what "something went wrong"
   MEANS - lost it, so the rescue worked only for runs that had not really
   needed rescuing. `TestItSurvivesARestart` is the test that could not pass
   until the message rode the event stream.
2. ANYTHING NON-BLANK WAS A CONCLUSION. A refusal was stored as the phase's
   deliverable, which is worse than the failure it replaced: the run continues
   and the next phase is handed a note saying the work was not done.
   `TestARefusalIsNotAConclusion`.
3. A SALVAGED PHASE READ AS A CLEAN ONE. `PhaseCompleted` was byte-for-byte
   identical either way, so nothing downstream could count salvages or find the
   runs standing on one. `TestTheRecordSaysItWasSalvaged`.

WHY THESE READ THE EVENT STORE AND THE SMOKE SUITE'S REPOSITORY DOES NOT.
`FakeExecutionRepository` hands back the same aggregate object it was given; it
is a cache, not an event store. A restart test built on it would be asserting
against state the process happened to still be holding, which is precisely the
thing being ruled out. `_EventStore` below keeps envelopes and rehydrates from
them, so "the aggregate knows" here can only mean "the stream said so".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.artifact_recovery import (
    RECOVERED_TITLE_MARKER,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    PhaseProducedNoDeclaredOutputError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _Clone,
    _clone_repository,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    _DispatchContext,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)

from .test_1300_a_missing_report_does_not_discard_the_run import (
    SAID,
    _KeepingArtifacts,
    _RecordingAgent,
    _run_writing_nothing,
)
from .test_processor_smoke import _make_processor, _two_phase_workflow

if TYPE_CHECKING:
    from pathlib import Path

    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture
def clone(tmp_path: Path) -> _Clone:
    """A phase's starting point: a clone on a feature branch, pushed and level."""
    return _clone_repository(tmp_path)


EXECUTION_ID = "exec-1300-restart"
WORKFLOW_ID = "wf-1300-restart"
FIRST_PHASE = "phase-001"


class _EventStore:
    """An execution repository that keeps events and rebuilds only from them.

    This is the whole point of the restart tests: `get_by_id` never returns an
    object anyone has held before, so any state it has came out of the stream.
    """

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if not self.envelopes:
            return None
        revived = WorkflowExecutionAggregate()
        revived.rehydrate(self.envelopes)
        return revived

    def events_named(self, event_type: str) -> list[Any]:
        """Every stored event of one type, as a reader of the record sees them."""
        return [
            envelope.event
            for envelope in self.envelopes
            if getattr(envelope.event, "event_type", type(envelope.event).__name__) == event_type
        ]


class _Process:
    """One processor lifetime - and therefore everything a restart destroys.

    The durable things (the event store, the to-do list's projection store, the
    artifact store) are passed in and shared across processes, because that is
    what makes them durable. The processor, its `PhaseRuntime` and the loop's
    own bookkeeping are built here and thrown away with the process.
    """

    def __init__(
        self,
        events: _EventStore,
        todo_store: InMemoryProjectionStore,
        artifacts: _KeepingArtifacts,
        agent: _RecordingAgent,
    ) -> None:
        processor = _make_processor(agent)
        processor._artifact_repo = artifacts  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
        # The to-do list is a projection and survives a restart by being read
        # back out of its store (`ExecutionTodoProjection` is rebuilt, its
        # store is not). The journal is rebuilt around both.
        projection = ExecutionTodoProjection(store=todo_store)
        processor._todo_projection = projection  # pyright: ignore[reportPrivateUsage]
        processor._journal = ExecutionJournal(events, projection)  # pyright: ignore[reportPrivateUsage]
        processor._inputs = {}  # pyright: ignore[reportPrivateUsage]
        self.processor: WorkflowExecutionProcessor = processor
        self.artifact_ids: list[str] = []
        self.phase_results: list[Any] = []
        self.completed_phase_ids: list[str] = []
        self.phase_outputs = PhaseOutputCache()

    async def work(
        self,
        aggregate: WorkflowExecutionAggregate,
        phases: list[ExecutablePhase],
        *,
        stopping_before: TodoAction | None = None,
    ) -> None:
        """Drain the to-do list the way `run()` does, optionally stopping short.

        `stopping_before` is where the process dies. It leaves the to-do item
        pending and its event stream saved, which is exactly the state a
        restarted processor finds.
        """
        phase_map = {p.phase_id: p for p in phases}
        while True:
            todos: list[TodoItem] = await self.processor._todo_projection.get_pending(  # pyright: ignore[reportPrivateUsage]
                EXECUTION_ID
            )
            if not todos or todos[0].action == stopping_before:
                return
            await self.processor._dispatch(  # pyright: ignore[reportPrivateUsage]
                todo=todos[0],
                aggregate=aggregate,
                phase_map=phase_map,
                phase_results=self.phase_results,
                all_artifact_ids=self.artifact_ids,
                completed_phase_ids=self.completed_phase_ids,
                phase_outputs=self.phase_outputs,
                repos=None,
                dispatch_ctx=_DispatchContext(),
            )

    async def reprovision(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
    ) -> None:
        """Replace the infrastructure the crash took, as a restart has to.

        Per the architecture notes: "On crash, infrastructure is assumed lost.
        The processor re-provisions from the last completed domain event." The
        workspace this hands back is EMPTY - the phase wrote no output file and
        the container that ran it is gone - so whatever the collection step
        recovers next cannot have come from disk.

        No command is issued to the aggregate for it: the workspace was already
        provisioned once as far as the record is concerned, and re-announcing
        it would rewind the to-do list to RUN_AGENT and re-run the agent.
        """
        result = await self.processor._workspaces.provision(  # pyright: ignore[reportPrivateUsage]
            todo=todo,
            phase=phase,
            aggregate=aggregate,
            session_id=todo.session_id or "",
            repo_urls=[],
            completed_phase_ids=self.completed_phase_ids,
            phase_outputs=self.phase_outputs,
        )
        self.processor._runtime.attach_workspace(  # pyright: ignore[reportPrivateUsage]
            phase.phase_id,
            workspace=result.workspace,
            workspace_cm=result.workspace_cm,
            agent_env=result.agent_env,
            claude_cmd=result.claude_cmd,
            delivers_repo_changes=True,
        )


def _started(phases: list[ExecutablePhase]) -> WorkflowExecutionAggregate:
    """A real aggregate at the start of a real run."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id=WORKFLOW_ID,
            workflow_name="Fix Issue",
            total_phases=len(phases),
            inputs={},
            phase_definitions=[
                PhaseDefinition(phase_id=p.phase_id, name=p.name, order=p.order, timeout_seconds=30)
                for p in phases
            ],
        )
    )
    return aggregate


class _Crashed:
    """What two processes and one event store left behind."""

    def __init__(
        self,
        events: _EventStore,
        artifacts: _KeepingArtifacts,
        agent: _RecordingAgent,
        restarted: _Process,
    ) -> None:
        self.events = events
        self.artifacts = artifacts
        self.agent = agent
        self.restarted = restarted

    @property
    def stored(self) -> list[tuple[str, str]]:
        return [(a.title or "", a.content or "") for a in self.artifacts.saved]


async def _crash_between_the_agent_and_collection(*, says: str | None) -> _Crashed:
    """Run a phase, kill the process the instant the agent's result is saved.

    The seam is chosen deliberately: `AgentExecutionCompleted` has been
    persisted and COLLECT_ARTIFACTS is pending, so the run is at the one point
    where the salvage's only input existed nowhere but in memory.
    """
    phases = _two_phase_workflow(first_declares=("markdown",))
    events = _EventStore()
    todo_store = InMemoryProjectionStore()
    artifacts = _KeepingArtifacts()
    agent = _RecordingAgent(says=says)

    doomed = _Process(events, todo_store, artifacts, agent)
    aggregate = _started(phases)
    await doomed.processor._journal.open(aggregate)  # pyright: ignore[reportPrivateUsage]
    await doomed.work(aggregate, phases, stopping_before=TodoAction.COLLECT_ARTIFACTS)

    # ── the restart ──────────────────────────────────────────────────────
    # Nothing of `doomed` is used past this line. The aggregate below is not
    # the one it was mutating: it is built from the stored stream and nothing
    # else, which is all a new process has.
    del doomed, aggregate
    restarted = _Process(events, todo_store, artifacts, agent)
    revived = await events.get_by_id(EXECUTION_ID)
    assert revived is not None, "the run was never persisted; the test proves nothing"

    pending = await restarted.processor._todo_projection.get_pending(EXECUTION_ID)  # pyright: ignore[reportPrivateUsage]
    assert pending and pending[0].action == TodoAction.COLLECT_ARTIFACTS, (
        f"expected the restarted process to find collection pending, got {pending}"
    )
    await restarted.reprovision(pending[0], phases[0], revived)
    await restarted.work(revived, phases)
    return _Crashed(events, artifacts, agent, restarted)


class TestItSurvivesARestart:
    """DEFECT 1. The salvage's input has to be in the record, or it is not there.

    Held in the processor, it was destroyed by the very failures the feature
    exists to absorb. These run a real restart: a second processor, a second
    `PhaseRuntime`, and an aggregate rebuilt from the persisted events alone.
    """

    async def test_the_conclusion_is_still_recovered_after_the_process_dies(self) -> None:
        crashed = await _crash_between_the_agent_and_collection(says=SAID)

        assert crashed.stored, (
            "the restarted process stored nothing. What the agent said was "
            "lost with the process that heard it - which is #1300's defect 1: "
            "the salvage only ever worked when nothing had gone wrong."
        )
        ((title, content),) = crashed.stored
        assert SAID in content, (
            f"the recovered deliverable must carry the phase's conclusion, got {content!r}"
        )
        assert RECOVERED_TITLE_MARKER in title, (
            f"and must still declare itself a salvage after a restart, got {title!r}"
        )

    async def test_the_restarted_run_carries_on_to_the_next_phase(self) -> None:
        """The cost #1300 measures is the discarded run, not the missing file."""
        crashed = await _crash_between_the_agent_and_collection(says=SAID)

        assert crashed.agent.call_count == 2, (
            f"the downstream phase never ran ({crashed.agent.call_count} agent "
            "calls): a restart mid-phase still threw the finished work away"
        )

    async def test_a_restart_invents_nothing_for_a_phase_that_said_nothing(self) -> None:
        """The #1167 guard has to hold on the restart path too, or it is a hole.

        A restart must not become a second way to complete a phase that
        reached no conclusion anywhere.
        """
        with pytest.raises(PhaseProducedNoDeclaredOutputError):
            await _crash_between_the_agent_and_collection(says=None)


class TestARefusalIsNotAConclusion:
    """DEFECT 2. Salvage is for rescuing real work, not for laundering none.

    THE BAR, and why it is not a length. #1195's conclusion - the run that
    started all this - is ten words. So is "I cannot do this because the
    repository is not checked out." A floor that admits the first admits the
    second, and a floor high enough to exclude the second throws away the case
    the feature was built for.

    So the bar is on WHAT THE MESSAGE DOES, not on its size: a usable
    conclusion has to REPORT something. `is_usable_conclusion` drops the
    segments that report nothing - pure sign-off ("Done.", "Task complete") and
    bare stance with no reason ("I cannot do this.") - and requires eight
    reporting words of what is left. A refusal that explains itself is kept,
    because that IS information a downstream phase can act on; a refusal that
    does not is the same as silence and is treated as silence.

    These drive the whole processor rather than calling the predicate, because
    what matters is not that a function returned False - it is that the phase
    FAILED, loudly, exactly as it did before the salvage existed.
    """

    @pytest.mark.parametrize(
        "says",
        [
            pytest.param("Done.", id="a bare sign-off"),
            pytest.param("Task complete. All done!", id="ceremony and nothing else"),
            pytest.param("I cannot complete this task. I will not proceed.", id="a bare refusal"),
            pytest.param(
                "I'm sorry, but I'm unable to help with that request.", id="a polite refusal"
            ),
        ],
    )
    async def test_it_fails_the_phase_as_it_did_before(self, clone: _Clone, says: str) -> None:
        run = await _run_writing_nothing(clone, says=says)

        assert run.result.status == "failed", (  # type: ignore[attr-defined]
            f"{says!r} was accepted as this phase's deliverable. A phase that "
            "refused or merely signed off produced nothing a later phase can "
            "act on; storing it launders an empty run into a passing one."
        )
        assert run.stored == [], f"nothing may be stored for {says!r}, got {run.stored}"
        assert run.agent.call_count == 1, "the downstream phase must not run on a refusal"

    async def test_a_refusal_that_says_why_is_kept(self, clone: _Clone) -> None:
        """The asymmetry is deliberate and this is the half that is easy to lose.

        Discarding a finished run is what #1300 costs $38.62 a window; storing
        one unhelpful note costs a reader ten seconds. So a message that
        reports anything at all is salvaged, and a refusal carrying its reason
        reports the most useful thing in the run.
        """
        explained = (
            "I could not run the migration because the database credentials "
            "were never injected into the workspace; everything else is done."
        )
        run = await _run_writing_nothing(clone, says=explained)

        assert run.result.status == "completed", (  # type: ignore[attr-defined]
            f"got {run.result.status!r}. A refusal that explains itself is the "  # type: ignore[attr-defined]
            "single most useful thing this run produced - it tells the next "
            "phase what to fix. Dropping it is the bar set too high."
        )
        ((_, content),) = run.stored
        assert "credentials" in content, f"the reason must survive into the record: {content!r}"


class TestTheRecordSaysItWasSalvaged:
    """DEFECT 3. Whatever the status, the stored record must say how it got there.

    Read off the persisted events, not off the return value: an operator, a
    projection and anyone counting salvages across executions all read the
    stream, and a flag that only ever existed in a processor's return value
    would be invisible to every one of them.
    """

    async def _phase_completed_events(self, *, produces_a_file: bool) -> list[Any]:
        phases = _two_phase_workflow(first_declares=("markdown",))
        events = _EventStore()
        artifacts = _KeepingArtifacts()
        agent = _RecordingAgent(says=SAID)
        if produces_a_file:
            agent._produces = (("artifacts/output/deliverable.md", b"# The real report"),)  # pyright: ignore[reportPrivateUsage]

        process = _Process(events, InMemoryProjectionStore(), artifacts, agent)
        aggregate = _started(phases)
        await process.processor._journal.open(aggregate)  # pyright: ignore[reportPrivateUsage]
        await process.work(aggregate, phases)
        return events.events_named("PhaseCompleted")

    async def test_a_salvaged_phase_is_marked_in_its_phase_completed_event(self) -> None:
        completed = await self._phase_completed_events(produces_a_file=False)

        assert completed, "the phase never completed; the salvage path did not run"
        salvaged = completed[0]
        assert salvaged.deliverable_recovered is True, (
            "the salvaged phase's PhaseCompleted is indistinguishable from a "
            "clean one. A phase that completed with its declared contract "
            "broken must say so in the record, or nobody can tell how often "
            "the salvage fires or which runs are standing on it."
        )

    async def test_a_phase_that_wrote_its_deliverable_is_not_marked(self) -> None:
        """A flag that is always true says nothing, which is the failure mode here."""
        completed = await self._phase_completed_events(produces_a_file=True)

        assert completed, "the healthy phase never completed"
        assert completed[0].deliverable_recovered is False, (
            "a phase that wrote its deliverable was recorded as salvaged - the "
            "flag is stuck on and distinguishes nothing"
        )
