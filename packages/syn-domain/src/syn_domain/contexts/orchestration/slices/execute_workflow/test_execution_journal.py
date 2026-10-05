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
from event_sourcing import ConcurrencyConflictError, DomainEvent, EventEnvelope, EventStoreError

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
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


class _CommitThenErrorRepository:
    """A store that commits the append and then loses the response.

    The gRPC client raises `EventStoreError` for any non-ABORTED RPC failure
    after `Append` was sent, and the server may already have committed by then.
    The stream is kept here so a reload sees what was really written.
    """

    def __init__(self) -> None:
        self.stream: list[EventEnvelope[DomainEvent]] = []
        self.lose_next_ack = False

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.stream.extend(aggregate.get_uncommitted_events())
        aggregate.mark_events_as_committed()
        if self.lose_next_ack:
            self.lose_next_ack = False
            raise EventStoreError("Failed to append events: connection reset")

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        aggregate = WorkflowExecutionAggregate()
        aggregate.rehydrate(list(self.stream))
        return aggregate


async def _interrupt_per_adr_072_d5(
    repository: _CommitThenErrorRepository, journal: ExecutionJournal, lost: list[BaseException]
) -> bool:
    """One reconciliation turn of D5's step 1; True only when step 2 may close the row.

    Reload and ask the aggregate to interrupt; a terminal stream refuses and
    nothing is appended. On `EventsNotRecordedError` the row stays reaped and
    the turn records the cause, assuming nothing about what the store did.
    """
    aggregate = await repository.get_by_id(EXECUTION_ID)
    assert aggregate is not None
    try:
        aggregate._handle_command(  # pyright: ignore[reportPrivateUsage]
            InterruptExecutionCommand(execution_id=EXECUTION_ID, phase_id="phase-a")
        )
    except ValueError:
        pass
    else:
        try:
            await journal.append(aggregate)
        except EventsNotRecordedError as err:
            assert err.__cause__ is not None
            lost.append(err.__cause__)
            return False
    return aggregate.status is ExecutionStatus.INTERRUPTED


@pytest.mark.unit
async def test_a_lost_acknowledgment_is_not_proof_that_nothing_was_written() -> None:
    """ADR-072 D5: reload after an unacknowledged save, never re-append blind.

    The save commits and then reports an error. The wrapper is the same one a
    refused write raises, but the interruption is already in the stream. The
    next turn must find it there, append nothing, and only then free the slot.
    """
    repository = _CommitThenErrorRepository()
    journal = ExecutionJournal(repository, _RecordingProjection([]))
    await journal.open(_running_aggregate())
    repository.lose_next_ack = True
    lost: list[BaseException] = []

    assert not await _interrupt_per_adr_072_d5(repository, journal, lost), (
        "an unacknowledged save must not free the slot"
    )
    assert [type(cause) for cause in lost] == [EventStoreError]

    may_close = await _interrupt_per_adr_072_d5(repository, journal, lost)

    interruptions = [
        e for e in repository.stream if type(e.event).__name__ == "WorkflowInterruptedEvent"
    ]
    assert len(interruptions) == 1, "the interruption was written once, before the ack was lost"
    assert may_close, "the slot is freed once a reload shows the stream terminal"


_NO_WRITE = re.compile(
    r"nothing (?:was |is )?(?:written|appended)|wrote nothing|writes nothing|not durable"
)


@pytest.mark.unit
def test_adr_072_d5_claims_no_write_only_for_a_version_conflict() -> None:
    """Only a `ConcurrencyConflictError` cause proves the store wrote nothing.

    D5 once said every `EventsNotRecordedError` meant nothing was written. An
    RPC can fail after the store commits, and a reconciler that believed the
    ADR would append a second interruption instead of reloading.
    """
    prose = " ".join(_adr_072_d5().split())
    for sentence in re.split(r"(?<=\.)\s+", prose):
        if "`EventsNotRecordedError`" in sentence and _NO_WRITE.search(sentence):
            assert "`ConcurrencyConflictError`" in sentence, sentence


_NOT_SEEN = re.compile(
    r"nothing downstream will|never (?:be )?(?:seen|projected)|rejected the write"
)


@pytest.mark.unit
def test_events_not_recorded_error_never_promises_the_events_are_absent() -> None:
    """What a caller reads on the exception is what the ADR says, and no more.

    The docstring once said an unacknowledged save meant nothing downstream
    would see the events projected, two sentences before saying the store may
    have committed them; the message said the store "rejected" the write. Both
    told a reconciler it could append again without reloading.
    """
    texts = [" ".join((EventsNotRecordedError.__doc__ or "").split())]
    source = Path(__file__).with_name("execution_journal.py").read_text()
    (message,) = re.findall(r'raise EventsNotRecordedError\(\s*f"([^"]*)"', source)
    texts.append(message)
    for text in texts:
        assert not _NOT_SEEN.search(text), text
