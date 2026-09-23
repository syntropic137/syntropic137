"""#1262: a phase killed at its timeout must report what it burned getting there.

THE INCIDENT. Overnight a phase hit ``exit_code=124`` against a 1200s budget
having produced 735 tokens. It was not doing anything - it had stalled. Other
124s the same day carried 171-377 messages and 64-133 tool calls; those were
working and needed a bigger cap. Same exit code, opposite responses, and the
execution record separated them by nothing: every failed phase reported zero
tokens, because the only handler that had ever written those fields was
``PhaseCompleted`` and a phase that dies never gets one.

The counts were not missing, they were unread. ``FinalUsage.resolve`` had
already settled them - the harness's own totals when it reported, the observed
deltas when it was killed before it could - and ``PhaseRuntime`` was still
holding them when ``_fail_execution`` ran. The only place they survived was the
prose ``(tokens=190+545)`` inside ``error_message``, parseable by a human and by
nothing else. The stalled run was the retry unblocking a performance fix, so the
absent field cost a cycle as well as money.

WHY THESE DRIVE ``run()`` RATHER THAN THE OBJECTS UNDER IT. There are five hops
between the runtime holding a count and an operator reading it - the runtime,
the ``PhaseFailure``, the command, the event, the projection - and each one
re-lists its fields by hand. Asserting at either end catches nothing in the
middle, which is how this field came to be lost in the first place. So the
counts are put in where the system observes them, through a real ``run()`` with
a real timeout, and read out of the event that run emitted and the read model
built from it. The remaining hop, from that read model to the served response,
is pinned beside the other #1262 signals in
``apps/syn-api/tests/test_timeout_vs_stall_signals.py``.

THE FIXTURES ARE THE INCIDENT'S OWN NUMBERS, and none of them can arise from a
default: every token field on ``PhaseResult``, on ``WorkflowFailed`` and in the
projection defaults to 0, so a hop that drops one reports 0 and fails rather
than coincidentally agreeing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    PhaseUsage,
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
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        WorkflowExecutionResult,
    )

pytestmark = pytest.mark.unit

#: The overnight run, verbatim: 735 tokens against a 1200s budget, killed 124.
#: The cache counts are set too, because they are two of four hops that can be
#: dropped independently and a fixture leaving them zero could not tell a
#: dropped cache field from a defaulted one.
STALLED = PhaseUsage(
    input_tokens=190,
    output_tokens=545,
    cache_creation_tokens=13,
    cache_read_tokens=27,
)
STALLED_TOTAL = 775

#: The other 124s from that day: real work, and a budget that genuinely was too
#: small. Deliberately orders of magnitude away from STALLED, because telling
#: these two apart is the entire purpose of the field.
BUSY = PhaseUsage(
    input_tokens=180_400,
    output_tokens=94_100,
    cache_creation_tokens=22_000,
    cache_read_tokens=1_400_000,
)
BUSY_TOTAL = 1_696_500

#: A phase that did its work and then refused itself. Exit 0, so it leaves
#: through the OTHER raise in `_handle_run_agent` (#1256) - and past the same
#: door, which is why its counts were lost identically.
REFUSED_ITSELF = (
    'TASK_RESULT: {"success": false, "comments": "blocked on a stale lock"}\nTASK_RESULT_END'
)

#: The real cap the incident's phase was given.
BUDGET_SECONDS = 1200

PHASE_ID = "implement"


class _EventStore:
    """An execution repository that keeps every event a run commits.

    Modelled on the one in ``test_1300_what_the_salvage_must_survive``: the
    journal reads the aggregate's uncommitted events and then saves, and the
    save marks them committed, so a repository is the last place the stream can
    be read whole. Keeping it is the point here - the event is what every
    reader except this run's own caller gets, and a count that reaches the
    returned result but not the stream is invisible to all of them.
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

    def the_failure(self) -> WorkflowFailedEvent:
        """The run's one WorkflowFailed, as a reader of the stream receives it."""
        matching = [e.event for e in self.envelopes if isinstance(e.event, WorkflowFailedEvent)]
        assert len(matching) == 1, (
            f"expected exactly one WorkflowFailed, got {len(matching)}; "
            f"stream was {[_name_of(e.event) for e in self.envelopes]}"
        )
        return matching[0]


def _name_of(event: object) -> str:
    return getattr(event, "event_type", type(event).__name__)


async def _read_by_the_detail_projection(
    stream: _EventStore, execution_id: str
) -> WorkflowExecutionDetail:
    """Build the execution record an operator reads, from the run's own events.

    Dispatch mirrors ``ExecutionJournal`` - and borrows its two rules rather
    than restating them, because a test that snake-cased handler names its own
    way could pass while production called nothing at all.
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
    assert record is not None, "the projection must have stored the execution"
    return WorkflowExecutionDetail.from_dict(record)


def _a_phase_with_a_budget() -> list[ExecutablePhase]:
    """One phase, given the budget the incident's phase had.

    It declares no output artifact: this is about what a phase SPENT, and a
    declared-but-unwritten output would fail every run here at collection
    (#1167) for a reason none of them is about.
    """
    return [
        ExecutablePhase(
            phase_id=PHASE_ID,
            name="implement",
            order=1,
            description="A phase that burns tokens and is then killed",
            agent_config=AgentConfiguration(),
            prompt_template="do the thing",
            output_artifact_types=(),
            timeout_seconds=BUDGET_SECONDS,
        )
    ]


async def _run(
    handler: FakeAgentExecutionHandler, execution_id: str
) -> tuple[WorkflowExecutionResult, _EventStore]:
    """One whole run, keeping its event stream."""
    processor = _make_processor(handler)
    stream = _EventStore()
    processor._journal = ExecutionJournal(  # pyright: ignore[reportPrivateUsage]
        stream,
        processor._todo_projection,  # pyright: ignore[reportPrivateUsage]
    )
    result = await processor.run(
        workflow_id="wf-1262",
        workflow_name="sdlc-implement",
        phases=_a_phase_with_a_budget(),
        inputs={},
        execution_id=execution_id,
    )
    return result, stream


def _the_failed_phase(result: WorkflowExecutionResult) -> PhaseResult:
    assert result.status == "failed", f"fixture: expected a failed run, got {result.status}"
    assert len(result.phase_results) == 1
    return result.phase_results[0]


class TestATimedOutPhaseReportsWhatItSpent:
    """exit 124 - the case the issue is about."""

    async def test_the_phase_result_carries_the_counts(self) -> None:
        """Every one of these was the 0 its field defaults to before now."""
        result, _ = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-result",
        )
        phase = _the_failed_phase(result)

        assert phase.input_tokens == 190
        assert phase.output_tokens == 545
        assert phase.cache_creation_tokens == 13
        assert phase.cache_read_tokens == 27
        assert phase.total_tokens == STALLED_TOTAL, "the four summed, not one of them alone"

    async def test_the_failure_event_carries_the_counts(self) -> None:
        """The result goes to one caller; the EVENT is what every other reader
        gets, and after a restart it is the only thing left. A count that
        reaches the first and not the second is invisible to every operator."""
        _, stream = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-event",
        )
        failed = stream.the_failure()

        assert failed.failed_phase_input_tokens == 190
        assert failed.failed_phase_output_tokens == 545
        assert failed.failed_phase_cache_creation_tokens == 13
        assert failed.failed_phase_cache_read_tokens == 27

    async def test_the_counts_are_no_longer_only_prose_in_the_error_message(self) -> None:
        """`(tokens=190+545)` was the whole of the old record, and it is gone on
        purpose: it reported the RAW accumulated deltas, which double-count the
        context re-sent each turn, where the fields carry what `FinalUsage`
        resolved. Keeping both would put two disagreeing numbers on one phase."""
        _, stream = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-no-prose",
        )
        message = stream.the_failure().error_message

        assert "tokens=" not in message
        assert "exit_code=124" in message, (
            "removing the token prose must not take the exit status with it - "
            "that is the other half of the triage"
        )

    async def test_a_stalled_phase_and_a_busy_one_are_told_apart(self) -> None:
        """The comparison the whole change is for. Both are exit 124 on the same
        budget, so the counts are the only thing that can separate them.

        Asserted as "these differ" as well as by value: two constants can drift
        back into agreement while both single-case assertions still pass, and
        agreement is precisely the defect."""
        stalled, _ = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-stalled",
        )
        busy, _ = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=BUSY),
            "exec-1262-busy",
        )

        assert _the_failed_phase(stalled).total_tokens == STALLED_TOTAL
        assert _the_failed_phase(busy).total_tokens == BUSY_TOTAL
        assert _the_failed_phase(stalled).total_tokens != _the_failed_phase(busy).total_tokens


class TestAPhaseThatRefusedItselfLeavesThroughTheSameDoor:
    """A reported failure lost these counts identically, one branch away.

    `_handle_run_agent` raises twice - once for a refusal it read, once for a
    non-zero exit - and both unwind to `_fail_execution`, which is where the
    counts are now read. Fixing the exit path alone would have left an
    identical instance of the same bug beside it.
    """

    async def test_a_refused_phase_still_reports_what_it_spent(self) -> None:
        result, stream = await _run(
            FakeAgentExecutionHandler.success(says=REFUSED_ITSELF, spent=STALLED),
            "exec-1262-refused",
        )
        phase = _the_failed_phase(result)

        assert phase.input_tokens == 190
        assert phase.output_tokens == 545
        assert phase.total_tokens == STALLED_TOTAL
        assert stream.the_failure().failed_phase_output_tokens == 545


class TestTheCountsReachTheRecordAnOperatorReads:
    """Through the real projection, fed the events the run actually emitted."""

    async def test_the_failed_phase_in_the_execution_detail_carries_them(self) -> None:
        """The projection is the hop that matters most - it is what the API
        serves from, and `on_phase_completed` was the only handler that had
        ever written these keys."""
        _, stream = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-projected",
        )

        detail = await _read_by_the_detail_projection(stream, "exec-1262-projected")
        assert len(detail.phases) == 1
        phase = detail.phases[0]

        assert phase.status == "failed"
        assert phase.input_tokens == 190
        assert phase.output_tokens == 545
        assert phase.cache_creation_tokens == 13
        assert phase.cache_read_tokens == 27
        assert phase.total_tokens == STALLED_TOTAL

    async def test_the_execution_totals_stop_under_reporting_the_run(self) -> None:
        """They accumulated from completed phases only, so a run whose single
        phase died reported having spent nothing at all - the same under-report
        its DURATION made before #1036."""
        _, stream = await _run(
            FakeAgentExecutionHandler.failed(exit_code=124, spent=STALLED),
            "exec-1262-totals",
        )

        detail = await _read_by_the_detail_projection(stream, "exec-1262-totals")

        assert detail.total_input_tokens == 190
        assert detail.total_output_tokens == 545
        assert detail.total_cache_creation_tokens == 13
        assert detail.total_cache_read_tokens == 27


class TestWhatDidNotChange:
    """Guards on the answers that were already right."""

    async def test_a_phase_that_spent_nothing_reports_zeros(self) -> None:
        """Zero is the honest answer for a phase whose process never got
        anywhere - it spent nothing. There is deliberately no "unknown" to tell
        apart from it, which is what keeps a None out of all five hops above."""
        result, stream = await _run(
            FakeAgentExecutionHandler.never_launched(exit_code=1),
            "exec-1262-never-ran",
        )
        phase = _the_failed_phase(result)

        assert (phase.input_tokens, phase.output_tokens) == (0, 0)
        assert phase.total_tokens == 0
        assert stream.the_failure().failed_phase_input_tokens == 0

    async def test_a_clean_run_still_reports_its_own_tokens(self) -> None:
        """The success path settles its counts somewhere else entirely and must
        not have been disturbed: a phase that completes still says what it
        spent, and the run still completes."""
        result, _ = await _run(
            FakeAgentExecutionHandler.success(
                says='TASK_RESULT: {"success": true, "comments": "done"}\nTASK_RESULT_END',
                spent=STALLED,
            ),
            "exec-1262-clean",
        )

        assert result.status == "completed"
        assert result.phase_results[0].input_tokens == 190
        assert result.phase_results[0].total_tokens == STALLED_TOTAL
