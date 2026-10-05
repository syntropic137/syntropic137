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

import re
from pathlib import Path
from typing import TypedDict

import pytest
from event_sourcing import ConcurrencyConflictError

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    EventsNotRecordedError,
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


class _ConflictingRepository(_ClearingRepository):
    """A stream another writer has already advanced: every append is refused."""

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self._trace.append("save")
        raise ConcurrencyConflictError(expected_version=1, actual_version=2)


@pytest.mark.unit
async def test_a_stream_conflict_reaches_the_caller_wrapped_with_its_cause() -> None:
    """ADR-072 D5 tells the reconciler to reload on a conflict; this is what it catches.

    The conflict is not what escapes `append`: the wrapper is, and the
    conflict is only its cause. A caller written against the bare conflict
    never sees it, and treats a stale read as any other lost write.
    """
    trace: list[str] = []
    projection = _RecordingProjection(trace)
    journal = ExecutionJournal(_ConflictingRepository(trace), projection)
    aggregate = _running_aggregate()
    aggregate.mark_events_as_committed()
    _raise_phase_started(aggregate, "phase-a")

    with pytest.raises(EventsNotRecordedError) as raised:
        await journal.append(aggregate)

    assert isinstance(raised.value.__cause__, ConcurrencyConflictError)
    assert projection.phases_started == [], "nothing was written, so nothing is projected"


def _adr_072_d5() -> str:
    """The D5 section of ADR-072, which states what the journal raises."""
    root = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "adrs").is_dir())
    (adr,) = (root / "docs" / "adrs").glob("ADR-072-*.md")
    text = adr.read_text()
    start = text.index("### D5.")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def _defined_exception_names() -> set[str]:
    """Every exception class the journal's callers can see, by name."""
    root = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "adrs").is_dir())
    sources = [
        root / "packages",
        root / "apps",
        root / "lib" / "event-sourcing-platform" / "event-sourcing" / "python" / "src",
    ]
    names: set[str] = set()
    for source in sources:
        for path in source.rglob("*.py"):
            names.update(re.findall(r"^class (\w+Error)\b", path.read_text(), re.MULTILINE))
    return names


@pytest.mark.unit
def test_adr_072_d5_names_only_exceptions_the_code_raises() -> None:
    """The reconciler is built from D5's prose, so its exception names must be real.

    D5 once said the journal raised `ConcurrencyError`, a class that exists
    nowhere: a reconciler written from it would catch nothing and never reload.
    """
    section = _adr_072_d5()
    named = set(re.findall(r"`(\w+Error)`", section))
    assert {"EventsNotRecordedError", "ConcurrencyConflictError"} <= named
    assert named <= _defined_exception_names(), named - _defined_exception_names()
