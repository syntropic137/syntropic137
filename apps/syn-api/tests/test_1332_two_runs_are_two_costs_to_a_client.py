"""#1332: two runs of one workflow reach a client as two costs, not one twice.

WHAT THIS IS THE LAST HOP OF. `PhaseRuntime` held what each phase had spent
under the phase id alone. Two runs of a workflow name their phases identically -
both have an "implement" - so the run that recorded FIRST read back the other
run's totals on its way out, and every sink downstream received them as its own:
the result, the failure event, the execution record, and the response an
operator's client renders.

WHY IT ENDS HERE RATHER THAN AT THE PROJECTION. The counts cross five hops that
each re-list their fields by hand, and this repository has dropped a field at
exactly such a hop three times (#891, #1176, #1300). The domain side of this is
pinned in
``packages/syn-domain/tests/.../test_1332_a_run_reports_its_own_spend.py``;
what is added here is the half no domain test can see - that two executions
mapped through the same response builder still arrive as two different numbers.

WHY THE INTERLEAVE IS PLACED AND NOT RACED. The defect needs a run to record,
the OTHER run to record, and the first run to read. Nothing comes between a
phase's own record and its own read inside one ``run()``, so the foreign record
is made directly, through the same ``record_agent_run`` the concurrent run
would have called. See the domain test for the full argument.

THE FIXTURES ARE THE #1262 INCIDENT'S, in both directions, and neither can
arise from a default: every token field defaults to 0 from the projection
through to the response model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_api.routes.executions.phase_mapping import _map_phase_detail, _map_phase_to_response
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
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope

    from syn_api.routes.executions.models import PhaseExecutionInfo

pytestmark = pytest.mark.unit

#: The phase id both runs use - the premise. A workflow names its own phases,
#: so every run of it names them the same.
PHASE_ID = "implement"
WORKFLOW_ID = "wf-1332"

STALLED_EXECUTION = "exec-1332-stalled"
BUSY_EXECUTION = "exec-1332-busy"

#: The overnight run that stalled: 735 tokens against an hour-long budget.
STALLED = PhaseUsage(
    input_tokens=190, output_tokens=545, cache_creation_tokens=13, cache_read_tokens=27
)

#: The runs from the same day that were working and needed a bigger cap. The
#: distance between the two is what a client is read for.
BUSY = PhaseUsage(
    input_tokens=180_400,
    output_tokens=94_100,
    cache_creation_tokens=22_000,
    cache_read_tokens=1_400_000,
)


class _Stream:
    """The execution repository both runs commit to, keeping what they wrote."""

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope[DomainEvent]] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.envelopes.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        return None


class _NoTodoList:
    """A to-do projection with no handlers - the failure path never reads it.

    A ``MagicMock`` cannot stand in here: the journal looks up a handler per
    event and a mock answers every lookup with something that is not awaitable.
    """


def _a_processor(stream: _Stream) -> WorkflowExecutionProcessor:
    """One processor, as ``BackgroundWorkflowDispatcher`` hands to every run.

    Everything the failure path does not touch is a double. It touches the
    runtime it owns and the journal, and those are real.
    """
    return WorkflowExecutionProcessor(
        execution_repository=stream,  # pyright: ignore[reportArgumentType]
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="prompt"),
        command_builder=MagicMock(return_value=["claude"]),
        todo_projection=_NoTodoList(),  # pyright: ignore[reportArgumentType]
    )


class _NoRepo:
    async def save(self, _aggregate: object) -> None:
        return None


def _an_agent_that_spent(usage: PhaseUsage, *, execution_id: str) -> AgentExecutionResult:
    """What a run's handler hands back when its agent returns, with its counts
    on the command - which is where ``record_agent_run`` reads them."""
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


def _the_phase() -> list[ExecutablePhase]:
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


async def _run_that_died(
    processor: WorkflowExecutionProcessor, stream: _Stream, execution_id: str
) -> None:
    """Drive one run's real failure path, from a started phase to its event."""
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
    await stream.save(aggregate)
    # A phase with no recorded start produces no result at all, so the runtime
    # has to be holding this one the way a real dispatch left it.
    processor._runtime.begin(  # pyright: ignore[reportPrivateUsage]
        PHASE_ID,
        session_manager=SessionLifecycleManager(
            repository=_NoRepo(),  # pyright: ignore[reportArgumentType]
            session_id=f"sess-{execution_id}",
            workflow_id=WORKFLOW_ID,
            execution_id=execution_id,
            phase_id=PHASE_ID,
            agent_provider="claude",
            agent_model=None,
            observability=None,
        ),
        started_at=datetime.now(UTC),
    )
    await processor._fail_execution(  # pyright: ignore[reportPrivateUsage]
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


def _name_of(event: object) -> str:
    return getattr(event, "event_type", type(event).__name__)


class _NoTimeline:
    """Lane 2 with nothing to say. The activity summary is a separate signal
    and is pinned next door; this is about the counts."""

    async def get_session_tools(self, _session_id: str) -> None:
        return None


async def _as_a_client_sees_it(stream: _Stream, execution_id: str) -> PhaseExecutionInfo:
    """The failed phase of one execution, as the response model a client gets.

    The projection is fed the WHOLE shared stream, not one run's slice, because
    that is what it consumes in production and the question is whether two
    executions' numbers stay apart once they are in one place.
    """
    store = InMemoryProjectionStore()
    projection = WorkflowExecutionDetailProjection(store)
    for envelope in stream.envelopes:
        handler = getattr(
            projection,
            ExecutionJournal._event_type_to_handler(_name_of(envelope.event)),  # pyright: ignore[reportPrivateUsage]
            None,
        )
        if handler:
            await handler(
                ExecutionJournal._serialize_event(envelope.event)  # pyright: ignore[reportPrivateUsage]
            )

    record = await store.get(WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id)
    assert record is not None, f"the projection must have stored {execution_id}"
    detail = WorkflowExecutionDetail.from_dict(record)
    mapped = await _map_phase_detail(detail.phases[0], _NoTimeline(), {})  # pyright: ignore[reportArgumentType]
    return _map_phase_to_response(mapped)


async def _two_runs_that_died_on_the_same_phase() -> _Stream:
    """Both runs' agents returned, the stalled one first, and both then died."""
    stream = _Stream()
    processor = _a_processor(stream)
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
    await _run_that_died(processor, stream, STALLED_EXECUTION)
    await _run_that_died(processor, stream, BUSY_EXECUTION)
    return stream


async def test_the_stalled_run_is_served_its_own_735_tokens() -> None:
    """It recorded first, so under a shared key this is where an operator read
    1.7M tokens against a phase that had done nothing - and raised the budget."""
    stream = await _two_runs_that_died_on_the_same_phase()

    phase = await _as_a_client_sees_it(stream, STALLED_EXECUTION)

    assert phase.input_tokens == 190
    assert phase.output_tokens == 545
    assert phase.cache_creation_tokens == 13
    assert phase.cache_read_tokens == 27


async def test_the_busy_run_is_served_its_own_1_7m_tokens() -> None:
    """The other side of the same map, unchanged by the run beside it."""
    stream = await _two_runs_that_died_on_the_same_phase()

    phase = await _as_a_client_sees_it(stream, BUSY_EXECUTION)

    assert phase.input_tokens == 180_400
    assert phase.output_tokens == 94_100
    assert phase.cache_creation_tokens == 22_000
    assert phase.cache_read_tokens == 1_400_000


async def test_two_exit_124s_on_one_phase_id_are_two_served_answers() -> None:
    """The comparison the counts exist for, at the only place it is made.

    Both runs are exit 124 on the same phase of the same workflow. Nothing but
    these numbers separates 'stop paying for this retry' from 'raise the cap',
    and a shared key served them as equal - the one answer wrong for both.
    """
    stream = await _two_runs_that_died_on_the_same_phase()

    stalled = await _as_a_client_sees_it(stream, STALLED_EXECUTION)
    busy = await _as_a_client_sees_it(stream, BUSY_EXECUTION)

    assert stalled.input_tokens != busy.input_tokens
    assert busy.input_tokens > stalled.input_tokens * 100
