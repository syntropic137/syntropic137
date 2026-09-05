"""The journal must hand the local to-do list every event the save just swallowed.

THE HOP THESE TESTS GUARD. A real `ExecutionRepository.save` clears the
aggregate's uncommitted events - that is how the next save avoids re-writing
them. So the events the projection needs exist only in the window before the
save, and `ExecutionJournal` has to snapshot them there and replay them
afterwards. Read them a line later and the aggregate is already empty: the save
succeeds, the processor sees no error, and the to-do list it is about to query
silently never moved. The doubles below therefore clear on save like the real
repository does; a double that kept the events would pass whatever order the
journal used, and prove nothing.

`open` and `append` carry the same three lines against different
expected-version rules, so both are exercised. Fixing the ordering in one and
not the other is the plausible mistake.
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)

EXECUTION_ID = "exec-journal-1"


class _StartedPayload(TypedDict):
    """The one field these tests read out of a serialised WorkflowExecutionStarted."""

    execution_id: str


class _PhaseStartedPayload(TypedDict):
    """The one field these tests read out of a serialised PhaseStarted."""

    phase_id: str


def _running_aggregate() -> WorkflowExecutionAggregate:
    """An aggregate holding one uncommitted WorkflowExecutionStarted."""
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartExecutionCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-1",
            workflow_name="Journal Test",
            total_phases=1,
            inputs={},
        )
    )
    return aggregate


def _raise_phase_started(aggregate: WorkflowExecutionAggregate, phase_id: str) -> None:
    """Give the aggregate one more uncommitted event to hand over."""
    aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
        StartPhaseCommand(
            execution_id=EXECUTION_ID,
            workflow_id="wf-1",
            phase_id=phase_id,
            phase_name=phase_id,
            phase_order=1,
        )
    )


class _ClearingRepository:
    """Stands in for the real repository: persisting is what empties the aggregate."""

    def __init__(self, trace: list[str]) -> None:
        self._trace = trace

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self._trace.append("save")
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        self._trace.append("save_new")
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        raise NotImplementedError


class _RecordingProjection:
    """Records every handler call the journal makes, and in what order."""

    def __init__(self, trace: list[str]) -> None:
        self._trace = trace
        self.started: list[str] = []
        self.phases_started: list[str] = []

    async def on_workflow_execution_started(self, event: _StartedPayload) -> None:
        self._trace.append("on_workflow_execution_started")
        self.started.append(event["execution_id"])

    async def on_phase_started(self, event: _PhaseStartedPayload) -> None:
        self._trace.append("on_phase_started")
        self.phases_started.append(event["phase_id"])

    async def get_pending(self, execution_id: str) -> list[object]:
        return []


@pytest.mark.unit
async def test_open_projects_the_events_the_save_consumed() -> None:
    """The first save empties the aggregate; the to-do list must still see the event."""
    trace: list[str] = []
    projection = _RecordingProjection(trace)
    journal = ExecutionJournal(_ClearingRepository(trace), projection)
    aggregate = _running_aggregate()

    await journal.open(aggregate)

    assert not aggregate.has_uncommitted_events(), (
        "the repository double must clear, like the real one"
    )
    assert projection.started == [EXECUTION_ID]
    assert trace == ["save_new", "on_workflow_execution_started"]


@pytest.mark.unit
async def test_append_projects_the_events_the_save_consumed() -> None:
    """Same hop on the append path, which every save after the first one takes."""
    trace: list[str] = []
    projection = _RecordingProjection(trace)
    journal = ExecutionJournal(_ClearingRepository(trace), projection)
    aggregate = _running_aggregate()
    aggregate.mark_events_as_committed()
    _raise_phase_started(aggregate, "phase-a")

    await journal.append(aggregate)

    assert projection.phases_started == ["phase-a"]
    assert trace == ["save", "on_phase_started"]


@pytest.mark.unit
async def test_every_pending_event_reaches_the_projection_in_order() -> None:
    """A save can swallow several events at once; none of them may be dropped."""
    trace: list[str] = []
    projection = _RecordingProjection(trace)
    journal = ExecutionJournal(_ClearingRepository(trace), projection)
    aggregate = _running_aggregate()
    _raise_phase_started(aggregate, "phase-a")

    await journal.open(aggregate)

    assert trace == ["save_new", "on_workflow_execution_started", "on_phase_started"]


@pytest.mark.unit
async def test_an_event_the_projection_ignores_is_not_an_error() -> None:
    """The to-do list handles a handful of lifecycle events and skips the rest."""
    trace: list[str] = []

    class _NarrowProjection:
        async def on_phase_started(self, event: _PhaseStartedPayload) -> None:
            trace.append("on_phase_started")

        async def get_pending(self, execution_id: str) -> list[object]:
            return []

    journal = ExecutionJournal(_ClearingRepository(trace), _NarrowProjection())
    aggregate = _running_aggregate()
    _raise_phase_started(aggregate, "phase-a")

    await journal.open(aggregate)

    assert trace == ["save_new", "on_phase_started"]
