"""#1332: a failing run reports ITS spend, not a concurrent run's.

WHAT THE HAZARD IS. ``PhaseRuntime`` held what each phase had burned under the
phase id alone, and ``usage_for`` - the reader #1262 added so a killed phase
stops reporting zeros - asked the same way. Two runs of one workflow share
phase ids: both call their second phase "implement". So "what did implement
spend" had two true answers and returned whichever run recorded last, and the
run that recorded FIRST reported the other's counts as its own.

WHY THAT IS WORSE THAN A WRONG NUMBER. These counts exist to separate an exit
124 that stalled at 735 tokens from one that was working through 1.7M and
needed a bigger cap (#1262). The two demand opposite responses. A stalled run
wearing a busy run's totals does not read as missing data - it reads as a
measurement, and it argues for exactly the wrong one.

WHY THE INTERLEAVE IS PLACED AND NOT RACED. The defect needs one specific
order: a run records, the OTHER run records, the first run reads. Inside a
single ``run()`` nothing comes between a phase's own record and its own read,
so no sequence of whole runs can produce it and ``asyncio.gather`` produces it
only by luck - a test that depended on that would pass for scheduling reasons
and stop catching this the day the scheduler changed. So the foreign record is
made directly, through the same ``record_agent_run`` the other run would have
called, and the failure path is then driven for real from there. The last test
needs no placement at all: ``harvest`` is on the success path, so one whole
run really can pop an entry out from under a concurrent one.

THE FIXTURES ARE THE #1262 INCIDENT'S OWN NUMBERS, in both directions, and
neither can arise from a default: every token field on ``PhaseResult``, on
``WorkflowFailed`` and in the projection defaults to 0, so a run that reports
its own counts cannot be one that reported nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    AgentVerdict,
    PhaseUsage,
    StreamResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseResult,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
    )

pytestmark = pytest.mark.unit

#: The phase id both runs use, which is the whole premise: a workflow's phases
#: are named by the workflow, so every run of it names them identically.
PHASE_ID = "implement"

WORKFLOW_ID = "wf-1332"

#: The overnight run that stalled: 735 tokens against an hour-long budget.
STALLED = PhaseUsage(
    input_tokens=190,
    output_tokens=545,
    cache_creation_tokens=13,
    cache_read_tokens=27,
)

#: The runs from the same day that were genuinely working and needed a bigger
#: cap. Orders of magnitude away from STALLED, because that distance is what
#: the counts are read for - and what makes a swap between the two unmissable.
BUSY = PhaseUsage(
    input_tokens=180_400,
    output_tokens=94_100,
    cache_creation_tokens=22_000,
    cache_read_tokens=1_400_000,
)

STALLED_EXECUTION = "exec-1332-stalled"
BUSY_EXECUTION = "exec-1332-busy"


class _EventStore:
    """An execution repository that keeps every event the runs commit.

    Both runs share it, as two dispatches of one workflow share a store, so a
    test can ask what a reader of the stream actually received for each.
    """

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return None

    def failure_for(self, execution_id: str) -> WorkflowFailedEvent:
        """The one WorkflowFailed this execution put on the stream."""
        matching = [
            e.event
            for e in self.envelopes
            if isinstance(e.event, WorkflowFailedEvent) and e.event.execution_id == execution_id
        ]
        assert len(matching) == 1, (
            f"expected exactly one WorkflowFailed for {execution_id}, got {len(matching)}"
        )
        return matching[0]


def _name_of(event: object) -> str:
    return getattr(event, "event_type", type(event).__name__)


async def _read_by_the_detail_projection(
    stream: _EventStore, execution_id: str
) -> WorkflowExecutionDetail:
    """Build the execution record an operator opens, from the runs' own events.

    Fed the WHOLE shared stream, not one run's slice, because that is what the
    projection consumes in production and the point at issue is whether two
    executions' numbers stay apart once they are in one place.
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for envelope in stream.envelopes:
        handler_name = ExecutionJournal._event_type_to_handler(  # pyright: ignore[reportPrivateUsage]
            _name_of(envelope.event)
        )
        handler = getattr(projection, handler_name, None)
        if handler:
            await handler(
                ExecutionJournal._serialize_event(envelope.event)  # pyright: ignore[reportPrivateUsage]
            )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id)
    assert record is not None, f"the projection must have stored {execution_id}"
    return WorkflowExecutionDetail.from_dict(record)


def _the_phase() -> list[ExecutablePhase]:
    """One phase, declaring no output - this is about what a run SPENT.

    A declared-but-unwritten output would fail every run here at collection
    (#1167) for a reason none of them is about.
    """
    return [
        ExecutablePhase(
            phase_id=PHASE_ID,
            name="implement",
            order=1,
            description="A phase two runs of this workflow both have",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=(),
            timeout_seconds=1200,
        )
    ]


def _an_agent_that_spent(usage: PhaseUsage, *, execution_id: str) -> AgentExecutionResult:
    """What the handler hands back when a run's agent returns.

    Built here rather than taken from a run because this stands in for the
    CONCURRENT run - the one whose record lands between this run's own record
    and its read. It carries the counts the same way the real handler does, on
    the command, which is where ``record_agent_run`` reads them.
    """
    tokens = TokenAccumulator()
    tokens.record(
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_creation_tokens,
        usage.cache_read_tokens,
    )
    return AgentExecutionResult(
        stream_result=StreamResult(
            line_count=0,
            interrupt_requested=False,
            interrupt_reason=None,
            verdict=AgentVerdict.from_agent_text(None),
        ),
        tokens=tokens,
        subagents=SubagentTracker(),
        command=AgentExecutionCompletedCommand(
            execution_id=execution_id,
            phase_id=PHASE_ID,
            session_id=f"sess-{execution_id}",
            exit_code=124,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            cache_read_tokens=usage.cache_read_tokens,
        ),
    )


class _NoRepo:
    async def save(self, _aggregate: object) -> None:
        return None


def _a_session_for(execution_id: str) -> SessionLifecycleManager:
    """The open session a dispatched phase leaves behind, per execution."""
    return SessionLifecycleManager(
        repository=_NoRepo(),  # pyright: ignore[reportArgumentType]
        session_id=f"sess-{execution_id}",
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        phase_id=PHASE_ID,
        agent_provider="claude",
        agent_model=None,
        observability=None,
    )


def _a_started_run(execution_id: str) -> WorkflowExecutionAggregate:
    """An aggregate at the point a phase is running - where a timeout finds it."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            workflow_name="sdlc-implement",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            phase_id=PHASE_ID,
            phase_name="implement",
            phase_order=1,
            session_id=f"sess-{execution_id}",
        )
    )
    return aggregate


async def _fail(
    processor: WorkflowExecutionProcessor,
    stream: _EventStore,
    execution_id: str,
) -> PhaseResult:
    """Drive one run's real failure path to the end, and return its phase record.

    ``_fail_execution`` is entered directly because it is the outermost frame
    that contains the read under test: ``run()`` above it would re-record this
    run's own counts first, which is precisely the ordering the defect does not
    occur in.
    """
    aggregate = _a_started_run(execution_id)
    await stream.save(aggregate)
    # A phase with no recorded start produces no result at all, so the runtime
    # has to be holding this one the way a real dispatch left it. `_started_at`
    # and the session manager are still keyed by phase alone - that is #1311,
    # and it is why this is set immediately before the failure it belongs to.
    processor._runtime.begin(  # pyright: ignore[reportPrivateUsage]
        PHASE_ID,
        session_manager=_a_session_for(execution_id),
        started_at=datetime.now(UTC),
    )
    result = await processor._fail_execution(  # pyright: ignore[reportPrivateUsage]
        error=RuntimeError(f"Agent execution failed for phase {PHASE_ID} (exit_code=124)"),
        aggregate=aggregate,
        execution_id=execution_id,
        workflow_id=WORKFLOW_ID,
        phases=_the_phase(),
        phase_results=[],
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=datetime.now(UTC),
        failed_phase_id=PHASE_ID,
    )
    assert result.status == "failed", f"fixture: expected a failed run, got {result.status}"
    assert len(result.phase_results) == 1
    return result.phase_results[0]


def _two_runs_interleaved() -> tuple[WorkflowExecutionProcessor, _EventStore]:
    """One processor, with both runs' agents having returned and neither reported.

    The stalled run records FIRST, so under a phase-only key it is the one that
    reads back the other's totals. Both are on the same ``PhaseRuntime``,
    because that is the situation: ``BackgroundWorkflowDispatcher`` hands one
    processor to every execution it dispatches.
    """
    processor = _make_processor(FakeAgentExecutionHandler.failed(exit_code=124))
    stream = _EventStore()
    processor._journal = ExecutionJournal(  # pyright: ignore[reportPrivateUsage]
        stream,
        processor._todo_projection,  # pyright: ignore[reportPrivateUsage]
    )
    runtime = processor._runtime  # pyright: ignore[reportPrivateUsage]
    runtime.record_agent_run(
        PHASE_ID,
        execution_id=STALLED_EXECUTION,
        result=_an_agent_that_spent(STALLED, execution_id=STALLED_EXECUTION),
    )
    runtime.record_agent_run(
        PHASE_ID,
        execution_id=BUSY_EXECUTION,
        result=_an_agent_that_spent(BUSY, execution_id=BUSY_EXECUTION),
    )
    return processor, stream


class TestTwoFailingRunsReportTheirOwnSpend:
    """Both died on the same phase id of the same workflow, minutes apart."""

    async def test_the_phase_result_carries_only_this_run_s_counts(self) -> None:
        """The stalled run recorded first, so it is the one that read back the
        busy run's 1.7M tokens - the reading that would have bought a stalled
        phase a bigger budget and another hour of nothing."""
        processor, stream = _two_runs_interleaved()

        stalled = await _fail(processor, stream, STALLED_EXECUTION)
        busy = await _fail(processor, stream, BUSY_EXECUTION)

        assert (stalled.input_tokens, stalled.output_tokens) == (190, 545)
        assert (stalled.cache_creation_tokens, stalled.cache_read_tokens) == (13, 27)
        assert stalled.total_tokens == 775

        assert (busy.input_tokens, busy.output_tokens) == (180_400, 94_100)
        assert (busy.cache_creation_tokens, busy.cache_read_tokens) == (22_000, 1_400_000)
        assert busy.total_tokens == 1_696_500

    async def test_each_failure_event_carries_only_its_own_counts(self) -> None:
        """The result reaches one caller; the EVENT is what every other reader
        gets and all a restart leaves behind. Two executions' events sit in one
        stream, which is where a shared key stops being recoverable."""
        processor, stream = _two_runs_interleaved()
        await _fail(processor, stream, STALLED_EXECUTION)
        await _fail(processor, stream, BUSY_EXECUTION)

        stalled = stream.failure_for(STALLED_EXECUTION)
        busy = stream.failure_for(BUSY_EXECUTION)

        assert stalled.failed_phase_input_tokens == 190
        assert stalled.failed_phase_output_tokens == 545
        assert stalled.failed_phase_cache_creation_tokens == 13
        assert stalled.failed_phase_cache_read_tokens == 27

        assert busy.failed_phase_input_tokens == 180_400
        assert busy.failed_phase_output_tokens == 94_100
        assert busy.failed_phase_cache_creation_tokens == 22_000
        assert busy.failed_phase_cache_read_tokens == 1_400_000

    async def test_each_execution_record_shows_only_its_own_counts(self) -> None:
        """What an operator opens. Both runs' events go through one projection,
        so this is the first place the two could be confused for one."""
        processor, stream = _two_runs_interleaved()
        await _fail(processor, stream, STALLED_EXECUTION)
        await _fail(processor, stream, BUSY_EXECUTION)

        stalled = (await _read_by_the_detail_projection(stream, STALLED_EXECUTION)).phases[0]
        busy = (await _read_by_the_detail_projection(stream, BUSY_EXECUTION)).phases[0]

        assert (stalled.input_tokens, stalled.output_tokens) == (190, 545)
        assert (stalled.cache_creation_tokens, stalled.cache_read_tokens) == (13, 27)
        assert (busy.input_tokens, busy.output_tokens) == (180_400, 94_100)
        assert (busy.cache_creation_tokens, busy.cache_read_tokens) == (22_000, 1_400_000)

    async def test_the_two_are_still_told_apart_at_the_end(self) -> None:
        """The comparison the counts exist for. Both are exit 124 on the same
        phase of the same workflow; nothing but these numbers separates 'stop
        paying for this retry' from 'raise the cap'. A shared key made them
        equal, which is the one answer that is wrong for both runs."""
        processor, stream = _two_runs_interleaved()
        stalled = await _fail(processor, stream, STALLED_EXECUTION)
        busy = await _fail(processor, stream, BUSY_EXECUTION)

        assert stalled.total_tokens != busy.total_tokens
        assert busy.total_tokens > stalled.total_tokens * 100


class TestACompletingRunLeavesAConcurrentRunItsCounts:
    """`harvest` is the other reader of the same map, and it POPS.

    No placement is needed here: this is two whole runs, one of which completes
    while the other is still going. Under a phase-only key the completing run
    takes the entry with it, and the run still running then dies reporting the
    zeros that #1262 exists to stop it reporting.
    """

    async def test_a_run_that_completes_does_not_take_the_other_run_s_counts(self) -> None:
        processor = _make_processor(FakeAgentExecutionHandler.success(spent=STALLED))
        stream = _EventStore()
        processor._journal = ExecutionJournal(  # pyright: ignore[reportPrivateUsage]
            stream,
            processor._todo_projection,  # pyright: ignore[reportPrivateUsage]
        )
        # The busy run's agent has returned and the run has not reported yet.
        processor._runtime.record_agent_run(  # pyright: ignore[reportPrivateUsage]
            PHASE_ID,
            execution_id=BUSY_EXECUTION,
            result=_an_agent_that_spent(BUSY, execution_id=BUSY_EXECUTION),
        )

        # A whole other run of the same workflow starts, succeeds and harvests.
        completed = await processor.run(
            workflow_id=WORKFLOW_ID,
            workflow_name="sdlc-implement",
            phases=_the_phase(),
            inputs={},
            execution_id=STALLED_EXECUTION,
        )
        assert completed.status == "completed", f"fixture: got {completed.status}"
        assert completed.phase_results[0].input_tokens == 190, (
            "the completing run must report what IT spent - the write side of the same key"
        )

        busy = await _fail(processor, stream, BUSY_EXECUTION)

        assert (busy.input_tokens, busy.output_tokens) == (180_400, 94_100)
        assert (busy.cache_creation_tokens, busy.cache_read_tokens) == (22_000, 1_400_000)
